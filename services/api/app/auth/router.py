"""
app/auth/router.py — Authentication endpoints.

Routes:
    POST /auth/register             Create a new account
    POST /auth/login                Authenticate and receive a JWT
    GET  /auth/me                   Return current user's profile
    POST /auth/password-reset-request   Send a password-reset email
    POST /auth/password-reset           Reset password using the emailed token
    GET  /auth/accept-invite/{token}    Validate a beta invitation
    POST /auth/accept-invite            Complete registration from an invitation
"""

from __future__ import annotations

import os
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.schemas import (
    AcceptInviteRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    CreditSummary,
)
from app.db.models.beta_invitation import BetaInvitation
from app.db.models.credits import CreditBalance
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me-in-production")
_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_HOURS = int(os.environ.get("ACCESS_TOKEN_EXPIRE_HOURS", "168"))  # 7 days


# ── Internal helpers ──────────────────────────────────────────────────────────

def _make_token(subject: str | int, token_type: str = "access", hours: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=hours or _ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(subject), "type": token_type, "exp": expire}
    return jwt.encode(payload, _SECRET_KEY, algorithm=_ALGORITHM)


def _decode_token(token: str, expected_type: str = "access") -> str | None:
    """Return subject string, or None on failure."""
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        return payload.get("sub")
    except jwt.InvalidTokenError:
        return None


def _send_email(to: str, subject: str, body: str) -> None:
    """Attempt to send a plain-text email.  Silently swallows failures in dev."""
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("FEEDBACK_EMAIL", smtp_user or "noreply@example.com")

    if not smtp_host:
        return  # email not configured; silently skip

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            if smtp_user and smtp_pass:
                s.login(smtp_user, smtp_pass)
            s.send_message(msg)
    except Exception:
        pass  # never crash the request because of an email failure


def _credit_summary(db: Session, user_id: int) -> CreditSummary | None:
    bal = db.query(CreditBalance).filter(CreditBalance.user_id == user_id).first()
    if not bal:
        return None
    return CreditSummary(
        building_credits_remaining=bal.credits_remaining,
        building_credits_used=bal.credits_used,
        ai_credits_remaining=bal.ai_credits_remaining,
        ai_credits_used=bal.ai_credits_used,
        commute_credits_remaining=bal.commute_credits_remaining,
        commute_credits_used=bal.commute_credits_used,
    )


def _user_response(user: User, db: Session) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_admin=user.is_admin,
        role=user.role,
        tier=user.tier,
        beta_tester=user.beta_tester,
        last_login=user.last_login,
        premium_start=user.premium_start,
        premium_expiration=user.premium_expiration,
        created_at=user.created_at,
        credits=_credit_summary(db, user.id),
    )


def _create_user_with_balance(
    db: Session,
    email: str,
    hashed_password: str,
    display_name: str | None = None,
    tier: str = "free",
    is_admin: bool = False,
) -> User:
    """Create a User row and its initial CreditBalance row."""
    user = User(
        email=email,
        hashed_password=hashed_password,
        display_name=display_name,
        tier=tier,
        is_admin=is_admin,
        role="admin" if is_admin else "user",
    )
    db.add(user)
    db.flush()  # populate user.id

    credits = 100 if tier == "premium" else 5
    balance = CreditBalance(
        user_id=user.id,
        tier=tier,
        credits_remaining=credits,
    )
    db.add(balance)
    return user


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account."""
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = _pwd_ctx.hash(payload.password)
    user = _create_user_with_balance(
        db,
        email=payload.email,
        hashed_password=hashed,
        display_name=payload.display_name,
    )
    db.commit()
    db.refresh(user)

    token = _make_token(user.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate with email + password and receive a JWT."""
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not _pwd_ctx.verify(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account suspended")

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    token = _make_token(user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return the authenticated user's profile and credit summary."""
    return _user_response(current_user, db)


@router.post("/password-reset-request")
def password_reset_request(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """
    Request a password-reset token.

    If SMTP is configured, a reset link is emailed.
    If not configured, the raw token is returned in the response (developer mode).
    """
    user = db.query(User).filter(User.email == payload.email).first()
    # Always return 200 to prevent user enumeration.
    if not user:
        return {"message": "If an account with that email exists, a reset link has been sent."}

    reset_token = _make_token(user.id, token_type="password_reset", hours=2)

    smtp_host = os.environ.get("SMTP_HOST", "")
    app_url = os.environ.get("APP_URL", "http://localhost:8000")
    reset_url = f"{app_url}/auth/reset?token={reset_token}"
    _send_email(
        to=user.email,
        subject="NestAI Password Reset",
        body=(
            f"You requested a password reset for your NestAI account.\n\n"
            f"Reset link: {reset_url}\n\n"
            f"This link expires in 2 hours. If you did not request a reset, ignore this email."
        ),
    )

    # In dev (no SMTP), return the token directly so the owner can test.
    if not smtp_host:
        return {"message": "Reset token generated (email not configured).", "token": reset_token}
    return {"message": "If an account with that email exists, a reset link has been sent."}


@router.post("/password-reset")
def password_reset(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    """Reset a password using the token received by email."""
    subject = _decode_token(payload.token, expected_type="password_reset")
    if not subject:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = db.query(User).filter(User.id == int(subject)).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid token")

    user.hashed_password = _pwd_ctx.hash(payload.new_password)
    db.commit()
    return {"message": "Password reset successfully. You can now log in with your new password."}


@router.get("/accept-invite/{token}")
def get_invitation(token: str, db: Session = Depends(get_db)):
    """Validate a beta invitation token and return its details."""
    inv = db.query(BetaInvitation).filter(
        BetaInvitation.token == token,
        BetaInvitation.status == "pending",
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")
    now = datetime.now(timezone.utc)
    if inv.beta_expiration and inv.beta_expiration < now:
        inv.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="Invitation has expired")
    return {
        "email": inv.email,
        "display_name": inv.display_name,
        "building_analyses": inv.building_analyses,
        "ai_credits": inv.ai_credits,
        "commute_credits": inv.commute_credits,
        "premium_features": inv.premium_features,
        "beta_expiration": inv.beta_expiration,
    }


@router.post("/accept-invite", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def accept_invite(payload: AcceptInviteRequest, db: Session = Depends(get_db)):
    """Complete beta tester registration from an invitation link."""
    inv = db.query(BetaInvitation).filter(
        BetaInvitation.token == payload.token,
        BetaInvitation.status == "pending",
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")

    now = datetime.now(timezone.utc)
    if inv.beta_expiration and inv.beta_expiration < now:
        inv.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="Invitation has expired")

    existing = db.query(User).filter(User.email == inv.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    tier = "premium" if inv.premium_features else "beta"
    hashed = _pwd_ctx.hash(payload.password)
    user = _create_user_with_balance(
        db,
        email=inv.email,
        hashed_password=hashed,
        display_name=payload.display_name or inv.display_name,
        tier=tier,
    )
    user.beta_tester = True
    user.premium_start = now if inv.premium_features else None
    user.premium_expiration = inv.beta_expiration

    # Update credit balance with invitation-specified amounts.
    balance = db.query(CreditBalance).filter(CreditBalance.user_id == user.id).first()
    if balance:
        balance.credits_remaining = inv.building_analyses
        balance.ai_credits_remaining = inv.ai_credits
        balance.commute_credits_remaining = inv.commute_credits

    inv.status = "accepted"
    inv.accepted_at = now
    inv.accepted_by_id = user.id

    db.commit()
    db.refresh(user)

    token = _make_token(user.id)
    return TokenResponse(access_token=token)
