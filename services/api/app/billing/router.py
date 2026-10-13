"""Authenticated billing endpoints and Stripe-signed webhook."""

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.auth.plans import current_plan
from app.db.models.user import User
from app.db.session import get_db
from app.billing import service

router = APIRouter(prefix="/billing", tags=["billing"])


class Checkout(BaseModel):
    plan: str
    trial_consent: bool = False
    payment_method_confirmed: bool = False
    idempotency_key: str = Field(min_length=1, max_length=128)


@router.post("/checkout")
def checkout(payload: Checkout, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.create_checkout_session(
        db, user, payload.plan, trial_consent=payload.trial_consent,
        payment_method_confirmed=payload.payment_method_confirmed,
        idempotency_key=payload.idempotency_key,
    )


@router.get("/status")
def status(user: User = Depends(get_current_user)):
    return {"active_plan": current_plan(user), "requested_plan": user.requested_plan,
            "subscription_status": user.subscription_status,
            "trial_used": user.trial_used, "trial_ends_at": user.trial_ends_at,
            "cancel_at_period_end": user.cancel_at_period_end,
            "billing_configured": bool(__import__("os").getenv("STRIPE_SECRET_KEY"))}


@router.get("/prices")
def prices(user: User = Depends(get_current_user)):
    return {plan: {"amount_cents": price.get("unit_amount"), "currency": price.get("currency"),
                   "recurring": dict(price.get("recurring") or {})}
            for plan in ("premium", "premium_plus") for price in [service.price_for(plan)]}


@router.post("/portal")
def portal(user: User = Depends(get_current_user)):
    return service.portal(user)


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 2_000_000:
        raise HTTPException(413, "Webhook body too large")
    return service.process_webhook(db, raw, request.headers.get("stripe-signature", ""))
