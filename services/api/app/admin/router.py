"""
app/admin/router.py
FastAPI router for the /admin area.

Provides read-only overview endpoints for the NestAI administrator dashboard.
All routes require an authenticated admin user (enforced via the
`require_admin` dependency).

These are JSON API endpoints — connect a frontend or use the Swagger UI
at /docs to explore them.
"""

from datetime import datetime, timezone, timedelta
from typing import Annotated
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.auth.security import hash_password, verify_password, decode_access_token, normalize_email
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.feedback import FeedbackReport
from app.db.models.beta_access import BetaAccess
from app.db.models.credits import CreditBalance, CreditTransaction
from app.db.models.billing import BillingEvent
from app.db.models.ai_feedback import AICallLog

router = APIRouter(prefix="/admin", tags=["admin"])

_basic_security = HTTPBasic(auto_error=False)
_bearer_security = HTTPBearer(auto_error=False)


class BetaInviteCreateRequest(BaseModel):
    email_restriction: str | None = None
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_at: datetime | None = None


class BetaInviteRead(BaseModel):
    id: int
    email_restriction: str | None = None
    is_active: bool
    max_uses: int
    use_count: int
    expires_at: datetime | None = None
    created_by_id: int | None = None
    redeemed_by_id: int | None = None
    redeemed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BetaInviteCreateResponse(BetaInviteRead):
    invite_code: str


def _serialize_beta_invite(invite: BetaAccess) -> BetaInviteRead:
    return BetaInviteRead(
        id=invite.id,
        email_restriction=invite.email_hint,
        is_active=invite.is_active,
        max_uses=invite.max_uses,
        use_count=invite.use_count,
        expires_at=invite.expires_at,
        created_by_id=invite.created_by_id,
        redeemed_by_id=invite.redeemed_by_id,
        redeemed_at=invite.redeemed_at,
        created_at=invite.created_at,
        updated_at=invite.updated_at,
    )


# ── Auth dependency ────────────────────────────────────────────────────────────

def require_admin(
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_security)],
    basic: Annotated[HTTPBasicCredentials | None, Depends(_basic_security)],
    db: Session = Depends(get_db),
) -> User:
    """Accept either a JWT ****** or HTTP Basic credentials."""
    user: User | None = None

    if bearer and bearer.scheme.lower() == "bearer":
        try:
            payload = decode_access_token(bearer.credentials)
            user_id = payload.get("sub")
            if user_id is not None:
                user = db.query(User).filter(User.id == int(user_id)).first()
        except Exception:
            user = None

    if user is None and basic is not None:
        candidate = db.query(User).filter(User.email == normalize_email(basic.username)).first()
        if candidate and verify_password(basic.password, candidate.hashed_password):
            user = candidate

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# ── Overview ───────────────────────────────────────────────────────────────────

@router.get("/")
def admin_overview(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """High-level dashboard counts."""
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    user_count = db.query(User).count()
    beta_count = db.query(User).filter(User.beta_tester == True).count()  # noqa: E712
    premium_count = db.query(User).filter(User.tier == "premium").count()
    open_feedback = db.query(FeedbackReport).filter(
        FeedbackReport.status.in_(["new", "triaged", "in_progress"])
    ).count()
    active_beta_codes = db.query(BetaAccess).filter(BetaAccess.is_active == True).count()  # noqa: E712
    recent_ai_calls = db.query(AICallLog).filter(
        AICallLog.created_at >= thirty_days_ago
    ).count()

    return {
        "users": {"total": user_count, "beta_testers": beta_count, "premium": premium_count},
        "feedback": {"open": open_feedback},
        "beta_codes": {"active": active_beta_codes},
        "ai_calls_last_30d": recent_ai_calls,
    }


# ── Users ──────────────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(
    skip: int = 0,
    limit: int = 50,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "tier": u.tier,
            "is_admin": u.is_admin,
            "beta_tester": u.beta_tester,
            "is_active": u.is_active,
            "created_at": u.created_at,
        }
        for u in users
    ]


@router.post("/users/{user_id}/promote-beta")
def promote_to_beta(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.beta_tester = True
    db.commit()
    return {"message": f"User {user.email} promoted to beta tester"}


# ── Feedback ───────────────────────────────────────────────────────────────────

@router.get("/feedback")
def list_feedback(
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(FeedbackReport)
    if status:
        q = q.filter(FeedbackReport.status == status)
    reports = q.order_by(FeedbackReport.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": r.id,
            "public_reference": r.public_reference,
            "category": r.category,
            "title": r.title,
            "status": r.status,
            "severity": r.severity,
            "user_plan": r.user_plan,
            "created_at": r.created_at,
        }
        for r in reports
    ]


# ── Beta codes ─────────────────────────────────────────────────────────────────

@router.get("/beta-codes", response_model=list[BetaInviteRead])
def list_beta_codes(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    codes = db.query(BetaAccess).order_by(BetaAccess.created_at.desc()).all()
    return [_serialize_beta_invite(c) for c in codes]


@router.post("/beta-codes", response_model=BetaInviteCreateResponse)
def create_beta_code(
    payload: BetaInviteCreateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    invite_code = f"NEST-{secrets.token_urlsafe(9).upper()}"
    code_hash = hash_password(invite_code)
    beta = BetaAccess(
        code_hash=code_hash,
        created_by_id=admin.id,
        email_hint=payload.email_restriction,
        max_uses=payload.max_uses,
        expires_at=payload.expires_at,
    )
    db.add(beta)
    db.commit()
    db.refresh(beta)
    return BetaInviteCreateResponse(**_serialize_beta_invite(beta).model_dump(), invite_code=invite_code)


@router.post("/beta-codes/{invite_id}/deactivate", response_model=BetaInviteRead)
def deactivate_beta_code(
    invite_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    beta = db.query(BetaAccess).filter(BetaAccess.id == invite_id).first()
    if not beta:
        raise HTTPException(status_code=404, detail="Invite code not found")
    beta.is_active = False
    db.commit()
    db.refresh(beta)
    return _serialize_beta_invite(beta)


# ── AI cost tracking ───────────────────────────────────────────────────────────

@router.get("/ai-costs")
def ai_cost_summary(
    days: int = 30,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logs = db.query(AICallLog).filter(AICallLog.created_at >= cutoff).all()
    total_cost = sum(
        (log.estimated_cost_usd or 0.0) for log in logs if not log.was_cache_hit
    )
    total_tokens = sum((log.total_tokens or 0) for log in logs)
    cache_hits = sum(1 for log in logs if log.was_cache_hit)
    return {
        "period_days": days,
        "total_calls": len(logs),
        "cache_hits": cache_hits,
        "estimated_cost_usd": round(total_cost, 4),
        "total_tokens": total_tokens,
    }
