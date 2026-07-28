"""FastAPI auth routes for NestAI users."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.plans import (
    BETA_PLAN,
    FREE_PLAN,
    PAYMENT_PLANS,
    current_plan,
    is_valid_plan,
    normalize_plan,
    plan_requires_payment,
    requested_plan,
    set_user_plan,
)
from app.billing.service import create_checkout_session, payment_required_message
from app.auth.security import create_access_token, hash_password, verify_password
from app.db.models.user import User
from app.db.models.beta_access import BetaAccess
from app.db.session import get_db

from .dependencies import get_current_user
from .schemas import AccessTokenResponse, AuthUserRead, LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])

_PREMIUM_TRIAL_DAYS = 7


def _owner_email() -> str | None:
    """Return the configured owner email, normalised to lowercase."""
    raw = os.getenv("NESTAI_OWNER_EMAIL", "").strip()
    return raw.lower() or None


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _serialize_user(user: User) -> AuthUserRead:
    selected_account_type = requested_plan(user) or current_plan(user)
    return AuthUserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tier=current_plan(user),
        active_plan=current_plan(user),
        requested_plan=requested_plan(user),
        selected_account_type=selected_account_type,
        subscription_status=user.subscription_status,
        payment_customer_id=user.payment_customer_id,
        payment_subscription_id=user.payment_subscription_id,
        beta_approved_at=user.beta_approved_at,
        beta_access=bool(user.beta_tester),
        is_admin=user.is_admin,
        is_active=user.is_active,
        premium_trial_started_at=user.premium_trial_started_at,
        premium_trial_ends_at=user.premium_trial_ends_at,
        premium_trial_used=bool(user.premium_trial_used),
    )


def _find_valid_beta_access(db: Session, invite_code: str, email: str) -> BetaAccess | None:
    beta_codes = db.query(BetaAccess).filter(BetaAccess.is_active == True).all()  # noqa: E712
    now = datetime.now(timezone.utc)
    for beta_access in beta_codes:
        if not verify_password(invite_code, beta_access.code_hash):
            continue
        if beta_access.expires_at and beta_access.expires_at < now:
            continue
        if beta_access.use_count >= beta_access.max_uses:
            continue
        if beta_access.email_hint and beta_access.email_hint.lower() != email.lower():
            continue
        return beta_access
    return None


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)):
    normalized_email = _normalize_email(str(payload.email))
    account_type = normalize_plan(payload.account_type)
    if not is_valid_plan(account_type):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid account type")

    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    owner_email = _owner_email()
    is_owner = bool(owner_email and normalized_email == owner_email)

    display_name = None
    if payload.display_name:
        stripped = payload.display_name.strip()
        display_name = stripped or None

    user = User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        display_name=display_name,
        is_active=True,
        is_admin=is_owner,
        tier=FREE_PLAN,
        active_plan=FREE_PLAN,
        requested_plan=None,
        subscription_status="active",
        beta_tester=False,
        premium_trial_used=False,
    )

    checkout_session_info = None
    if account_type == FREE_PLAN:
        set_user_plan(user, FREE_PLAN, requested=None, subscription_status="active")
    elif account_type == BETA_PLAN:
        if not payload.beta_invite_code:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Beta invite code required")
        beta_access = _find_valid_beta_access(db, payload.beta_invite_code, normalized_email)
        if not beta_access:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid beta invite code")
        beta_access.use_count += 1
        beta_access.redeemed_at = datetime.now(timezone.utc)
        user.beta_tester = True
        user.beta_approved_at = datetime.now(timezone.utc)
        set_user_plan(user, BETA_PLAN, requested=None, subscription_status="active")
    else:
        if not plan_requires_payment(account_type):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid account type")
        set_user_plan(user, FREE_PLAN, requested=account_type, subscription_status="pending_payment")

    db.add(user)
    db.flush()

    if account_type == BETA_PLAN:
        beta_access.redeemed_by_id = user.id

    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "email": user.email})
    response = {
        "user": _serialize_user(user).model_dump(mode="json"),
        "access_token": token,
        "token_type": "bearer",
    }

    if account_type in PAYMENT_PLANS:
        checkout_session_info = create_checkout_session(db, user, account_type)
        db.refresh(user)
        response.update(
            {
                "user": _serialize_user(user).model_dump(mode="json"),
                **checkout_session_info,
                "payment_required_message": payment_required_message(account_type),
            }
        )

    return response


@router.post("/login", response_model=AccessTokenResponse)
def login_user(payload: LoginRequest, db: Session = Depends(get_db)) -> AccessTokenResponse:
    normalized_email = _normalize_email(str(payload.email))
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    token = create_access_token({"sub": str(user.id), "email": user.email})
    return AccessTokenResponse(access_token=token)


@router.get("/me", response_model=AuthUserRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> AuthUserRead:
    return _serialize_user(current_user)


@router.post("/trial/start", response_model=AuthUserRead)
def start_premium_trial(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthUserRead:
    """Start a one-time 7-day Premium trial.

    Rules:
    - One trial per user account; cannot be restarted.
    - Does not grant Premium Plus.
    - After expiry the user's actual paid plan (or Free) takes effect.
    - If the user already has a paid Premium/Premium Plus plan the trial
      is unnecessary but can still be recorded (no-op if already on paid plan).
    """
    if current_user.premium_trial_used:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Premium trial has already been used",
        )

    now = datetime.now(timezone.utc)
    current_user.premium_trial_started_at = now
    current_user.premium_trial_ends_at = now + timedelta(days=_PREMIUM_TRIAL_DAYS)
    current_user.premium_trial_used = True
    db.commit()
    db.refresh(current_user)
    return _serialize_user(current_user)
