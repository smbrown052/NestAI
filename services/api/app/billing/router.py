"""Billing endpoints for checkout, status, and webhook activation."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.plans import PAYMENT_PLANS, normalize_plan
from app.auth.schemas import BillingStatusRead, CheckoutSessionCreateRequest, CheckoutSessionCreateResponse
from app.db.models.user import User
from app.db.models.billing import BillingEvent
from app.db.session import get_db

from .service import (
    activate_purchased_plan,
    create_checkout_session,
    fail_checkout,
    payment_required_message,
    record_webhook_event,
    streamlit_base_url,
    verify_webhook_signature,
)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/create-checkout-session", response_model=CheckoutSessionCreateResponse)
def create_checkout_session_endpoint(
    payload: CheckoutSessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CheckoutSessionCreateResponse:
    plan = normalize_plan(payload.plan)
    if plan not in PAYMENT_PLANS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan does not require checkout")
    try:
        session_info = create_checkout_session(
            db,
            current_user,
            plan,
            trial_consent=payload.trial_consent,
            payment_method_confirmed=payload.payment_method_confirmed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return CheckoutSessionCreateResponse(**session_info)


@router.post("/webhook")
async def billing_webhook(
    request: Request,
    x_nestai_signature: str | None = Header(default=None, alias="X-NestAI-Signature"),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    if not x_nestai_signature or not verify_webhook_signature(raw_body, x_nestai_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    payload = json.loads(raw_body.decode("utf-8"))
    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    checkout_session_id = payload.get("checkout_session_id")

    if not event_id or not event_type or not checkout_session_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing webhook fields")

    if event_type == "payment_succeeded":
        user = activate_purchased_plan(
            db,
            checkout_session_id=checkout_session_id,
            event_id=event_id,
            customer_id=payload.get("payment_customer_id"),
            subscription_id=payload.get("payment_subscription_id"),
        )
    elif event_type in {"payment_failed", "payment_cancelled"}:
        user = fail_checkout(db, checkout_session_id=checkout_session_id, event_id=event_id, cancelled=event_type == "payment_cancelled")
    else:
        if not record_webhook_event(db, event_id=event_id, event_type=event_type, raw_payload=raw_body.decode("utf-8")):
            return {"status": "ignored"}
        db.commit()
        return {"status": "recorded"}

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checkout session not found")
    return {"status": "ok", "active_plan": user.active_plan, "subscription_status": user.subscription_status}


@router.get("/status", response_model=BillingStatusRead)
def billing_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> BillingStatusRead:
    requested = current_user.requested_plan
    payment_message = None
    checkout_session_id = None
    checkout_url = None
    if current_user.subscription_status == "pending_payment" and requested:
        payment_message = payment_required_message(requested)
        latest_checkout = (
            db.query(BillingEvent)
            .filter(BillingEvent.user_id == current_user.id)
            .filter(BillingEvent.event_type == "checkout_session_created")
            .order_by(BillingEvent.created_at.desc())
            .first()
        )
        checkout_session_id = latest_checkout.provider_event_id if latest_checkout else None
        checkout_url = f"{streamlit_base_url()}?billing_session_id={checkout_session_id}" if checkout_session_id else None
    return BillingStatusRead(
        active_plan=current_user.active_plan,
        requested_plan=requested,
        subscription_status=current_user.subscription_status,
        payment_customer_id=current_user.payment_customer_id,
        payment_subscription_id=current_user.payment_subscription_id,
        checkout_session_id=checkout_session_id,
        checkout_url=checkout_url,
        payment_required_message=payment_message,
        trial_days=7 if requested in PAYMENT_PLANS else None,
        future_monthly_price=("$49/mo" if requested == "premium_plus" else "$19/mo") if requested in PAYMENT_PLANS else None,
        cancellation_terms="Cancel any time before trial ends to avoid charges." if requested in PAYMENT_PLANS else None,
        billing_reminder="A billing reminder will be sent before your first charge." if requested in PAYMENT_PLANS else None,
    )