"""Billing helpers for checkout and webhook processing."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.auth.plans import FREE_PLAN, PAYMENT_PLANS, current_plan, normalize_plan, set_user_plan
from app.db.models.billing import BillingEvent
from app.db.models.referral import Referral
from app.db.models.user import User

STREAMLIT_BASE_URL_ENV = "NESTAI_STREAMLIT_URL"
BILLING_WEBHOOK_SECRET_ENV = "BILLING_WEBHOOK_SECRET"


def billing_webhook_secret() -> str:
    return (
        os.getenv(BILLING_WEBHOOK_SECRET_ENV)
        or os.getenv("JWT_SECRET_KEY")
        or os.getenv("SECRET_KEY")
        or ""
    )


def streamlit_base_url() -> str:
    return os.getenv(STREAMLIT_BASE_URL_ENV, "http://localhost:8501").rstrip("/")


def sign_webhook_payload(raw_payload: bytes) -> str:
    secret = billing_webhook_secret()
    if not secret:
        raise RuntimeError("BILLING_WEBHOOK_SECRET or JWT_SECRET_KEY must be set")
    return hmac.new(secret.encode("utf-8"), raw_payload, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_payload: bytes, signature: str) -> bool:
    expected = sign_webhook_payload(raw_payload)
    return hmac.compare_digest(expected, signature)


def payment_required_message(plan: str) -> str:
    normalized = normalize_plan(plan)
    if normalized == "premium_plus":
        return "Payment required to activate Premium Plus"
    return "Payment required to activate Premium"


def _trial_days_for_plan(plan: str) -> int:
    _ = plan
    return 7


def create_checkout_session(
    db: Session,
    user: User,
    requested_plan: str,
    *,
    trial_consent: bool = False,
    payment_method_confirmed: bool = False,
) -> dict:
    plan = normalize_plan(requested_plan)
    if plan not in PAYMENT_PLANS:
        raise ValueError("Requested plan does not require payment")
    if not trial_consent or not payment_method_confirmed:
        raise ValueError("Checkout requires explicit trial consent and payment method confirmation")

    session_id = f"cs_{secrets.token_urlsafe(18)}"
    trial_days = _trial_days_for_plan(plan)
    trial_end = datetime.now(timezone.utc) + timedelta(days=trial_days)
    monthly_price = "$49/mo" if plan == "premium_plus" else "$19/mo"
    payload = {
        "checkout_session_id": session_id,
        "requested_plan": plan,
        "user_id": user.id,
        "trial_consent": True,
        "payment_method_confirmed": True,
        "trial_days": trial_days,
        "trial_end_date": trial_end.date().isoformat(),
        "monthly_price": monthly_price,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    event = BillingEvent(
        user_id=user.id,
        event_type="checkout_session_created",
        provider="mock",
        provider_event_id=session_id,
        tier_before=current_plan(user),
        tier_after=FREE_PLAN,
        raw_payload=json.dumps(payload),
    )
    db.add(event)
    user.requested_plan = plan
    user.subscription_status = "pending_payment"
    set_user_plan(user, FREE_PLAN, requested=plan, subscription_status="pending_payment")
    db.commit()
    db.refresh(user)
    return {
        "checkout_session_id": session_id,
        "checkout_url": f"{streamlit_base_url()}?billing_session_id={session_id}",
        "payment_required_message": payment_required_message(plan),
        "active_plan": current_plan(user),
        "requested_plan": plan,
        "trial_days": trial_days,
        "trial_end_date": trial_end.date().isoformat(),
        "future_monthly_price": monthly_price,
        "cancellation_terms": "Cancel any time before trial ends to avoid charges.",
        "billing_reminder": "A billing reminder will be sent before your first charge.",
    }


def record_webhook_event(db: Session, *, event_id: str, event_type: str, raw_payload: str) -> bool:
    existing = (
        db.query(BillingEvent)
        .filter(BillingEvent.provider_event_id == event_id)
        .first()
    )
    if existing:
        return False
    db.add(
        BillingEvent(
            event_type=event_type,
            provider="mock",
            provider_event_id=event_id,
            raw_payload=raw_payload,
        )
    )
    return True


def activate_purchased_plan(db: Session, *, checkout_session_id: str, event_id: str, customer_id: str | None = None, subscription_id: str | None = None) -> User | None:
    checkout_event = (
        db.query(BillingEvent)
        .filter(BillingEvent.provider_event_id == checkout_session_id)
        .filter(BillingEvent.event_type == "checkout_session_created")
        .first()
    )
    if not checkout_event or not checkout_event.user_id:
        return None

    user = db.query(User).filter(User.id == checkout_event.user_id).first()
    if not user:
        return None

    requested = normalize_plan(user.requested_plan or json.loads(checkout_event.raw_payload or "{}" ).get("requested_plan", FREE_PLAN))
    if requested not in PAYMENT_PLANS:
        requested = FREE_PLAN

    if not record_webhook_event(db, event_id=event_id, event_type="payment_succeeded", raw_payload=json.dumps({"checkout_session_id": checkout_session_id, "user_id": user.id, "requested_plan": requested})):
        return user

    user.payment_customer_id = customer_id
    user.payment_subscription_id = subscription_id
    set_user_plan(user, requested, requested=None, subscription_status="active")
    user.subscription_status = "active"

    if user.referrer_id:
        existing_reward = (
            db.query(Referral)
            .filter(Referral.referred_user_id == user.id)
            .filter(Referral.status == "converted")
            .first()
        )
        if not existing_reward:
            referral_row = (
                db.query(Referral)
                .filter(Referral.referrer_user_id == user.referrer_id)
                .filter(Referral.referred_email == user.email.lower())
                .order_by(Referral.created_at.desc())
                .first()
            )
            if not referral_row:
                referral_row = Referral(
                    referrer_user_id=user.referrer_id,
                    referred_user_id=user.id,
                    referred_email=user.email.lower(),
                    referral_code=None,
                    status="converted",
                    reward_cents=500,
                    converted_at=datetime.now(timezone.utc),
                    rewarded_at=datetime.now(timezone.utc),
                )
                db.add(referral_row)
            else:
                referral_row.referred_user_id = user.id
                referral_row.status = "converted"
                referral_row.reward_cents = 500
                referral_row.converted_at = datetime.now(timezone.utc)
                referral_row.rewarded_at = datetime.now(timezone.utc)
            referrer = db.query(User).filter(User.id == user.referrer_id).first()
            if referrer:
                referrer.referral_credit_cents = (referrer.referral_credit_cents or 0) + 500

    db.commit()
    db.refresh(user)
    return user


def fail_checkout(db: Session, *, checkout_session_id: str, event_id: str, cancelled: bool = False) -> User | None:
    checkout_event = (
        db.query(BillingEvent)
        .filter(BillingEvent.provider_event_id == checkout_session_id)
        .filter(BillingEvent.event_type == "checkout_session_created")
        .first()
    )
    if not checkout_event or not checkout_event.user_id:
        return None
    user = db.query(User).filter(User.id == checkout_event.user_id).first()
    if not user:
        return None
    if not record_webhook_event(
        db,
        event_id=event_id,
        event_type="payment_cancelled" if cancelled else "payment_failed",
        raw_payload=json.dumps({"checkout_session_id": checkout_session_id, "user_id": user.id}),
    ):
        return user

    set_user_plan(user, FREE_PLAN, requested=None, subscription_status="cancelled" if cancelled else "failed")
    user.payment_customer_id = None
    user.payment_subscription_id = None
    user.subscription_status = "cancelled" if cancelled else "failed"
    db.commit()
    db.refresh(user)
    return user