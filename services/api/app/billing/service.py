"""Stripe-only billing. No local event can activate a subscription."""

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
import os
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.plans import PAYMENT_PLANS, current_plan, normalize_plan, set_user_plan
from app.db.models.billing import BillingEvent
from app.db.models.user import User


def plain(value):
    """Normalize SDK containers recursively without losing decimal precision."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Stripe decimal")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite Stripe number")
        return value
    from stripe import StripeObject
    if isinstance(value, StripeObject):
        value = value.to_dict()
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Stripe object keys must be strings")
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    raise TypeError(f"Unsupported Stripe value type: {type(value).__name__}")


def stripe_client():
    key = os.getenv("STRIPE_SECRET_KEY", "")
    if not key:
        raise HTTPException(503, "Stripe billing is not configured")
    if not key.startswith("sk_test_") and os.getenv("STRIPE_ALLOW_LIVE", "").lower() != "true":
        raise HTTPException(503, "Live Stripe billing requires explicit configuration")
    import stripe
    return stripe, key


def return_url():
    from app.core.config import get_settings
    base = os.getenv("NESTAI_STREAMLIT_URL", "http://localhost:8501").rstrip("/")
    parsed = urlparse(base)
    if not parsed.hostname or parsed.scheme not in {"http", "https"} or (
        not get_settings().is_development and parsed.scheme != "https"
    ):
        raise HTTPException(503, "Billing return URL is not securely configured")
    if parsed.query or parsed.fragment or parsed.username:
        raise HTTPException(503, "Billing return URL must not contain query, credentials or fragment")
    return base


def payment_required_message(plan: str) -> str:
    return f"Payment required to activate {'Premium Plus' if plan == 'premium_plus' else 'Premium'}"


def price_for(plan: str):
    if plan not in PAYMENT_PLANS:
        raise HTTPException(422, "Invalid paid plan")
    stripe, key = stripe_client()
    prefix = "STRIPE_PREMIUM_PLUS" if plan == "premium_plus" else "STRIPE_PREMIUM"
    price_id = os.getenv(prefix + "_PRICE_ID")
    try:
        if not price_id:
            product_id = os.getenv(prefix + "_PRODUCT_ID")
            if not product_id:
                raise HTTPException(503, "Stripe price/product is not configured")
            product = plain(stripe.Product.retrieve(product_id, api_key=key))
            price_id = product.get("default_price")
        if not isinstance(price_id, str):
            raise HTTPException(503, "Stripe product has no default price")
        price = plain(stripe.Price.retrieve(price_id, api_key=key))
    except stripe.StripeError:
        raise HTTPException(502, "Stripe price lookup failed") from None
    if not price.get("active") or price.get("type") != "recurring":
        raise HTTPException(503, "Configured Stripe price is not an active subscription price")
    return price


def create_checkout_session(
    db: Session, user: User, requested_plan: str, *,
    trial_consent: bool = False, payment_method_confirmed: bool = False,
    idempotency_key: str | None = None,
) -> dict:
    plan = normalize_plan(requested_plan)
    stripe, key = stripe_client()
    user = db.query(User).filter(User.id == user.id).populate_existing().with_for_update().one()
    if user.stripe_subscription_id and user.subscription_status in {"active", "trialing", "past_due"}:
        raise HTTPException(409, "Manage an existing subscription through the billing portal")
    price = price_for(plan)
    pending = db.query(BillingEvent).filter_by(
        user_id=user.id, provider="stripe", event_type="checkout_session_created"
    ).order_by(BillingEvent.id.desc()).first()
    if pending:
        try:
            prior = plain(stripe.checkout.Session.retrieve(pending.provider_event_id, api_key=key))
            if prior.get("status") == "open":
                response = json.loads(pending.raw_payload)
                if response.get("requested_plan") == plan:
                    return response
                stripe.checkout.Session.expire(prior["id"], api_key=key)
            elif prior.get("status") == "complete" and (
                not user.stripe_subscription_id or user.subscription_status == "pending_payment"
            ):
                raise HTTPException(409, "Checkout completed; waiting for verified subscription synchronization")
        except stripe.StripeError:
            raise HTTPException(502, "Stripe checkout status is temporarily unavailable") from None
    base = return_url()
    metadata = {"nestai_user_id": str(user.id), "nestai_plan": plan}
    subscription_data = {"metadata": metadata}
    if trial_consent and payment_method_confirmed and not user.trial_used:
        subscription_data["trial_period_days"] = 7
    try:
        if not user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=user.email, metadata={"nestai_user_id": str(user.id)},
                api_key=key, idempotency_key=f"nestai-customer-{user.id}",
            )
            user.stripe_customer_id = user.payment_customer_id = customer["id"]
        session = stripe.checkout.Session.create(
            mode="subscription", customer=user.stripe_customer_id,
            payment_method_collection="always",
            line_items=[{"price": price["id"], "quantity": 1}],
            subscription_data=subscription_data, metadata=metadata,
            client_reference_id=str(user.id),
            success_url=f"{base}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/?checkout=cancelled",
            api_key=key, idempotency_key=f"nestai-checkout-{user.id}-{idempotency_key or plan}",
        )
    except stripe.StripeError:
        db.rollback()
        raise HTTPException(502, "Stripe checkout is temporarily unavailable") from None
    user.requested_plan = plan
    if current_plan(user) not in PAYMENT_PLANS:
        user.subscription_status = "pending_payment"
    response = {
        "checkout_session_id": session["id"], "checkout_url": session["url"],
        "requested_plan": plan, "active_plan": current_plan(user),
        "trial_days": subscription_data.get("trial_period_days", 0),
        "price": {"amount_cents": price.get("unit_amount"), "currency": price.get("currency"),
                  "recurring": dict(price.get("recurring") or {})},
        "payment_required_message": payment_required_message(plan),
    }
    db.add(BillingEvent(user_id=user.id, provider="stripe", event_type="checkout_session_created",
                       provider_event_id=session["id"], tier_before=current_plan(user),
                       raw_payload=json.dumps(response)))
    db.commit()
    return response


def portal(user: User, requested_plan: str | None = None) -> dict:
    stripe, key = stripe_client()
    if not user.stripe_customer_id:
        raise HTTPException(409, "No Stripe customer exists for this account")
    try:
        base = return_url()
        options = {}
        if requested_plan is not None:
            plan = normalize_plan(requested_plan)
            if plan not in PAYMENT_PLANS:
                raise HTTPException(422, "Invalid paid plan")
            if not user.stripe_subscription_id:
                raise HTTPException(409, "No existing Stripe subscription to change")
            sub = plain(stripe.Subscription.retrieve(user.stripe_subscription_id, api_key=key))
            items = (sub.get("items") or {}).get("data", [])
            if sub.get("customer") != user.stripe_customer_id or sub.get("status") not in {"active", "trialing", "past_due"}:
                raise HTTPException(409, "No manageable subscription exists for this account")
            if len(items) != 1 or not items[0].get("id") or items[0].get("quantity", 1) != 1:
                raise HTTPException(409, "Subscription requires manual billing management")
            options["flow_data"] = {
                "type": "subscription_update_confirm",
                "subscription_update_confirm": {
                    "subscription": user.stripe_subscription_id,
                    "items": [{"id": items[0]["id"], "price": price_for(plan)["id"], "quantity": 1}],
                },
                "after_completion": {"type": "redirect", "redirect": {"return_url": base}},
            }
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=base,
            api_key=key, **options,
        )
        return {"portal_url": session["url"]}
    except stripe.StripeError:
        raise HTTPException(502, "Stripe portal is temporarily unavailable") from None


def subscription_plan(sub):
    # Portal price changes do not update checkout's nestai_plan metadata.
    items = (sub.get("items") or {}).get("data", [])
    if len(items) != 1 or items[0].get("quantity", 1) != 1:
        return "free"
    item_price = items[0].get("price") or {}
    price_id = item_price if isinstance(item_price, str) else item_price.get("id")
    matches = []
    for plan, prefix in (("premium", "STRIPE_PREMIUM"), ("premium_plus", "STRIPE_PREMIUM_PLUS")):
        if os.getenv(prefix + "_PRICE_ID") or os.getenv(prefix + "_PRODUCT_ID"):
            if price_for(plan)["id"] == price_id:
                matches.append(plan)
    if len(matches) > 1:
        raise HTTPException(503, "Stripe plans must use distinct prices")
    return matches[0] if matches else "free"


def process_webhook(db: Session, raw: bytes, signature: str) -> dict:
    import stripe
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "Stripe webhook is not configured")
    try:
        event = stripe.Webhook.construct_event(raw, signature, secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid Stripe webhook signature") from None
    try:
        return _process_verified_webhook(db, plain(event))
    except (TypeError, ValueError):
        db.rollback()
        raise HTTPException(502, "Stripe event processing failed; retry webhook") from None
    except Exception:
        db.rollback()
        raise


def _process_verified_webhook(db: Session, event: dict) -> dict:
    if not isinstance(event.get("id"), str) or not isinstance(event.get("type"), str) or not isinstance(
        (event.get("data") or {}).get("object"), dict
    ):
        raise HTTPException(400, "Invalid Stripe event")
    if event.get("livemode") and os.getenv("STRIPE_ALLOW_LIVE", "").lower() != "true":
        raise HTTPException(400, "Live Stripe events are not enabled")
    if db.query(BillingEvent).filter_by(provider_event_id=event["id"]).first():
        return {"received": True, "duplicate": True}
    # Flush the unique event marker before processing; transaction rollback allows retries.
    marker = BillingEvent(provider="stripe", provider_event_id=event["id"],
                          event_type=event["type"], raw_payload=json.dumps(event))
    db.add(marker)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"received": True, "duplicate": True}
    obj = event["data"]["object"]
    subscription_id = None
    if event["type"].startswith("customer.subscription."):
        subscription_id = obj.get("id")
    elif event["type"] in {"checkout.session.completed", "checkout.session.async_payment_succeeded",
                           "invoice.paid", "invoice.payment_failed"}:
        subscription_id = obj.get("subscription")
        if not subscription_id:
            subscription_id = (obj.get("parent") or {}).get("subscription_details", {}).get("subscription")
    if subscription_id:
        sdk, key = stripe_client()
        customer = obj.get("customer")
        user = db.query(User).filter_by(stripe_customer_id=customer).populate_existing().with_for_update().first() if customer else None
        try:
            # Read current state instead of trusting arrival order or checkout redirect.
            sub = plain(sdk.Subscription.retrieve(subscription_id, api_key=key))
            if user is None:
                metadata = sub.get("metadata") or {}
                try:
                    user_id = int(metadata.get("nestai_user_id", ""))
                except (ValueError, TypeError):
                    user_id = None
                user = db.query(User).filter(User.id == user_id).populate_existing().with_for_update().first() if user_id else None
                if user:
                    # Refresh after acquiring the account lock: another webhook may have waited too.
                    sub = plain(sdk.Subscription.retrieve(subscription_id, api_key=key))
        except sdk.StripeError:
            db.rollback()
            raise HTTPException(502, "Stripe subscription lookup failed; retry webhook") from None
        metadata = sub.get("metadata") or {}
        owner = metadata.get("nestai_user_id")
        if user and user.stripe_customer_id == sub.get("customer") and (
            str(owner) == str(user.id) or (owner is None and user.stripe_subscription_id == sub["id"])
        ):
            if user.stripe_subscription_id and user.stripe_subscription_id != sub["id"] and (
                user.subscription_status in {"active", "trialing", "past_due"}
                or sub.get("status") not in {"active", "trialing"}
            ):
                db.commit()
                return {"received": True, "ignored": True}
            status = sub.get("status", "incomplete")
            previous = current_plan(user)
            active = subscription_plan(sub) if status in {"active", "trialing"} else "free"
            set_user_plan(user, active, subscription_status=status)
            user.stripe_subscription_id = user.payment_subscription_id = sub["id"]
            user.payment_customer_id = user.stripe_customer_id
            user.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
            if sub.get("trial_end"):
                user.trial_used = True
                user.trial_ends_at = datetime.fromtimestamp(sub["trial_end"], timezone.utc)
            marker.user_id, marker.tier_before, marker.tier_after = user.id, previous, active
    db.commit()
    return {"received": True, "duplicate": False}
