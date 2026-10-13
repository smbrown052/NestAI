"""Local tests use mocks; no test represents real provider/Stripe validation."""

from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models
from app.db.base import Base
from app.db.models.account import MonthlyUsage, AccountProperty
from app.db.models.credits import CreditBalance, CreditTransaction
from app.db.models.referral import Referral
from app.db.models.user import User
from app.db.session import get_db
from app.auth.security import create_access_token
from app.platform import providers
from main import app
from shared.entitlements import limits_for

APARTMENT_TEXT = (
    "Building\n123 Main St, Arlington, VA 22201\nPricing & Floor Plans\n"
    "A1\n$2,000\n2 Bed\n1.5 Bath\n900 Sq Ft\n"
    "Unit\n0012\nprice\n$2,000\nsquare feet\n900\navailabilityNow"
)


@pytest.fixture(params=["sqlite", "postgres"])
def api(request, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("NESTAI_PROVIDER_MODE", "mock")
    if request.param == "postgres":
        url = os.getenv("NESTAI_TEST_DATABASE_URL") or os.getenv("TEST_POSTGRES_URL")
        if not url:
            pytest.skip("NESTAI_TEST_DATABASE_URL not configured; no PostgreSQL claim")
        admin = create_engine(url)
        schema = "test_" + uuid4().hex
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        admin = None
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    with factory() as db:
        users = [User(email=f"user{i}@example.com", hashed_password="not-used",
                      active_plan="free", tier="free", subscription_status="active") for i in (1, 2)]
        db.add_all(users)
        db.commit()
        ids = [user.id for user in users]
    headers = [{"Authorization": "Bearer " + create_access_token({"sub": str(i)})} for i in ids]
    client = TestClient(app)
    yield client, factory, headers, ids, request.param
    app.dependency_overrides.clear()
    engine.dispose()
    if admin:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def paid(api, plan="premium"):
    _, factory, _, ids, _ = api
    with factory() as db:
        user = db.get(User, ids[0])
        user.active_plan = user.tier = plan
        db.commit()


def save(api, key="save", **parsed):
    client, _, headers, _, _ = api
    result = client.post("/properties", headers=headers[0],
                         json={"kind": "apartment", "parsed": parsed or {"address": "123 Main St"},
                               "external_id": key, "idempotency_key": key})
    assert result.status_code == 200, result.text
    return result.json()


def test_approved_entitlements(api):
    client, _, headers, _, _ = api
    result = client.get("/entitlements", headers=headers[0]).json()
    assert result["limits"] == {"analyses": 5, "properties": 2, "ai": 0, "enrichment": 0, "commute": 0, "reports": 0}
    assert limits_for("premium") == {"analyses": 100, "properties": 50, "ai": 100, "enrichment": 50, "commute": 100, "reports": 20}
    assert limits_for("premium_plus") == {"analyses": 500, "properties": 200, "ai": 500, "enrichment": 200, "commute": 400, "reports": 100}
    assert result["timezone"] == "UTC"


def test_analysis_idempotency_and_monthly_quota(api):
    client, factory, headers, ids, _ = api
    payload = {"kind": "apartment", "text": APARTMENT_TEXT, "idempotency_key": "analysis"}
    result = client.post("/analyses", headers=headers[0], json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["parsed"]["units"][0]["id"] == "0012"
    assert client.post("/analyses", headers=headers[0], json=payload).json() == result.json()
    assert client.post("/analyses", headers=headers[0], json={**payload, "text": "Changed"}).status_code == 409
    for i in range(4):
        assert client.post("/analyses", headers=headers[0], json={**payload, "idempotency_key": f"a{i}"}).status_code == 200
    assert client.post("/analyses", headers=headers[0], json={**payload, "idempotency_key": "over"}).status_code == 429
    with factory() as db:
        assert db.query(MonthlyUsage).filter_by(user_id=ids[0], metric="analyses").one().count == 5


def test_home_parser_adapter(api):
    client, _, headers, _, _ = api
    response = client.post("/analyses", headers=headers[0], json={
        "kind": "home", "idempotency_key": "home", "text": "For sale\n123 Main St, Arlington, VA 22201\n$450,000\n3 beds\n2 baths\n1,500 sqft"})
    assert response.status_code == 200, response.text
    assert "warnings" in response.json()["parsed"]


@pytest.mark.parametrize("kind", ["apartment", "home", "rental_home"])
def test_invalid_analysis_does_not_consume_quota(api, kind):
    client, factory, headers, ids, _ = api
    response = client.post("/analyses", headers=headers[0], json={
        "kind": kind, "text": "not a valid listing", "idempotency_key": "invalid"})
    assert response.status_code == 422
    with factory() as db:
        assert not db.query(MonthlyUsage).filter_by(user_id=ids[0], metric="analyses").first()


def test_apartment_parser_preserves_authoritative_numeric_fields(api):
    client, _, headers, _, _ = api
    response = client.post("/analyses", headers=headers[0], json={
        "kind": "apartment", "idempotency_key": "floorplan", "text":
        "Building\n123 Main St, Arlington, VA 22201\nPricing & Floor Plans\nA1\n$2,000\n2 Bed\n1.5 Bath\n900 Sq Ft\nUnit\n0012\nprice\n$2,000\nsquare feet\n900\navailabilityNow"})
    assert response.status_code == 200, response.text
    parsed = response.json()["parsed"]
    assert parsed["units"][0]["id"] == "0012" and parsed["units"][0]["baths_num"] == 1.5
    saved = client.post("/properties", headers=headers[0], json={
        "kind": "apartment", "parsed": parsed, "idempotency_key": "save-floorplan"})
    assert saved.status_code == 200, saved.text
    result = client.post("/ranking", headers=headers[0], json={
        "constraints": {"min_baths": 1.5, "min_beds": 2}}).json()
    assert result["ranked"][0]["baths_num"] == 1.5 and result["ranked"][0]["beds_num"] == 2


def test_upsert_quotas_unit_ids_and_account_isolation(api):
    client, factory, headers, ids, _ = api
    first = save(api, units=[{"id": "0012", "price": "$2,000", "sqft": "900", "beds": 2, "baths": 1.5}])
    second = save(api, key="other")
    update = client.post("/properties", headers=headers[0], json={
        "kind": "apartment", "parsed": {"units": [{"id": "PH-A", "price": 3000}]},
        "external_id": "save", "idempotency_key": "updated"})
    assert update.status_code == 200
    assert update.json()["id"] == first["id"]
    updated_units = {unit["id"]: unit for unit in update.json()["units"]}
    assert updated_units["0012"]["is_archived"] is True and updated_units["PH-A"]["id"] == "PH-A"
    assert client.post("/properties", headers=headers[0], json={
        "kind": "home", "parsed": {}, "external_id": "third", "idempotency_key": "third"}).status_code == 429
    assert client.get("/properties", headers=headers[1]).json() == {"properties": []}
    assert client.delete("/properties/" + first["id"], headers=headers[1]).status_code == 404
    assert client.post("/ranking", headers=headers[1], json={"property_ids": [first["id"]]}).status_code == 404
    with factory() as db:
        assert db.query(AccountProperty).filter_by(user_id=ids[0]).count() == 2
    assert client.delete("/properties/" + second["id"], headers=headers[0]).status_code == 200


def test_unit_ids_cannot_be_coerced(api):
    client, _, headers, _, _ = api
    response = client.post("/properties", headers=headers[0], json={
        "kind": "apartment", "parsed": {"units": [{"id": 12}]}, "idempotency_key": "numeric"})
    assert response.status_code == 422
    assert client.get("/properties", headers=headers[0]).json()["properties"] == []


def test_partial_save_preserves_units_and_prior_facts(api):
    client, _, headers, _, _ = api
    prop = save(api, address="Main St", units=[{"id": "0012", "price": 2000}])
    response = client.post("/properties", headers=headers[0], json={
        "kind": "apartment", "external_id": prop["external_id"],
        "parsed": {"extra_parking": 100}, "idempotency_key": "fees"})
    assert response.status_code == 200
    assert response.json()["parsed"]["address"] == "Main St"
    assert response.json()["units"][0]["id"] == "0012"


def test_profile_isolation(api):
    client, _, headers, _, _ = api
    assert client.put("/profile", headers=headers[0], json={"preferences": {"budget": 2500}}).status_code == 200
    assert client.get("/profile", headers=headers[0]).json() == {"preferences": {"budget": 2500}}
    assert client.get("/profile", headers=headers[1]).json() == {"preferences": {}}


def test_profile_name_patch_and_natural_requests(api):
    client, factory, headers, ids, _ = api
    response = client.patch("/profile", headers=headers[0], json={"display_name": "  Updated Name  "})
    assert response.status_code == 200 and response.json()["display_name"] == "Updated Name"
    with factory() as db:
        assert db.get(User, ids[0]).display_name == "Updated Name"
        assert db.get(User, ids[1]).display_name is None
    assert client.patch("/profile", headers=headers[0], json={"display_name": "X", "is_admin": True}).status_code == 422
    response = client.post("/requests", headers=headers[0], json={"request": "under $2500 and at least 2 beds"})
    assert response.status_code == 200, response.text
    assert response.json()["constraints"]["rent_lt"] == 2500 and response.json()["constraints"]["min_beds"] == 2
    assert response.json()["priorities"] == {}
    assert client.post("/requests", headers=headers[0], json={"request": "invent unsafe neighborhood rankings"}).status_code == 422


def test_property_fee_patch_archive_restore_and_quota_preservation(api):
    client, _, headers, _, _ = api
    prop = save(api, monthly_rent=2000, square_feet=1000)
    response = client.patch("/properties/" + prop["id"], headers=headers[0], json={
        "fees": {"parking": 100, "utilities": 50, "pet_fee": 10, "renters_insurance": 20, "other": 0}})
    assert response.status_code == 200
    assert response.json()["fees"]["parking"] == 100
    ranked = client.post("/ranking", headers=headers[0], json={}).json()["ranked"]
    assert ranked[0]["monthly_total"] == 2180
    assert ranked[0]["fees_complete"] is True
    assert client.patch("/properties/" + prop["id"], headers=headers[0], json={"fees": {"parking": -1}}).status_code == 422
    assert client.patch("/properties/" + prop["id"], headers=headers[1], json={"fees": {"parking": 1}}).status_code == 404
    response = client.post("/properties/" + prop["id"] + "/archive", headers=headers[0], json={})
    assert response.status_code == 200 and response.json()["is_archived"] is True
    assert client.get("/entitlements", headers=headers[0]).json()["usage"]["properties"] == 1
    assert client.post("/ranking", headers=headers[0], json={}).json()["ranked"] == []
    assert client.post("/properties/" + prop["id"] + "/restore", headers=headers[1], json={}).status_code == 404
    response = client.post("/properties/" + prop["id"] + "/restore", headers=headers[0], json={})
    assert response.status_code == 200 and response.json()["is_archived"] is False
    assert client.post("/ranking", headers=headers[0], json={}).json()["ranked"][0]["monthly_total"] == 2180


@pytest.mark.parametrize("path", ["advisor", "enrichment", "commute", "negotiation", "analytics", "reports"])
def test_paid_endpoints_require_entitlement(api, path):
    client, _, headers, _, _ = api
    prop = save(api)
    result = client.post("/" + path, headers=headers[0], json={
        "property_ids": [prop["id"]], "idempotency_key": path, "destination": "Work"})
    assert result.status_code == 403


def test_paid_services_mock_and_shared_ai_quota(api, monkeypatch):
    paid(api)
    monkeypatch.setenv("NESTAI_QUOTA_PREMIUM_AI", "1")
    client, _, headers, _, _ = api
    prop = save(api)
    payload = {"property_ids": [prop["id"]], "idempotency_key": "advisor"}
    response = client.post("/advisor", headers=headers[0], json=payload)
    assert response.status_code == 200 and response.json()["mock"] is True
    assert client.post("/negotiation", headers=headers[0], json={**payload, "idempotency_key": "negotiation"}).status_code == 429
    for path in ("enrichment", "commute"):
        response = client.post("/" + path, headers=headers[0], json={
            **payload, "idempotency_key": path, "destination": "Work"})
        assert response.status_code == 200 and response.json()["mock"] is True
    assert client.post("/analytics", headers=headers[0], json={**payload, "idempotency_key": "analytics"}).status_code == 403


def test_provider_failure_rolls_back_quota(api, monkeypatch):
    paid(api)
    monkeypatch.setenv("NESTAI_PROVIDER_MODE", "live")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client, factory, headers, ids, _ = api
    prop = save(api)
    response = client.post("/advisor", headers=headers[0], json={
        "property_ids": [prop["id"]], "idempotency_key": "failure"})
    assert response.status_code == 503
    with factory() as db:
        assert not db.query(MonthlyUsage).filter_by(user_id=ids[0], metric="ai").first()


def test_month_rollover_does_not_reset_legacy_credits(api):
    client, factory, headers, ids, _ = api
    with factory() as db:
        db.add(MonthlyUsage(user_id=ids[0], period="2000-01", metric="analyses", count=999))
        db.commit()
    response = client.post("/analyses", headers=headers[0], json={
        "kind": "apartment", "text": APARTMENT_TEXT, "idempotency_key": "new-month"})
    assert response.status_code == 200
    assert client.get("/entitlements", headers=headers[0]).json()["usage"]["analyses"] == 1
    with factory() as db:
        assert db.get(MonthlyUsage, (ids[0], "2000-01", "analyses")).count == 999


def test_live_commute_and_enrichment_mocked_transport_persist_verified_fields(api, monkeypatch):
    paid(api)
    client, _, headers, _, _ = api
    prop = save(api)
    monkeypatch.setenv("NESTAI_PROVIDER_MODE", "live")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "testing-placeholder")
    payload = {"property_ids": [prop["id"]], "idempotency_key": "live-transport", "destination": "Work"}
    with patch.object(providers, "request_json", return_value={
        "status": "OK", "routes": [{"legs": [{"duration": {"value": 600}, "distance": {"value": 3000}}]}]}):
        result = client.post("/commute", headers=headers[0], json=payload)
    assert result.status_code == 200 and result.json()["mock"] is False
    assert client.get("/properties", headers=headers[0]).json()["properties"][0]["parsed"]["commute_transit_min"] == 10
    assert client.post("/ranking", headers=headers[0], json={}).json()["ranked"][0]["commute_minutes"] == 10
    with patch.object(providers, "request_json", return_value={"places": [{"id": "test-place"}]}):
        result = client.post("/enrichment", headers=headers[0], json={**payload, "idempotency_key": "places"})
    assert result.status_code == 200
    assert client.get("/properties", headers=headers[0]).json()["properties"][0]["parsed"]["enrichment"]["places"][0]["id"] == "test-place"
    # This is mocked HTTP transport, not a live Google validation.


def test_live_ai_transport_uses_backend_secret_and_redacts_errors(api, monkeypatch):
    paid(api)
    monkeypatch.setenv("NESTAI_PROVIDER_MODE", "live")
    monkeypatch.setenv("OPENAI_API_KEY", "testing-placeholder")
    client, _, headers, _, _ = api
    prop = save(api)
    with patch.object(providers, "request_json", return_value={"choices": [{"message": {"content": "Confirmed tradeoffs"}}]}) as transport:
        result = client.post("/advisor", headers=headers[0], json={"property_ids": [prop["id"]], "idempotency_key": "transport"})
    assert result.status_code == 200 and result.json()["answer"] == "Confirmed tradeoffs"
    assert transport.call_args.kwargs["headers"]["Authorization"].split()[-1] == "testing-placeholder"
    assert "testing-placeholder" not in result.text


def test_mock_mode_is_rejected_in_production(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("NESTAI_PROVIDER_MODE", "mock")
    get_settings.cache_clear()
    try:
        with pytest.raises(Exception) as result:
            providers.mode()
        assert result.value.status_code == 503
    finally:
        get_settings.cache_clear()


def test_csv_numeric_columns_and_formula_injection(api):
    paid(api)
    client, _, headers, _, _ = api
    prop = save(api, property_title="  =CMD()", address="+formula", units=[
        {"id": "0012", "beds": "2", "baths": "1.5", "unit_price": "$2,500", "unit_sqft": "1,000"},
        {"id": "@attack", "beds": "=bad", "price": "-not-numeric"}])
    response = client.post("/exports", headers=headers[0], json={"scope": "units", "property_ids": [prop["id"]]})
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["unit_id"] == "0012"
    assert float(rows[0]["rent"]) == 2500 and float(rows[0]["square_feet"]) == 1000
    assert rows[1]["unit_id"] == "'@attack" and rows[1]["beds"] == "" and rows[1]["rent"] == ""
    response = client.post("/exports", headers=headers[0], json={"property_ids": [prop["id"]]})
    assert "'  =CMD()" in response.text and "'+formula" in response.text
    assert client.post("/exports", headers=headers[1], json={"property_ids": [prop["id"]]}).status_code == 403


def test_exports_share_ui_filtered_ranked_set(api):
    paid(api)
    client, _, headers, _, _ = api
    prop = save(api, units=[
        {"id": "0012", "price": 2000, "sqft": 900, "beds_num": 2, "baths_num": 1.5},
        {"id": "0013", "price": 3500, "sqft": 1000, "beds_num": 2, "baths_num": 2},
    ])
    query = {"property_ids": [prop["id"]], "constraints": {"rent_lte": 2500}, "priorities": {"price": 1}}
    ui = client.post("/ranking", headers=headers[0], json=query).json()["ranked"]
    export = client.post("/exports", headers=headers[0], json={**query, "scope": "units"})
    exported = list(csv.DictReader(io.StringIO(export.text)))
    assert [row["unit_id"] for row in exported] == [row["unit_id"] for row in ui] == ["0012"]
    json_export = client.post("/exports", headers=headers[0], json={**query, "scope": "units", "format": "json"}).json()
    assert json_export == ui
    assert all("units" not in row for row in json_export)


def test_premium_and_plus_reports_use_consistent_snapshot_levels(api):
    paid(api)
    client, _, headers, _, _ = api
    prop = save(api, monthly_rent=2000, square_feet=1000, bedrooms=2)
    payload = {"property_ids": [prop["id"]], "idempotency_key": "premium-report"}
    premium = client.post("/reports", headers=headers[0], json=payload).json()
    premium_snapshot = json.loads(premium["content"])
    assert premium_snapshot["report_level"] == "premium" and "analytics" not in premium_snapshot
    paid(api, "premium_plus")
    plus = client.post("/reports", headers=headers[0], json={**payload, "idempotency_key": "plus-report"}).json()
    snapshot = json.loads(plus["content"])
    assert snapshot["report_level"] == "plus" and snapshot["analytics"]["sensitivity"]
    assert snapshot["analytics"]["baseline"] == snapshot["comparison"]
    assert "components" in snapshot["comparison"]["ranked"][0]
    assert "monthly_total" in snapshot["comparison"]["ranked"][0]


def test_ranking_reports_download_and_plus_sensitivity(api):
    paid(api, "premium_plus")
    client, _, headers, _, _ = api
    prop = save(api, address="Main St", monthly_rent=2000, square_feet=1000, bedrooms=2)
    payload = {"property_ids": [prop["id"]], "idempotency_key": "report", "priorities": {"price": 1}}
    ranking = client.post("/ranking", headers=headers[0], json={"priorities": {"price": 1}}).json()
    assert ranking["ranked"][0]["score"] == 50
    assert ranking["ranked"][0]["components"]["price"]["known"] is True
    report = client.post("/reports", headers=headers[0], json=payload)
    assert report.status_code == 200, report.text
    assert client.post("/reports", headers=headers[0], json=payload).json() == report.json()
    download = client.get(report.json()["download_url"], headers=headers[0])
    assert download.status_code == 200 and download.text == report.json()["content"]
    assert client.get(report.json()["download_url"], headers=headers[1]).status_code == 403
    response = client.post("/analytics", headers=headers[0], json={**payload, "idempotency_key": "sensitivity"})
    assert response.status_code == 200 and len(response.json()["sensitivity"]) == 1


def test_shared_constraints_fractional_baths_and_transit_provenance(api):
    client, _, headers, _, _ = api
    save(api, units=[
        {"id": "0012", "unit_price": "$2,000", "unit_sqft": "900", "beds": 2, "baths": 1.5,
         "metro_min": 8, "metro_travel_mode": "walk", "pets_policy": "Pets allowed"},
        {"id": "0013", "unit_price": "$2,000", "unit_sqft": "900", "beds": 2, "baths": 1,
         "metro_min": 5, "metro_travel_mode": "drive", "pets_policy": "unknown"},
    ])
    response = client.post("/ranking", headers=headers[0], json={
        "constraints": {"rent_lte": 2000, "min_baths": 1.5, "max_transit_walk_minutes": 10,
                        "pet_friendly": True}, "priorities": {"price": 1, "space": 1}})
    assert response.status_code == 200, response.text
    ranked = response.json()["ranked"]
    assert len(ranked) == 1 and ranked[0]["unit"] == "0012" and ranked[0]["baths_num"] == 1.5
    assert response.json()["method"] == "shared_decision"
    assert client.post("/ranking", headers=headers[0], json={"constraints": {"unsupported": 1}}).status_code == 422


def test_legacy_credits_and_referrals_unchanged(api):
    client, factory, headers, ids, _ = api
    with factory() as db:
        db.add(CreditBalance(user_id=ids[0], credits_remaining=87, credits_purchased=100))
        db.add(CreditTransaction(user_id=ids[0], transaction_type="grant", delta=87, balance_after=87, reason="legacy grant"))
        db.add(Referral(referrer_user_id=ids[0], referred_email="legacy@example.com", status="converted", reward_cents=500))
        db.commit()
    client.post("/analyses", headers=headers[0], json={"kind": "apartment", "text": APARTMENT_TEXT, "idempotency_key": "credit"})
    with factory() as db:
        assert db.query(CreditBalance).one().credits_remaining == 87
        assert db.query(CreditTransaction).one().delta == 87
        assert db.query(Referral).one().reward_cents == 500


def stripe_signature(raw, secret):
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), str(timestamp).encode() + b"." + raw, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_stripe_unconfigured_does_not_crash_and_no_fake_activation(api, monkeypatch):
    client, _, headers, _, _ = api
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert client.get("/health").status_code == 200
    response = client.post("/billing/checkout", headers=headers[0], json={"plan": "premium", "idempotency_key": "checkout"})
    assert response.status_code == 503
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "local-testing-only")
    assert client.post("/billing/webhook", content=b'{"event_type":"payment_succeeded"}',
                       headers={"X-NestAI-Signature": "fake"}).status_code == 400
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "free"


def test_stripe_checkout_uses_configured_price_without_invention(api, monkeypatch):
    client, factory, headers, ids, _ = api
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_PREMIUM_PRICE_ID", "price_configured")
    price = {"id": "price_configured", "active": True, "type": "recurring", "unit_amount": 1234, "currency": "usd", "recurring": {"interval": "month"}}
    with patch("stripe.Price.retrieve", return_value=price), patch("stripe.Customer.create", return_value={"id": "cus_test"}), patch(
        "stripe.checkout.Session.create", return_value={"id": "cs_test", "url": "https://checkout.stripe.com/test"}) as create:
        response = client.post("/billing/checkout", headers=headers[0], json={
            "plan": "premium", "idempotency_key": "checkout", "trial_consent": True, "payment_method_confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["price"]["amount_cents"] == 1234
    assert create.call_args.kwargs["line_items"][0]["price"] == "price_configured"
    assert create.call_args.kwargs["subscription_data"]["trial_period_days"] == 7
    with factory() as db:
        assert db.get(User, ids[0]).active_plan == "free"


def test_stripe_product_resolution_sdk_objects_and_trial_reuse(api, monkeypatch):
    import stripe
    client, factory, headers, ids, _ = api
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.delenv("STRIPE_PREMIUM_PRICE_ID", raising=False)
    monkeypatch.setenv("STRIPE_PREMIUM_PRODUCT_ID", "prod_test")
    with factory() as db:
        db.get(User, ids[0]).trial_used = True
        db.commit()
    product = stripe.StripeObject.construct_from({"default_price": "price_test"}, None)
    price = stripe.StripeObject.construct_from({"id": "price_test", "active": True, "type": "recurring", "unit_amount": 9876, "currency": "usd"}, None)
    with patch("stripe.Product.retrieve", return_value=product), patch("stripe.Price.retrieve", return_value=price), patch(
        "stripe.Customer.create", return_value={"id": "cus_test"}), patch(
        "stripe.checkout.Session.create", return_value={"id": "cs_test", "url": "https://checkout.stripe.com/test"}) as checkout:
        response = client.post("/billing/checkout", headers=headers[0], json={
            "plan": "premium", "trial_consent": True, "payment_method_confirmed": True, "idempotency_key": "reused"})
    assert response.status_code == 200 and response.json()["trial_days"] == 0
    assert "trial_period_days" not in checkout.call_args.kwargs["subscription_data"]


def test_open_checkout_reused_instead_of_multiple_trials(api, monkeypatch):
    client, _, headers, _, _ = api
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_PREMIUM_PRICE_ID", "price_test")
    price = {"id": "price_test", "active": True, "type": "recurring", "unit_amount": 1234}
    payload = {"plan": "premium", "idempotency_key": "first", "trial_consent": True, "payment_method_confirmed": True}
    with patch("stripe.Price.retrieve", return_value=price), patch("stripe.Customer.create", return_value={"id": "cus_test"}), patch(
        "stripe.checkout.Session.create", return_value={"id": "cs_test", "url": "https://checkout.stripe.com/test"}) as create, patch(
        "stripe.checkout.Session.retrieve", return_value={"id": "cs_test", "status": "open"}):
        first = client.post("/billing/checkout", headers=headers[0], json=payload)
        second = client.post("/billing/checkout", headers=headers[0], json={**payload, "idempotency_key": "second"})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and create.call_count == 1


def test_billing_portal_and_live_billing_opt_in(api, monkeypatch):
    client, factory, headers, ids, _ = api
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_placeholder")
    monkeypatch.delenv("STRIPE_ALLOW_LIVE", raising=False)
    assert client.post("/billing/portal", headers=headers[0]).status_code == 503
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    assert client.post("/billing/portal", headers=headers[0]).status_code == 409
    with factory() as db:
        db.get(User, ids[0]).stripe_customer_id = "cus_portal"
        db.commit()
    with patch("stripe.billing_portal.Session.create", return_value={"url": "https://billing.stripe.com/test"}):
        response = client.post("/billing/portal", headers=headers[0])
    assert response.status_code == 200 and response.json()["portal_url"] == "https://billing.stripe.com/test"


def test_verified_webhook_idempotency_lifecycle_and_out_of_order(api, monkeypatch):
    client, factory, headers, ids, _ = api
    secret = "local-testing-only"
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_PREMIUM_PRICE_ID", "price_test")
    with factory() as db:
        user = db.get(User, ids[0])
        user.stripe_customer_id = "cus_test"
        db.commit()
    price = {"id": "price_test", "active": True, "type": "recurring"}
    sub = {"id": "sub_test", "customer": "cus_test", "metadata": {"nestai_user_id": str(ids[0]), "nestai_plan": "premium"},
           "items": {"data": [{"price": {"id": "price_test"}}]}, "status": "trialing", "trial_end": int(time.time()) + 604800}
    def send(event_id, event_type):
        raw = json.dumps({"id": event_id, "object": "event", "type": event_type, "livemode": False,
                          "data": {"object": {"id": "sub_test"}}}).encode()
        with patch("stripe.Subscription.retrieve", return_value=sub), patch("stripe.Price.retrieve", return_value=price):
            return client.post("/billing/webhook", content=raw, headers={"Stripe-Signature": stripe_signature(raw, secret)})
    response = send("evt_first", "customer.subscription.created")
    assert response.status_code == 200, response.text
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "premium"
    assert send("evt_first", "customer.subscription.created").json()["duplicate"] is True
    sub["status"] = "past_due"
    assert send("evt_past_due", "customer.subscription.updated").status_code == 200
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "free"
    sub["status"] = "canceled"
    assert send("evt_deleted", "customer.subscription.deleted").status_code == 200
    # A stale created event still reads canceled current state.
    assert send("evt_stale", "customer.subscription.created").status_code == 200
    assert client.get("/billing/status", headers=headers[0]).json()["subscription_status"] == "canceled"
    with factory() as db:
        assert db.get(User, ids[0]).trial_used is True
    sub["id"], sub["status"] = "sub_new", "active"
    assert send("evt_resubscribed", "customer.subscription.created").status_code == 200
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "premium"
    sub["id"], sub["status"] = "sub_test", "canceled"
    assert send("evt_old_subscription", "customer.subscription.deleted").json().get("ignored") is True
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "premium"


def test_postgres_concurrent_quota_and_idempotency(api, monkeypatch):
    client, factory, headers, ids, backend = api
    if backend != "postgres":
        pytest.skip("Row-lock concurrency validated only on PostgreSQL")
    monkeypatch.setenv("NESTAI_QUOTA_FREE_ANALYSES", "1")
    def run(key):
        return client.post("/analyses", headers=headers[0], json={"kind": "apartment", "text": APARTMENT_TEXT, "idempotency_key": key}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, ["one", "two"]))
    assert sorted(results) == [200, 429]
    successful = "one" if results[0] == 200 else "two"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(run, [successful, successful])) == [200, 200]
    with factory() as db:
        assert db.query(MonthlyUsage).filter_by(user_id=ids[0]).one().count == 1


def test_additive_migration_preserves_unowned_and_credits(monkeypatch):
    url = os.getenv("NESTAI_TEST_DATABASE_URL") or os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("NESTAI_TEST_DATABASE_URL not configured")
    from alembic import command
    from alembic.config import Config
    admin = create_engine(url)
    schema = "migration_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PGOPTIONS", f"-csearch_path={schema}")
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    try:
        command.upgrade(cfg, "ae05715be4e2")
        with admin.begin() as conn:
            conn.execute(text(f'SET search_path TO "{schema}"'))
            conn.execute(text("INSERT INTO users (email, hashed_password, referral_code) VALUES ('preserved@example.com', 'hash', 'preserved-code')"))
            conn.execute(text("INSERT INTO credit_balances (user_id, credits_remaining, credits_purchased) SELECT id, 88, 100 FROM users"))
            conn.execute(text("INSERT INTO properties (property_type, session_id, address) VALUES ('HOME_FOR_SALE', 'legacy-unowned', 'Never Claim Me')"))
        command.upgrade(cfg, "head")
        with admin.begin() as conn:
            conn.execute(text(f'SET search_path TO "{schema}"'))
            assert conn.execute(text("SELECT credits_remaining FROM credit_balances")).scalar() == 88
            assert conn.execute(text("SELECT user_id FROM properties WHERE session_id='legacy-unowned'")).scalar() is None
            assert conn.execute(text("SELECT count(*) FROM account_properties")).scalar() == 0
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0007_account_services"
        command.downgrade(cfg, "ae05715be4e2")
        with admin.begin() as conn:
            conn.execute(text(f'SET search_path TO "{schema}"'))
            assert conn.execute(text("SELECT count(*) FROM properties")).scalar() == 1
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
