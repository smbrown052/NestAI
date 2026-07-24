"""
app/admin/router.py
FastAPI router for the /admin area.

All routes require a valid JWT from an authenticated administrator.
Use POST /auth/login to obtain a token, then pass it as:
    Authorization: ******

Sub-sections:
  /admin/           Dashboard overview
  /admin/users      User management
  /admin/beta       Beta tester management
  /admin/feedback   Feedback management
  /admin/billing    Billing overview
  /admin/analytics  Usage analytics
  /admin/ai-costs   AI API cost tracking
  /admin/audit-log  Administrator audit log
"""

from __future__ import annotations

import json
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin
from app.auth.router import _user_response
from app.db.models.ai_feedback import AICallLog
from app.db.models.audit_log import AuditLog
from app.db.models.beta_access import BetaAccess
from app.db.models.beta_invitation import BetaInvitation
from app.db.models.billing import BillingEvent
from app.db.models.credits import CreditBalance, CreditTransaction
from app.db.models.feedback import FeedbackReport
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Internal helpers ──────────────────────────────────────────────────────────

def _log_action(
    db: Session,
    admin: User,
    affected_user,
    action: str,
    previous_value=None,
    new_value=None,
    reason=None,
) -> None:
    entry = AuditLog(
        admin_id=admin.id,
        affected_user_id=affected_user.id if affected_user else None,
        action=action,
        previous_value=json.dumps(previous_value) if previous_value is not None else None,
        new_value=json.dumps(new_value) if new_value is not None else None,
        reason=reason,
    )
    db.add(entry)


def _send_invite_email(to: str, token: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("FEEDBACK_EMAIL", smtp_user or "noreply@example.com")
    app_url = os.environ.get("APP_URL", "http://localhost:8501")
    invite_url = f"{app_url}/accept-invite?token={token}"

    if not smtp_host:
        return

    msg = EmailMessage()
    msg["Subject"] = "You have been invited to NestAI Beta"
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(
        f"You have been invited to join NestAI as a beta tester.\n\n"
        f"Click the link below to create your account:\n{invite_url}\n\n"
        f"This invitation is time-limited. If you have questions, reply to this email."
    )
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            if smtp_user and smtp_pass:
                s.login(smtp_user, smtp_pass)
            s.send_message(msg)
    except Exception:
        pass


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── Request bodies ─────────────────────────────────────────────────────────────

class CreditsBody(BaseModel):
    credit_type: str = "building"
    amount: int
    reason: str | None = None


class ActionBody(BaseModel):
    reason: str | None = None


class BetaInviteBody(BaseModel):
    email: str
    display_name: str | None = None
    expires_at: str | None = None
    building_analyses: int = 10
    ai_credits: int = 0
    commute_credits: int = 0
    premium_features: bool = True


class FeedbackUpdateBody(BaseModel):
    status: str | None = None
    severity: str | None = None
    priority: str | None = None
    internal_notes: str | None = None
    duplicate_of_id: int | None = None


# ── Overview / Dashboard ───────────────────────────────────────────────────────

@router.get("/")
def admin_overview(
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    user_count = db.query(User).count()
    active_count = db.query(User).filter(User.is_active == True).count()  # noqa: E712
    beta_count = db.query(User).filter(User.beta_tester == True).count()  # noqa: E712
    premium_count = db.query(User).filter(User.tier == "premium").count()
    admin_count = db.query(User).filter(User.is_admin == True).count()  # noqa: E712
    open_feedback = db.query(FeedbackReport).filter(
        FeedbackReport.status.in_(["new", "triaged", "in_progress"])
    ).count()
    active_beta_codes = db.query(BetaAccess).filter(BetaAccess.is_active == True).count()  # noqa: E712
    recent_ai_calls = db.query(AICallLog).filter(
        AICallLog.created_at >= thirty_days_ago
    ).count()

    revenue_events = (
        db.query(BillingEvent)
        .filter(
            BillingEvent.event_type == "subscription_created",
            BillingEvent.created_at >= thirty_days_ago,
        )
        .all()
    )
    monthly_revenue_cents = sum(e.amount_cents or 0 for e in revenue_events)

    return {
        "users": {
            "total": user_count,
            "active": active_count,
            "beta_testers": beta_count,
            "premium": premium_count,
            "admins": admin_count,
        },
        "feedback": {"open": open_feedback},
        "beta_codes": {"active": active_beta_codes},
        "ai_calls_last_30d": recent_ai_calls,
        "monthly_revenue_usd": monthly_revenue_cents / 100,
    }


# ── Users ──────────────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(
    search: str = Query("", description="Search by name or email"),
    skip: int = 0,
    limit: int = 50,
    admin: Annotated[User, Depends(require_admin)] = ...,
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            User.email.ilike(pattern) | User.display_name.ilike(pattern)
        )
    users = q.order_by(User.created_at.desc()).offset(skip).limit(limit).all()

    balances = {
        b.user_id: b
        for b in db.query(CreditBalance).filter(
            CreditBalance.user_id.in_([u.id for u in users])
        ).all()
    }

    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "tier": u.tier,
            "role": u.role,
            "is_admin": u.is_admin,
            "beta_tester": u.beta_tester,
            "is_active": u.is_active,
            "last_login": u.last_login,
            "premium_expiration": u.premium_expiration,
            "created_at": u.created_at,
            "building_analyses_remaining": balances[u.id].credits_remaining if u.id in balances else 0,
            "ai_credits_remaining": balances[u.id].ai_credits_remaining if u.id in balances else 0,
            "commute_credits_remaining": balances[u.id].commute_credits_remaining if u.id in balances else 0,
        }
        for u in users
    ]


@router.get("/users/{user_id}")
def get_user(
    user_id: int,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    return _user_response(user, db)


@router.post("/users/{user_id}/grant-premium")
def grant_premium(
    user_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    prev = {"tier": user.tier}
    user.tier = "premium"
    user.premium_start = datetime.now(timezone.utc)
    balance = db.query(CreditBalance).filter(CreditBalance.user_id == user.id).first()
    if balance:
        balance.tier = "premium"
        balance.credits_remaining = max(balance.credits_remaining, 100)
    _log_action(db, admin, user, "grant_premium", prev, {"tier": "premium"}, body.reason)
    db.commit()
    return {"message": f"Premium granted to {user.email}"}


@router.post("/users/{user_id}/revoke-premium")
def revoke_premium(
    user_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    prev = {"tier": user.tier}
    user.tier = "free"
    user.premium_expiration = datetime.now(timezone.utc)
    balance = db.query(CreditBalance).filter(CreditBalance.user_id == user.id).first()
    if balance:
        balance.tier = "free"
    _log_action(db, admin, user, "revoke_premium", prev, {"tier": "free"}, body.reason)
    db.commit()
    return {"message": f"Premium revoked for {user.email}"}


@router.post("/users/{user_id}/grant-beta")
def grant_beta(
    user_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    prev = {"beta_tester": user.beta_tester, "tier": user.tier}
    user.beta_tester = True
    if user.tier == "free":
        user.tier = "beta"
    _log_action(db, admin, user, "grant_beta", prev, {"beta_tester": True, "tier": user.tier}, body.reason)
    db.commit()
    return {"message": f"Beta access granted to {user.email}"}


@router.post("/users/{user_id}/revoke-beta")
def revoke_beta(
    user_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    prev = {"beta_tester": user.beta_tester, "tier": user.tier}
    user.beta_tester = False
    if user.tier == "beta":
        user.tier = "free"
    _log_action(db, admin, user, "revoke_beta", prev, {"beta_tester": False, "tier": user.tier}, body.reason)
    db.commit()
    return {"message": f"Beta access revoked for {user.email}"}


@router.post("/users/{user_id}/extend-beta")
def extend_beta(
    user_id: int,
    body: ActionBody,
    new_expiration: str = Query(..., description="ISO date string for new expiration"),
    admin: Annotated[User, Depends(require_admin)] = ...,
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    prev = {"premium_expiration": str(user.premium_expiration)}
    try:
        exp = datetime.fromisoformat(new_expiration).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    user.premium_expiration = exp
    _log_action(db, admin, user, "extend_beta", prev, {"premium_expiration": str(exp)}, body.reason)
    db.commit()
    return {"message": f"Beta extended for {user.email} until {exp.date()}"}


@router.post("/users/{user_id}/convert-beta-premium")
def convert_beta_premium(
    user_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    prev = {"tier": user.tier}
    user.tier = "premium"
    user.beta_tester = False
    user.premium_start = datetime.now(timezone.utc)
    user.premium_expiration = None
    _log_action(db, admin, user, "convert_beta_to_premium", prev, {"tier": "premium"}, body.reason)
    db.commit()
    return {"message": f"{user.email} converted from beta to premium"}


@router.post("/users/{user_id}/convert-beta-free")
def convert_beta_free(
    user_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    prev = {"tier": user.tier, "beta_tester": user.beta_tester}
    user.tier = "free"
    user.beta_tester = False
    user.premium_expiration = datetime.now(timezone.utc)
    _log_action(db, admin, user, "convert_beta_to_free", prev, {"tier": "free"}, body.reason)
    db.commit()
    return {"message": f"{user.email} converted from beta to free"}


@router.post("/users/{user_id}/suspend")
def suspend_user(
    user_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot suspend your own account")
    prev = {"is_active": user.is_active}
    user.is_active = False
    _log_action(db, admin, user, "suspend", prev, {"is_active": False}, body.reason)
    db.commit()
    return {"message": f"Account {user.email} suspended"}


@router.post("/users/{user_id}/reactivate")
def reactivate_user(
    user_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    prev = {"is_active": user.is_active}
    user.is_active = True
    _log_action(db, admin, user, "reactivate", prev, {"is_active": True}, body.reason)
    db.commit()
    return {"message": f"Account {user.email} reactivated"}


@router.post("/users/{user_id}/promote-admin")
def promote_admin(
    user_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    prev = {"is_admin": user.is_admin, "role": user.role}
    user.is_admin = True
    user.role = "admin"
    _log_action(db, admin, user, "promote_admin", prev, {"is_admin": True, "role": "admin"}, body.reason)
    db.commit()
    return {"message": f"{user.email} promoted to admin"}


@router.post("/users/{user_id}/demote-admin")
def demote_admin(
    user_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot demote yourself")
    user = _get_user_or_404(db, user_id)
    prev = {"is_admin": user.is_admin, "role": user.role}
    user.is_admin = False
    user.role = "user"
    _log_action(db, admin, user, "demote_admin", prev, {"is_admin": False, "role": "user"}, body.reason)
    db.commit()
    return {"message": f"{user.email} demoted from admin"}


@router.post("/users/{user_id}/add-credits")
def add_credits(
    user_id: int,
    body: CreditsBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    balance = db.query(CreditBalance).filter(CreditBalance.user_id == user.id).first()
    if not balance:
        raise HTTPException(status_code=404, detail="Credit balance not found")

    ct = body.credit_type
    if ct == "building":
        prev = {"credits_remaining": balance.credits_remaining}
        balance.credits_remaining += body.amount
        new = {"credits_remaining": balance.credits_remaining}
    elif ct == "ai":
        prev = {"ai_credits_remaining": balance.ai_credits_remaining}
        balance.ai_credits_remaining += body.amount
        new = {"ai_credits_remaining": balance.ai_credits_remaining}
    elif ct == "commute":
        prev = {"commute_credits_remaining": balance.commute_credits_remaining}
        balance.commute_credits_remaining += body.amount
        new = {"commute_credits_remaining": balance.commute_credits_remaining}
    else:
        raise HTTPException(status_code=400, detail="Invalid credit_type. Use: building, ai, commute")

    db.add(CreditTransaction(
        user_id=user.id,
        transaction_type="grant",
        credit_type=ct,
        delta=body.amount,
        balance_after=list(new.values())[0],
        reason=body.reason or f"Admin grant by {admin.email}",
    ))
    _log_action(db, admin, user, "add_credits", prev, new, body.reason)
    db.commit()
    return {"message": f"Added {body.amount} {ct} credits to {user.email}"}


@router.post("/users/{user_id}/remove-credits")
def remove_credits(
    user_id: int,
    body: CreditsBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    balance = db.query(CreditBalance).filter(CreditBalance.user_id == user.id).first()
    if not balance:
        raise HTTPException(status_code=404, detail="Credit balance not found")

    ct = body.credit_type
    if ct == "building":
        prev = {"credits_remaining": balance.credits_remaining}
        balance.credits_remaining = max(0, balance.credits_remaining - body.amount)
        new = {"credits_remaining": balance.credits_remaining}
    elif ct == "ai":
        prev = {"ai_credits_remaining": balance.ai_credits_remaining}
        balance.ai_credits_remaining = max(0, balance.ai_credits_remaining - body.amount)
        new = {"ai_credits_remaining": balance.ai_credits_remaining}
    elif ct == "commute":
        prev = {"commute_credits_remaining": balance.commute_credits_remaining}
        balance.commute_credits_remaining = max(0, balance.commute_credits_remaining - body.amount)
        new = {"commute_credits_remaining": balance.commute_credits_remaining}
    else:
        raise HTTPException(status_code=400, detail="Invalid credit_type")

    db.add(CreditTransaction(
        user_id=user.id,
        transaction_type="grant",
        credit_type=ct,
        delta=-body.amount,
        balance_after=list(new.values())[0],
        reason=body.reason or f"Admin removal by {admin.email}",
    ))
    _log_action(db, admin, user, "remove_credits", prev, new, body.reason)
    db.commit()
    return {"message": f"Removed {body.amount} {ct} credits from {user.email}"}


# Legacy endpoint kept for backward compatibility
@router.post("/users/{user_id}/promote-beta")
def promote_to_beta(
    user_id: int,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    user.beta_tester = True
    db.commit()
    return {"message": f"User {user.email} promoted to beta tester"}


# ── Beta Management ────────────────────────────────────────────────────────────

@router.get("/beta/users")
def list_beta_users(
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    users = db.query(User).filter(User.beta_tester == True).all()  # noqa: E712
    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "tier": u.tier,
            "beta_tester": u.beta_tester,
            "premium_expiration": u.premium_expiration,
            "created_at": u.created_at,
            "last_login": u.last_login,
        }
        for u in users
    ]


@router.get("/beta/invitations")
def list_beta_invitations(
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    invitations = (
        db.query(BetaInvitation)
        .order_by(BetaInvitation.created_at.desc())
        .all()
    )
    return [
        {
            "id": inv.id,
            "email": inv.email,
            "display_name": inv.display_name,
            "status": inv.status,
            "beta_expiration": inv.beta_expiration,
            "building_analyses": inv.building_analyses,
            "ai_credits": inv.ai_credits,
            "commute_credits": inv.commute_credits,
            "premium_features": inv.premium_features,
            "accepted_at": inv.accepted_at,
            "created_at": inv.created_at,
        }
        for inv in invitations
    ]


@router.post("/beta/invite")
def invite_beta_tester(
    body: BetaInviteBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    existing_inv = db.query(BetaInvitation).filter(
        BetaInvitation.email == body.email,
        BetaInvitation.status == "pending",
    ).first()
    if existing_inv:
        raise HTTPException(status_code=400, detail="A pending invitation already exists for this email")

    beta_exp = None
    if body.expires_at:
        try:
            beta_exp = datetime.fromisoformat(body.expires_at).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expires_at format. Use ISO date (YYYY-MM-DD).")

    token = secrets.token_urlsafe(48)
    inv = BetaInvitation(
        invited_by_id=admin.id,
        email=body.email,
        display_name=body.display_name,
        token=token,
        building_analyses=body.building_analyses,
        ai_credits=body.ai_credits,
        commute_credits=body.commute_credits,
        premium_features=body.premium_features,
        beta_expiration=beta_exp,
        status="pending",
    )
    db.add(inv)

    smtp_configured = bool(os.environ.get("SMTP_HOST", ""))
    _send_invite_email(body.email, token)
    _log_action(db, admin, None, "invite_beta", None, {"email": body.email})
    db.commit()

    resp: dict = {"message": f"Invitation created for {body.email}.", "token": token}
    if not smtp_configured:
        resp["warning"] = "SMTP not configured; invitation email was not sent."
    return resp


@router.post("/beta/invitations/{invitation_id}/revoke")
def revoke_invitation(
    invitation_id: int,
    body: ActionBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    inv = db.query(BetaInvitation).filter(BetaInvitation.id == invitation_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    inv.status = "revoked"
    _log_action(db, admin, None, "revoke_invitation", {"status": "pending"}, {"status": "revoked"}, body.reason)
    db.commit()
    return {"message": f"Invitation {invitation_id} revoked"}


# ── Legacy beta codes ──────────────────────────────────────────────────────────

@router.get("/beta-codes")
def list_beta_codes(
    admin: Annotated[User, Depends(require_admin)],
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
    admin: Annotated[User, Depends(require_admin)] = ...,
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


# ── Feedback ───────────────────────────────────────────────────────────────────

@router.get("/feedback")
def list_feedback(
    status: str | None = None,
    category: str | None = None,
    skip: int = 0,
    limit: int = 50,
    admin: Annotated[User, Depends(require_admin)] = ...,
    db: Session = Depends(get_db),
):
    q = db.query(FeedbackReport)
    if status:
        q = q.filter(FeedbackReport.status == status)
    if category:
        q = q.filter(FeedbackReport.category == category)
    reports = q.order_by(FeedbackReport.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": r.id,
            "public_reference": r.public_reference,
            "category": r.category,
            "title": r.title,
            "status": r.status,
            "severity": r.severity,
            "priority": r.priority,
            "user_plan": r.user_plan,
            "internal_notes": r.internal_notes,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in reports
    ]


@router.get("/feedback/{feedback_id}")
def get_feedback(
    feedback_id: int,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    r = db.query(FeedbackReport).filter(FeedbackReport.id == feedback_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Feedback report not found")
    return {
        "id": r.id,
        "public_reference": r.public_reference,
        "category": r.category,
        "title": r.title,
        "description": r.description,
        "actual_behavior": r.actual_behavior,
        "expected_behavior": r.expected_behavior,
        "requested_feature": r.requested_feature,
        "problem_to_solve": r.problem_to_solve,
        "status": r.status,
        "severity": r.severity,
        "priority": r.priority,
        "user_plan": r.user_plan,
        "beta_tester": r.beta_tester,
        "internal_notes": r.internal_notes,
        "contact_email": r.contact_email,
        "attachment_url": r.attachment_url,
        "duplicate_of_id": r.duplicate_of_id,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
        "resolved_at": r.resolved_at,
    }


@router.patch("/feedback/{feedback_id}")
def update_feedback(
    feedback_id: int,
    body: FeedbackUpdateBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    r = db.query(FeedbackReport).filter(FeedbackReport.id == feedback_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Feedback report not found")

    if body.status is not None:
        r.status = body.status
        if body.status == "resolved":
            r.resolved_at = datetime.now(timezone.utc)
    if body.severity is not None:
        r.severity = body.severity
    if body.priority is not None:
        r.priority = body.priority
    if body.internal_notes is not None:
        r.internal_notes = body.internal_notes
    if body.duplicate_of_id is not None:
        r.duplicate_of_id = body.duplicate_of_id

    db.commit()
    return {"message": "Feedback updated"}


# ── Billing ────────────────────────────────────────────────────────────────────

@router.get("/billing/overview")
def billing_overview(
    admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    events = db.query(BillingEvent).order_by(BillingEvent.created_at.desc()).limit(100).all()
    total_revenue_cents = sum(
        e.amount_cents or 0
        for e in events
        if e.event_type in ("subscription_created", "credit_pack_purchased")
    )
    total_refunds_cents = sum(
        e.amount_cents or 0 for e in events if e.event_type == "refund"
    )
    return {
        "total_events": len(events),
        "total_revenue_usd": total_revenue_cents / 100,
        "total_refunds_usd": total_refunds_cents / 100,
        "recent_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "provider": e.provider,
                "amount_cents": e.amount_cents,
                "tier_after": e.tier_after,
                "created_at": e.created_at,
            }
            for e in events[:20]
        ],
    }


# ── Analytics ──────────────────────────────────────────────────────────────────

@router.get("/analytics/overview")
def analytics_overview(
    days: int = 30,
    admin: Annotated[User, Depends(require_admin)] = ...,
    db: Session = Depends(get_db),
):
    from sqlalchemy import func, cast, Date

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    new_users = db.query(User).filter(User.created_at >= cutoff).count()
    active_users = db.query(User).filter(
        User.last_login.isnot(None),
        User.last_login >= cutoff,
    ).count()
    premium_conversions = db.query(User).filter(
        User.premium_start.isnot(None),
        User.premium_start >= cutoff,
    ).count()
    beta_conversions = db.query(User).filter(
        User.beta_tester == True,  # noqa: E712
        User.created_at >= cutoff,
    ).count()

    daily = (
        db.query(
            cast(User.created_at, Date).label("date"),
            func.count(User.id).label("count"),
        )
        .filter(User.created_at >= cutoff)
        .group_by(cast(User.created_at, Date))
        .order_by(cast(User.created_at, Date))
        .all()
    )

    return {
        "period_days": days,
        "new_users": new_users,
        "active_users": active_users,
        "premium_conversions": premium_conversions,
        "beta_conversions": beta_conversions,
        "daily_signups": [{"date": str(row.date), "count": row.count} for row in daily],
    }


# ── AI cost tracking ───────────────────────────────────────────────────────────

@router.get("/ai-costs")
def ai_cost_summary(
    days: int = 30,
    admin: Annotated[User, Depends(require_admin)] = ...,
    db: Session = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logs = db.query(AICallLog).filter(AICallLog.created_at >= cutoff).all()
    total_cost = sum((log.estimated_cost_usd or 0.0) for log in logs if not log.was_cache_hit)
    total_tokens = sum((log.total_tokens or 0) for log in logs)
    cache_hits = sum(1 for log in logs if log.was_cache_hit)
    return {
        "period_days": days,
        "total_calls": len(logs),
        "cache_hits": cache_hits,
        "estimated_cost_usd": round(total_cost, 4),
        "total_tokens": total_tokens,
    }


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit-log")
def get_audit_log(
    skip: int = 0,
    limit: int = 50,
    admin: Annotated[User, Depends(require_admin)] = ...,
    db: Session = Depends(get_db),
):
    entries = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "admin_id": e.admin_id,
            "affected_user_id": e.affected_user_id,
            "action": e.action,
            "previous_value": e.previous_value,
            "new_value": e.new_value,
            "reason": e.reason,
            "created_at": e.created_at,
        }
        for e in entries
    ]
