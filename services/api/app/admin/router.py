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

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.feedback import FeedbackReport
from app.db.models.beta_access import BetaAccess
from app.db.models.credits import CreditBalance, CreditTransaction
from app.db.models.billing import BillingEvent
from app.db.models.ai_feedback import AICallLog

router = APIRouter(prefix="/admin", tags=["admin"])

security = HTTPBasic()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Auth dependency ────────────────────────────────────────────────────────────

def require_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
    db: Session = Depends(get_db),
) -> User:
    user = db.query(User).filter(User.email == credentials.username).first()
    if not user or not pwd_ctx.verify(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
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

@router.get("/beta-codes")
def list_beta_codes(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    codes = db.query(BetaAccess).order_by(BetaAccess.created_at.desc()).all()
    return [
        {
            "id": c.id,
            "code": c.code,
            "email_hint": c.email_hint,
            "is_active": c.is_active,
            "use_count": c.use_count,
            "max_uses": c.max_uses,
            "redeemed_at": c.redeemed_at,
            "expires_at": c.expires_at,
        }
        for c in codes
    ]


@router.post("/beta-codes")
def create_beta_code(
    code: str,
    email_hint: str | None = None,
    max_uses: int = 1,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(BetaAccess).filter(BetaAccess.code == code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Code already exists")
    beta = BetaAccess(
        code=code,
        created_by_id=admin.id,
        email_hint=email_hint,
        max_uses=max_uses,
    )
    db.add(beta)
    db.commit()
    return {"message": f"Beta code {code!r} created"}


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
