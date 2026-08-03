"""FastAPI auth routes for NestAI users."""

from __future__ import annotations

from datetime import datetime, timezone
import secrets

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
from app.db.models.referral import Referral
from app.db.models.user import User
from app.db.models.beta_access import BetaAccess
from app.db.session import get_db

from .dependencies import get_current_user
from .schemas import (
    AccessTokenResponse,
    AuthUserRead,
    LoginRequest,
    ReferralInviteRequest,
    ReferralRead,
    ReferralSummaryRead,
    RegisterRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


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
        referrer_id=user.referrer_id,
        referral_code=user.referral_code,
        referral_credit_cents=user.referral_credit_cents or 0,
        is_admin=user.is_admin,
        is_active=user.is_active,
    )


def _generate_unique_referral_code(db: Session) -> str:
    while True:
        code = f"nest-{secrets.token_urlsafe(6).replace('-', '').replace('_', '').lower()[:10]}"
        existing = db.query(User).filter(User.referral_code == code).first()
        if not existing:
            return code


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
    account_type = normalize_plan(payload.account_type)
    if not is_valid_plan(account_type):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid account type")

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    referrer_id = None
    normalized_email = payload.email.strip().lower()
    if payload.referral_code:
        referrer = db.query(User).filter(User.referral_code == payload.referral_code.strip()).first()
        if referrer and referrer.email.lower() != normalized_email:
            referrer_id = referrer.id

    if referrer_id is None:
        invite = (
            db.query(Referral)
            .filter(Referral.referred_email == normalized_email)
            .filter(Referral.status == "invited")
            .order_by(Referral.created_at.desc())
            .first()
        )
        if invite and invite.referrer_user_id:
            referrer_id = invite.referrer_user_id

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        display_name=payload.display_name.strip() or None,
        is_active=True,
        is_admin=False,
        tier=FREE_PLAN,
        active_plan=FREE_PLAN,
        requested_plan=None,
        subscription_status="active",
        beta_tester=False,
        referrer_id=referrer_id,
        referral_code=_generate_unique_referral_code(db),
        referral_credit_cents=0,
    )

    checkout_session_info = None
    if account_type == FREE_PLAN:
        set_user_plan(user, FREE_PLAN, requested=None, subscription_status="active")
    elif account_type == BETA_PLAN:
        if not payload.beta_invite_code:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Beta invite code required")
        beta_access = _find_valid_beta_access(db, payload.beta_invite_code, payload.email)
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
        if not payload.trial_consent or not payload.payment_method_confirmed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Premium trial requires explicit consent and payment method confirmation",
            )
        set_user_plan(user, FREE_PLAN, requested=account_type, subscription_status="pending_payment")

    db.add(user)
    db.flush()

    if user.referrer_id:
        referral_code_value = payload.referral_code.strip() if payload.referral_code else None
        invite_referral = (
            db.query(Referral)
            .filter(Referral.referrer_user_id == user.referrer_id)
            .filter(Referral.referred_email == normalized_email)
            .order_by(Referral.created_at.desc())
            .first()
        )
        if invite_referral:
            invite_referral.referred_user_id = user.id
            invite_referral.referral_code = invite_referral.referral_code or referral_code_value
        else:
            db.add(
                Referral(
                    referrer_user_id=user.referrer_id,
                    referred_user_id=user.id,
                    referred_email=normalized_email,
                    referral_code=referral_code_value,
                    status="registered",
                )
            )

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
        try:
            checkout_session_info = create_checkout_session(
                db,
                user,
                account_type,
                trial_consent=payload.trial_consent,
                payment_method_confirmed=payload.payment_method_confirmed,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
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
    user = db.query(User).filter(User.email == payload.email).first()
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


@router.get("/referrals/summary", response_model=ReferralSummaryRead)
def referral_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ReferralSummaryRead:
    referral_rows = (
        db.query(Referral)
        .filter(Referral.referrer_user_id == current_user.id)
        .order_by(Referral.created_at.desc())
        .all()
    )
    referral_code = current_user.referral_code or _generate_unique_referral_code(db)
    if not current_user.referral_code:
        current_user.referral_code = referral_code
        db.commit()
        db.refresh(current_user)
    return ReferralSummaryRead(
        referral_code=referral_code,
        referral_link=f"https://nestai.app/signup?ref={referral_code}",
        earned_credit_cents=current_user.referral_credit_cents or 0,
        referrals=[
            ReferralRead(
                id=row.id,
                referred_email=row.referred_email,
                status=row.status,
                reward_cents=row.reward_cents,
                created_at=row.created_at,
                converted_at=row.converted_at,
                rewarded_at=row.rewarded_at,
            )
            for row in referral_rows
        ],
    )


@router.post("/referrals/invite", response_model=ReferralRead)
def send_referral_invite(
    payload: ReferralInviteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReferralRead:
    target_email = payload.email.strip().lower()
    if target_email == current_user.email.lower():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot refer yourself")

    referral_code = current_user.referral_code or _generate_unique_referral_code(db)
    if not current_user.referral_code:
        current_user.referral_code = referral_code
        db.flush()

    existing = (
        db.query(Referral)
        .filter(Referral.referrer_user_id == current_user.id)
        .filter(Referral.referred_email == target_email)
        .order_by(Referral.created_at.desc())
        .first()
    )
    if existing:
        return ReferralRead(
            id=existing.id,
            referred_email=existing.referred_email,
            status=existing.status,
            reward_cents=existing.reward_cents,
            created_at=existing.created_at,
            converted_at=existing.converted_at,
            rewarded_at=existing.rewarded_at,
        )

    referral = Referral(
        referrer_user_id=current_user.id,
        referred_email=target_email,
        referral_code=referral_code,
        status="invited",
    )
    db.add(referral)
    db.commit()
    db.refresh(referral)
    return ReferralRead(
        id=referral.id,
        referred_email=referral.referred_email,
        status=referral.status,
        reward_cents=referral.reward_cents,
        created_at=referral.created_at,
        converted_at=referral.converted_at,
        rewarded_at=referral.rewarded_at,
    )