import os
import stripe

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/billing", tags=["billing"])

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

PRICE_IDS = {
    "premium": os.environ["STRIPE_PREMIUM_PRICE_ID"],
    "premium_plus": os.environ["STRIPE_PREMIUM_PLUS_PRICE_ID"],
}


@router.post("/checkout")
def create_checkout_session(
    plan: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    if user.trial_used:
        raise HTTPException(
            status_code=400,
            detail="You have already used your free trial.",
        )

    base_url = os.environ["NESTAI_STREAMLIT_URL"].rstrip("/")

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=user.email,
        payment_method_collection="always",
        line_items=[
            {
                "price": PRICE_IDS[plan],
                "quantity": 1,
            }
        ],
        subscription_data={
            "trial_period_days": 7,
            "metadata": {
                "nestai_user_id": str(user.id),
                "nestai_plan": plan,
            },
        },
        metadata={
            "nestai_user_id": str(user.id),
            "nestai_plan": plan,
        },
        success_url=f"{base_url}/?checkout=success",
        cancel_url=f"{base_url}/?checkout=cancelled",
    )

    return {"checkout_url": session.url}