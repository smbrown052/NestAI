"""Signed local SDK regressions; Stripe API responses are mocked, not live."""

from collections import UserDict
from decimal import Decimal
import json
import time
from unittest.mock import patch

from fastapi import HTTPException
import pytest
import stripe

from app.billing import service
from app.db.models.billing import BillingEvent
from app.db.models.credits import CreditBalance, CreditTransaction
from app.db.models.user import User
from test_platform import api, stripe_signature


SECRET = "local-testing-only"
DECIMAL_AMOUNT = "1234.5678901234567890123400"


def subscription(user_id, *, price="price_premium", status="active"):
    return {
        "id": "sub_basil", "object": "subscription", "customer": "cus_basil",
        "status": status, "cancel_at_period_end": False,
        "metadata": {"nestai_user_id": str(user_id), "nestai_plan": "premium"},
        "items": {"object": "list", "data": [{
            "id": "si_basil", "object": "subscription_item", "quantity": 1,
            "current_period_start": 1753833600, "current_period_end": 1756512000,
            "price": {"id": price, "object": "price", "active": True,
                      "type": "recurring", "currency": "usd", "unit_amount": 1234,
                      "unit_amount_decimal": DECIMAL_AMOUNT,
                      "recurring": {"interval": "month", "interval_count": 1}},
        }], "has_more": False, "url": "/v1/subscription_items?subscription=sub_basil"},
    }


def event_payload(event_type, user_id, event_id="evt_basil"):
    if event_type.startswith("customer.subscription."):
        obj = subscription(user_id)
    elif event_type.startswith("invoice."):
        obj = {
            "id": "in_basil", "object": "invoice", "customer": "cus_basil",
            "status": "paid", "paid": True, "currency": "usd", "amount_paid": 1234,
            "parent": {"type": "subscription_details", "subscription_details": {
                "subscription": "sub_basil", "metadata": {"nestai_user_id": str(user_id)}}},
            "lines": {"object": "list", "has_more": False, "data": [{
                "id": "il_basil", "object": "line_item", "amount": 1234, "quantity": 1,
                "currency": "usd", "period": {"start": 1753833600, "end": 1756512000},
                "parent": {"type": "subscription_item_details", "subscription_item_details": {
                    "subscription": "sub_basil", "subscription_item": "si_basil"}},
                "pricing": {"type": "price_details", "price_details": {
                    "price": "price_premium", "product": "prod_premium"},
                    "unit_amount_decimal": DECIMAL_AMOUNT},
            }]},
        }
    else:
        obj = {
            "id": "cs_basil", "object": "checkout.session", "customer": "cus_basil",
            "subscription": "sub_basil", "mode": "subscription", "status": "complete",
            "payment_status": "paid", "client_reference_id": str(user_id),
            "metadata": {"nestai_user_id": str(user_id), "nestai_plan": "premium"},
            "line_items": subscription(user_id)["items"],
        }
    return {
        "id": event_id, "object": "event", "api_version": "2025-07-30.basil",
        "created": int(time.time()), "livemode": False, "pending_webhooks": 1,
        "request": {"id": None, "idempotency_key": None},
        "type": event_type, "data": {"object": obj},
    }


def signed(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return raw, stripe_signature(raw, SECRET)


def sdk_subscription(user_id, **kwargs):
    return stripe.Subscription.construct_from(subscription(user_id, **kwargs), None)


def price_response(price_id, **kwargs):
    return stripe.Price.construct_from({
        "id": price_id, "object": "price", "active": True, "type": "recurring",
        "unit_amount_decimal": DECIMAL_AMOUNT,
    }, None)


@pytest.fixture
def billing(api, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_PREMIUM_PRICE_ID", "price_premium")
    monkeypatch.setenv("STRIPE_PREMIUM_PLUS_PRICE_ID", "price_plus")
    monkeypatch.delenv("STRIPE_ALLOW_LIVE", raising=False)
    for prefix in ("STRIPE_PREMIUM", "STRIPE_PREMIUM_PLUS"):
        monkeypatch.delenv(prefix + "_PRODUCT_ID", raising=False)
    _, factory, _, ids, _ = api
    with factory() as db:
        db.get(User, ids[0]).stripe_customer_id = "cus_basil"
        db.add(CreditBalance(user_id=ids[0], credits_remaining=87))
        db.commit()
    return api


def assert_state(billing, plan="free", markers=0, status=None):
    _, factory, _, ids, _ = billing
    with factory() as db:
        user = db.get(User, ids[0])
        assert user.active_plan == user.tier == plan
        if status:
            assert user.subscription_status == status
        assert db.query(BillingEvent).count() == markers
        assert db.query(CreditBalance).one().credits_remaining == 87
        assert db.query(CreditTransaction).count() == 0


def verify_signed_event(billing, event_type):
    client, factory, _, ids, _ = billing
    raw, signature = signed(event_payload(event_type, ids[0]))
    event = stripe.Webhook.construct_event(raw, signature, SECRET)
    obj = event["data"]["object"]
    if event_type == "invoice.paid":
        amount = obj["lines"]["data"][0]["pricing"]["unit_amount_decimal"]
    else:
        items = obj["items"] if event_type.startswith("customer.subscription.") else obj["line_items"]
        amount = items["data"][0]["price"]["unit_amount_decimal"]
    assert isinstance(amount, Decimal)
    with patch("stripe.Subscription.retrieve", return_value=sdk_subscription(ids[0])) as retrieve, patch(
        "stripe.Price.retrieve", side_effect=price_response
    ):
        response = client.post("/billing/webhook", content=raw, headers={"Stripe-Signature": signature})
    assert response.status_code == 200, response.text
    assert response.json() == {"received": True, "duplicate": False}
    retrieve.assert_called_once_with("sub_basil", api_key="sk_test_placeholder")
    assert_state(billing, "premium", 1, "active")
    with factory() as db:
        saved = json.loads(db.query(BillingEvent).one().raw_payload)
        assert saved == json.loads(raw)


def test_signed_basil_invoice_paid_nested_decimal(billing):
    verify_signed_event(billing, "invoice.paid")


def test_signed_basil_subscription_created_nested_decimal(billing):
    verify_signed_event(billing, "customer.subscription.created")


@pytest.mark.parametrize("event_type", [
    "checkout.session.completed", "checkout.session.async_payment_succeeded",
])
def test_signed_basil_checkout_nested_decimal(billing, event_type):
    verify_signed_event(billing, event_type)


def test_plain_recursively_normalizes_mixed_sdk_mappings_and_lists():
    source = UserDict({"nested": [
        stripe.StripeObject.construct_from({"pricing": {"unit_amount_decimal": DECIMAL_AMOUNT}}, None),
        {"amount": Decimal("0.0000000000000000000000000001")},
        None, True, 1, 1.5, "text",
    ]})
    normalized = service.plain(source)
    assert type(normalized) is dict
    assert type(normalized["nested"][0]) is dict
    assert normalized["nested"][0]["pricing"]["unit_amount_decimal"] == DECIMAL_AMOUNT
    assert normalized["nested"][1]["amount"] == "1E-28"
    json.dumps(normalized, allow_nan=False)
    assert isinstance(source["nested"][1]["amount"], Decimal)


@pytest.mark.parametrize("value", [
    object(), b"bytes", ("tuple",), {1: "non-string key"}, {1, 2},
    Decimal("NaN"), Decimal("Infinity"), float("nan"), float("inf"),
])
def test_plain_rejects_unsupported_or_nonfinite_nested_values(value):
    with pytest.raises((TypeError, ValueError)):
        service.plain({"nested": [{"unsupported": value}]})


def test_failed_subscription_normalization_rolls_back_marker_then_retries(billing):
    _, factory, _, ids, _ = billing
    raw, signature = signed(event_payload("invoice.paid", ids[0], "evt_retry_normalization"))
    bad = sdk_subscription(ids[0])
    bad["items"]["data"][0]["price"]["unsupported"] = object()
    with factory() as db, patch("stripe.Subscription.retrieve", return_value=bad):
        with pytest.raises(HTTPException) as failure:
            service.process_webhook(db, raw, signature)
        assert failure.value.status_code == 502
        assert db.query(BillingEvent).count() == 0
        assert db.get(User, ids[0]).active_plan == "free"
        with patch("stripe.Subscription.retrieve", return_value=sdk_subscription(ids[0])), patch(
            "stripe.Price.retrieve", side_effect=price_response
        ):
            assert service.process_webhook(db, raw, signature)["duplicate"] is False
    assert_state(billing, "premium", 1)


def test_failed_event_normalization_is_retryable_and_not_a_signature_error(billing):
    _, factory, _, ids, _ = billing
    raw, signature = signed(event_payload("invoice.paid", ids[0], "evt_retry_event"))
    with factory() as db:
        with patch.object(service, "plain", side_effect=TypeError("unsupported SDK value")):
            with pytest.raises(HTTPException) as failure:
                service.process_webhook(db, raw, signature)
        assert failure.value.status_code == 502
        assert db.query(BillingEvent).count() == 0
        with patch("stripe.Subscription.retrieve", return_value=sdk_subscription(ids[0])), patch(
            "stripe.Price.retrieve", side_effect=price_response
        ):
            assert service.process_webhook(db, raw, signature)["duplicate"] is False
    assert_state(billing, "premium", 1)


def test_failure_after_user_mutation_rolls_back_same_session_and_retries(billing):
    _, factory, _, ids, _ = billing
    raw, signature = signed(event_payload("customer.subscription.created", ids[0], "evt_retry_mutation"))
    original = service.set_user_plan

    def fail_after_mutation(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("processing interrupted")

    with factory() as db, patch("stripe.Subscription.retrieve", return_value=sdk_subscription(ids[0])), patch(
        "stripe.Price.retrieve", side_effect=price_response
    ):
        with patch.object(service, "set_user_plan", side_effect=fail_after_mutation), pytest.raises(RuntimeError):
            service.process_webhook(db, raw, signature)
        db.commit()
        assert db.query(BillingEvent).count() == 0
        assert db.get(User, ids[0]).active_plan == "free"
        assert service.process_webhook(db, raw, signature)["duplicate"] is False
    assert_state(billing, "premium", 1)


def test_signed_duplicates_out_of_order_upgrade_downgrade_cancel_and_recovery(billing):
    client, _, headers, ids, _ = billing

    def send(event_id, event_type, current, *, error=None):
        raw, signature = signed(event_payload(event_type, ids[0], event_id))
        with patch("stripe.Subscription.retrieve", return_value=current, side_effect=error), patch(
            "stripe.Price.retrieve", side_effect=price_response
        ):
            return client.post("/billing/webhook", content=raw, headers={"Stripe-Signature": signature})

    current = sdk_subscription(ids[0])
    assert send("evt_create", "customer.subscription.created", current).status_code == 200
    with patch("stripe.Subscription.retrieve") as retrieve, patch("stripe.Price.retrieve") as price:
        raw, signature = signed(event_payload("customer.subscription.created", ids[0], "evt_create"))
        assert client.post("/billing/webhook", content=raw, headers={
            "Stripe-Signature": signature}).json()["duplicate"] is True
        retrieve.assert_not_called()
        price.assert_not_called()
    current = sdk_subscription(ids[0], price="price_plus")
    assert send("evt_upgrade", "customer.subscription.updated", current).status_code == 200
    assert_state(billing, "premium_plus", 2)
    # The stale invoice still describes Premium; current Stripe price controls access.
    assert send("evt_old_invoice", "invoice.paid", current).status_code == 200
    assert_state(billing, "premium_plus", 3)
    current = sdk_subscription(ids[0])
    current["metadata"]["nestai_plan"] = "premium_plus"
    current["cancel_at_period_end"] = True
    assert send("evt_downgrade", "customer.subscription.updated", current).status_code == 200
    assert_state(billing, "premium", 4)
    assert client.get("/billing/status", headers=headers[0]).json()["cancel_at_period_end"] is True
    current = sdk_subscription(ids[0], status="past_due")
    assert send("evt_failed_payment", "invoice.payment_failed", current).status_code == 200
    assert_state(billing, "free", 5, "past_due")
    current = sdk_subscription(ids[0], price="price_plus")
    assert send("evt_recovered", "invoice.paid", current,
                error=stripe.APIConnectionError("mock unavailable")).status_code == 502
    assert_state(billing, "free", 5, "past_due")
    assert send("evt_recovered", "invoice.paid", current).status_code == 200
    assert_state(billing, "premium_plus", 6, "active")
    current = sdk_subscription(ids[0], status="canceled")
    assert send("evt_cancel", "customer.subscription.deleted", current).status_code == 200
    assert send("evt_stale_create", "customer.subscription.created", current).status_code == 200
    assert_state(billing, "free", 8, "canceled")


@pytest.mark.parametrize("invalid", ["missing", "wrong_secret", "tampered", "expired"])
def test_invalid_signatures_never_write_or_lookup_subscriptions(billing, invalid):
    client, _, _, ids, _ = billing
    raw, signature = signed(event_payload("invoice.paid", ids[0]))
    if invalid == "missing":
        signature = ""
    elif invalid == "wrong_secret":
        signature = stripe_signature(raw, "not-the-configured-secret")
    elif invalid == "tampered":
        raw += b" "
    else:
        signature = "t=1,v1=" + "0" * 64
    with patch("stripe.Subscription.retrieve") as retrieve, patch("stripe.Price.retrieve") as price:
        assert client.post("/billing/webhook", content=raw, headers={
            "Stripe-Signature": signature}).status_code == 400
        retrieve.assert_not_called()
        price.assert_not_called()
    assert_state(billing)
