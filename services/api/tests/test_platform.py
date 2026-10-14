"""Local tests use mocks; no test represents real provider/Stripe validation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
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
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models
from app.db.base import Base
from app.db.models.account import MonthlyUsage, AccountProperty
from app.db.models.credits import CreditBalance, CreditTransaction
from app.db.models.referral import Referral
from app.db.models.feedback import FeedbackReport
from app.db.models.property import Property
from app.db.models.home_details import HomeDetails
from app.db.models.comparison import Comparison
from app.db.models.building import Building
from app.db.models.unit import Unit
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


def test_trusted_beta_grant_preserved_without_stripe_and_expiry_enforced(api):
    client, factory, headers, ids, _ = api
    with factory() as db:
        user = db.get(User, ids[0])
        user.beta_tester = True
        user.beta_approved_at = datetime.now(timezone.utc)
        user.active_plan = user.tier = "beta"
        user.subscription_status = "pending_payment"
        user.beta_limits = {"properties": 3, "ai": 2}
        db.add(CreditBalance(user_id=user.id, credits_remaining=87))
        db.commit()
    result = client.get("/entitlements", headers=headers[0]).json()
    assert result["plan"] == "beta" and result["entitlement_source"] == "trusted_beta_grant"
    assert result["limits"]["properties"] == 3 and result["features"]["advisor"] is True
    prop = save(api)
    response = client.post("/advisor", headers=headers[0], json={
        "property_ids": [prop["id"]], "idempotency_key": "beta-advisor"})
    assert response.status_code == 200
    with factory() as db:
        assert db.query(CreditBalance).one().credits_remaining == 87
        assert db.get(User, ids[0]).stripe_customer_id is None
        db.get(User, ids[0]).beta_access_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "free"
    assert client.post("/advisor", headers=headers[0], json={
        "property_ids": [prop["id"]], "idempotency_key": "beta-expired"}).status_code == 403


def test_beta_string_without_grant_and_free_advanced_gates(api):
    client, factory, headers, ids, _ = api
    with factory() as db:
        db.get(User, ids[0]).active_plan = "beta"
        db.commit()
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "free"
    assert client.post("/requests", headers=headers[0], json={"request": "under $2500"}).status_code == 403
    assert client.post("/ranking", headers=headers[0], json={"priorities": {"price": 1}}).status_code == 403
    assert client.post("/ranking", headers=headers[0], json={}).status_code == 200


def test_admin_beta_grant_configuration_is_owned_and_payment_independent(api):
    client, factory, headers, ids, _ = api
    with factory() as db:
        db.get(User, ids[1]).is_admin = True
        db.commit()
    endpoint = f"/admin/users/{ids[0]}/beta-access"
    payload = {"active": True, "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
               "limits": {"analyses": 2}, "features": {"analytics": True}}
    assert client.patch(endpoint, headers=headers[0], json=payload).status_code == 403
    response = client.patch(endpoint, headers=headers[1], json=payload)
    assert response.status_code == 200, response.text
    entitlement = client.get("/entitlements", headers=headers[0]).json()
    assert entitlement["plan"] == "beta" and entitlement["limits"]["analyses"] == 2
    assert entitlement["features"]["analytics"] is True
    assert client.patch(endpoint, headers=headers[1], json={**payload, "limits": {"ai": -1}}).status_code == 422
    assert client.patch(endpoint, headers=headers[1], json={**payload, "limits": {"ai": True}}).status_code == 422
    assert client.patch(endpoint, headers=headers[1], json={"active": False}).status_code == 200
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "free"


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


def test_actual_avalon_cortland_fixture_api_29_13_and_dedup42(api):
    client, _, headers, _, _ = api
    root = Path(__file__).resolve().parents[3]
    ids = []
    for index, count in ((1, 29), (2, 13)):
        text_value = (root / f"legacy/streamlit/data/app_listing_{index}.txt").read_text()
        analysis = client.post("/analyses", headers=headers[0], json={
            "kind": "apartment", "text": text_value, "idempotency_key": f"fixture-analysis-{index}"})
        assert analysis.status_code == 200, analysis.text
        assert len(analysis.json()["parsed"]["units"]) == count
        payload = {"kind": "apartment", "parsed": analysis.json()["parsed"],
                   "external_id": f"fixture-{index}", "idempotency_key": f"fixture-save-{index}"}
        saved = client.post("/properties", headers=headers[0], json=payload)
        assert saved.status_code == 200, saved.text
        assert len(saved.json()["units"]) == count
        ids.append(saved.json()["id"])
        repeated = client.post("/properties", headers=headers[0], json={**payload, "idempotency_key": f"fixture-resave-{index}"})
        assert repeated.status_code == 200 and repeated.json()["id"] == saved.json()["id"]
    assert len(client.get("/properties", headers=headers[0]).json()["properties"]) == 2
    ranked = client.post("/ranking", headers=headers[0], json={"property_ids": ids}).json()["ranked"]
    assert len(ranked) == len({(row["property_id"], row["unit_id"]) for row in ranked}) == 42
    paid(api)
    exported = client.post("/exports", headers=headers[0], json={"property_ids": ids, "scope": "units"})
    csv_rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(csv_rows) == len({(row["property_id"], row["unit_id"]) for row in csv_rows}) == 42
    with patch.dict(os.environ, {"NESTAI_PROVIDER_MODE": "live", "OPENAI_API_KEY": "testing-placeholder"}), patch.object(
        providers, "request_json", return_value={"choices": [{"message": {"content": "Grounded fixture comparison"}}]}
    ) as transport:
        advised = client.post("/advisor", headers=headers[0], json={
            "property_ids": ids, "idempotency_key": "fixture-advisor", "question": "Compare these saved options"})
    assert advised.status_code == 200, advised.text
    context = json.loads(transport.call_args.kwargs["json"]["messages"][1]["content"])
    assert len(context["grounding"]["ranked"]) == 42
    assert {citation["property_id"] for citation in advised.json()["citations"]} == set(ids)


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
    paid(api)
    response = client.post("/requests", headers=headers[0], json={"request": "under $2500 and at least 2 beds"})
    assert response.status_code == 200, response.text
    assert response.json()["constraints"]["rent_lt"] == 2500 and response.json()["constraints"]["min_beds"] == 2
    assert response.json()["priorities"] == {}
    assert client.post("/requests", headers=headers[0], json={"request": "invent unsafe neighborhood rankings"}).status_code == 422


def test_natural_requests_keep_explicit_priorities_separate_from_constraints(api):
    paid(api)
    client, _, headers, _, _ = api
    response = client.post("/requests", headers=headers[0], json={
        "request": "under $2500 and at least 2 beds and prioritize commute over price"})
    assert response.status_code == 200, response.text
    parsed = response.json()
    assert parsed["constraints"]["rent_lt"] == 2500
    assert parsed["constraints"]["min_beds"] == 2
    assert parsed["priorities"]["commute"] == 3 and parsed["priorities"]["price"] == 1
    assert parsed["priorities"]["space"] == 1
    for request in ("space is more important than price", "prioritize space over price"):
        only_priority = client.post("/requests", headers=headers[0], json={"request": request})
        assert only_priority.status_code == 200, only_priority.text
        assert only_priority.json()["priorities"]["space"] == 3
    for request in ("prioritize commute over commute", "prioritize price and prioritize commute over price",
                    "prioritize unverified safety", "under $2500 and invent priorities"):
        assert client.post("/requests", headers=headers[0], json={"request": request}).status_code == 422
    assert client.post("/requests", headers=headers[1], json={
        "request": "prioritize space over price"}).status_code == 403


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
    assert client.get("/entitlements", headers=headers[0]).json()["usage"]["properties"] == 0
    assert client.post("/ranking", headers=headers[0], json={}).json()["ranked"] == []
    assert client.post("/properties/" + prop["id"] + "/restore", headers=headers[1], json={}).status_code == 404
    response = client.post("/properties/" + prop["id"] + "/restore", headers=headers[0], json={})
    assert response.status_code == 200 and response.json()["is_archived"] is False
    assert client.post("/ranking", headers=headers[0], json={}).json()["ranked"][0]["monthly_total"] == 2180


def test_active_property_limit_archive_and_implicit_restore(api, monkeypatch):
    client, _, headers, _, _ = api
    first = save(api, "first", units=[{"id": "0012", "price": 2000}])
    second = save(api, "second")
    assert client.post(f"/properties/{first['id']}/archive", headers=headers[0], json={}).status_code == 200
    assert client.post(f"/properties/{first['id']}/archive", headers=headers[0], json={}).status_code == 200
    save(api, "replacement")
    payload = {"kind": "apartment", "external_id": "first", "idempotency_key": "update-archived",
               "parsed": {"address": "Updated"}}
    updated = client.post("/properties", headers=headers[0], json=payload)
    assert updated.status_code == 200 and updated.json()["is_archived"] is True
    assert updated.json()["units"][0]["id"] == "0012"
    assert client.post("/properties", headers=headers[0], json={
        **payload, "idempotency_key": "implicit-restore", "parsed": {"is_archived": False}}).status_code == 429
    assert client.post("/properties", headers=headers[0], json={
        "kind": "home", "external_id": "third", "idempotency_key": "third", "parsed": {"address": "Third"}}).status_code == 429
    assert client.post("/properties", headers=headers[0], json={
        **payload, "idempotency_key": "invalid-archive", "parsed": {"is_archived": "false"}}).status_code == 422
    assert client.post(f"/properties/{first['id']}/restore", headers=headers[0], json={}).status_code == 429
    assert client.post("/properties", headers=headers[0], json={
        **payload, "idempotency_key": "paid-implicit", "parsed": {"is_archived": False}}).status_code == 429
    assert client.delete("/properties/" + second["id"], headers=headers[0]).status_code == 200
    restored = client.post(f"/properties/{first['id']}/restore", headers=headers[0], json={})
    assert restored.status_code == 200 and restored.json()["is_archived"] is False
    assert client.post(f"/properties/{first['id']}/restore", headers=headers[0], json={}).status_code == 200
    assert client.get("/entitlements", headers=headers[0]).json()["usage"]["properties"] == 2


def test_feedback_persists_admin_table_with_owned_idempotency(api):
    client, factory, headers, ids, _ = api
    payload = {"idempotency_key": "feedback", "category": "bug", "title": "Ranking issue",
               "description": "A reproducible issue", "route_or_screen": "Apartment Search"}
    response = client.post("/feedback", headers=headers[0], json=payload)
    assert response.status_code == 200, response.text
    assert client.post("/feedback", headers=headers[0], json=payload).json() == response.json()
    with factory() as db:
        report = db.query(FeedbackReport).one()
        assert report.user_id == ids[0] and report.contact_email is None and report.status == "new"
        db.get(User, ids[1]).is_admin = True
        db.commit()
    assert client.get("/admin/feedback", headers=headers[0]).status_code == 403
    admin_response = client.get("/admin/feedback", headers=headers[1])
    assert admin_response.status_code == 200 and admin_response.json()[0]["id"] == response.json()["id"]
    assert client.post("/feedback", headers=headers[0], json={**payload, "user_id": ids[1]}).status_code == 422


def test_backend_email_suppression_no_transport_calls(monkeypatch):
    from email_service import send_password_reset_email
    monkeypatch.setenv("NESTAI_DISABLE_EMAIL", "true")
    with patch("resend.Emails.send") as send:
        assert send_password_reset_email("unused@example.com", "https://example.invalid/reset") is False
    send.assert_not_called()


def test_password_reset_provider_failure_does_not_enumerate_accounts(api, monkeypatch):
    client, _, _, _, _ = api
    from app.core.config import get_settings
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    get_settings.cache_clear()
    try:
        with patch("app.auth.router.send_password_reset_email", side_effect=RuntimeError("private-provider-error")):
            response = client.post("/auth/forgot-password", json={"email": "user1@example.com"})
            unknown = client.post("/auth/forgot-password", json={"email": "unknown@example.com"})
        assert response.status_code == unknown.status_code == 200
        assert response.json() == unknown.json()
        assert "private-provider-error" not in response.text and "has been sent" not in response.text
    finally:
        get_settings.cache_clear()


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
    monkeypatch.setenv("WALKSCORE_API_KEY", "testing-placeholder")
    payload = {"property_ids": [prop["id"]], "idempotency_key": "live-transport", "destination": "Work"}
    with patch.object(providers, "request_json", return_value={
        "status": "OK", "routes": [{"legs": [{"duration": {"value": 600}, "distance": {"value": 3000}}]}]}):
        result = client.post("/commute", headers=headers[0], json=payload)
    assert result.status_code == 200 and result.json()["mock"] is False
    assert client.get("/properties", headers=headers[0]).json()["properties"][0]["parsed"]["commute_transit_min"] == 10
    assert client.post("/ranking", headers=headers[0], json={}).json()["ranked"][0]["commute_minutes"] == 10
    geocode = {"status": "OK", "results": [{"types": ["street_address"], "place_id": "confirmed-place",
                 "formatted_address": "123 Main St", "geometry": {"location": {"lat": 38.9, "lng": -77.1}}}]}
    nearby = [{"places": [{"id": category, "location": {"latitude": 38.91, "longitude": -77.11}}]}
              for category in ("groceries", "fitness", "transit")]
    walking = {"status": "OK", "routes": [{"legs": [{"duration": {"value": 300}, "distance": {"value": 500}}]}]}
    with patch.object(providers, "request_json", side_effect=[
        geocode, *nearby, walking, {"status": 1, "walkscore": 80, "ws_link": "https://www.walkscore.com/score/test"}
    ]):
        result = client.post("/enrichment", headers=headers[0], json={**payload, "idempotency_key": "places"})
    assert result.status_code == 200, result.text
    stored = client.get("/properties", headers=headers[0]).json()["properties"][0]["parsed"]
    assert stored["enrichment"]["categories"]["groceries"][0]["id"] == "groceries"
    assert stored["walk_score"] == 80 and stored["latitude"] == 38.9 and stored["metro_min"] == 5
    ranked = client.post("/ranking", headers=headers[0], json={}).json()["ranked"][0]
    assert ranked["commute_minutes"] == 10 and ranked["metro_travel_mode"] == "walk"
    assert ranked["components"]["walkability"]["value"] == 80
    with patch.object(providers, "request_json") as network:
        cached = client.post("/enrichment", headers=headers[0], json={**payload, "idempotency_key": "places-cached"})
    assert cached.status_code == 200 and cached.json()["cache_hit"] is True
    network.assert_not_called()
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
    request_body = transport.call_args.kwargs["json"]
    assert 0 < request_body["max_completion_tokens"] <= 2000
    context = json.loads(request_body["messages"][1]["content"])
    assert context["grounding"]["ranked"][0]["property_id"] == prop["id"]
    assert result.json()["citations"][0]["property_id"] == prop["id"]


def test_neighborhood_no_results_is_failure_without_quota_or_persistence(api, monkeypatch):
    paid(api)
    client, factory, headers, ids, _ = api
    prop = save(api)
    monkeypatch.setenv("NESTAI_PROVIDER_MODE", "live")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "testing-placeholder")
    with patch.object(providers, "request_json", return_value={"status": "ZERO_RESULTS", "results": []}):
        result = client.post("/enrichment", headers=headers[0], json={
            "property_ids": [prop["id"]], "idempotency_key": "no-location"})
    assert result.status_code == 502 and "testing-placeholder" not in result.text
    with factory() as db:
        assert not db.query(MonthlyUsage).filter_by(user_id=ids[0], metric="enrichment").first()
    assert "enrichment" not in client.get("/properties", headers=headers[0]).json()["properties"][0]["parsed"]


def test_advisor_only_deterministic_grounding_no_adversarial_raw_listing(api, monkeypatch):
    paid(api)
    client, _, headers, _, _ = api
    first = save(api, monthly_rent=2000, square_feet=1000, bedrooms=2, description="RAW_PROMPT_ATTACK",
                 enrichment={"status": "complete", "instruction": "FAKE_PROVIDER_ATTACK"})
    second = save(api, key="second-advice", monthly_rent=2400, square_feet=1100, bedrooms=2)
    client.put("/profile", headers=headers[0], json={"preferences": {"pets": "Yes", "max_budget": 2500}})
    monkeypatch.setenv("NESTAI_PROVIDER_MODE", "live")
    monkeypatch.setenv("OPENAI_API_KEY", "testing-placeholder")
    with patch.object(providers, "request_json", return_value={"choices": [{"message": {"content": "Grounded answer"}}]}) as transport:
        result = client.post("/advisor", headers=headers[0], json={
            "property_ids": [first["id"], second["id"]], "question": "Explain tradeoffs", "idempotency_key": "grounded"})
    assert result.status_code == 200
    body = transport.call_args.kwargs["json"]
    assert "RAW_PROMPT_ATTACK" not in body["messages"][1]["content"]
    assert "FAKE_PROVIDER_ATTACK" not in body["messages"][1]["content"]
    context = json.loads(body["messages"][1]["content"])["grounding"]
    assert context["profile"]["pets"] == "Yes"
    assert context["ranked"][0]["comparison"]["deltas"]["price"] is not None
    assert {citation["property_id"] for citation in result.json()["citations"]} == {first["id"], second["id"]}
    assert "untrusted data" in body["messages"][0]["content"]


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


def test_listing_exports_preserve_every_mixed_ranked_option(api):
    paid(api)
    client, _, headers, _, _ = api
    prop = save(api, units=[
        {"id": "0012", "price": 2000, "sqft": 900},
        {"id": "0013", "price": 2300, "sqft": 1000},
        {"id": "excluded", "price": 3500, "sqft": 500},
    ])
    home = client.post("/properties", headers=headers[0], json={
        "kind": "home", "external_id": "purchase", "idempotency_key": "purchase",
        "parsed": {"property_type": "HOME_FOR_SALE", "address": "Purchase Home",
                   "sale_price": 450000, "square_feet": 2000}}).json()
    rental = client.post("/properties", headers=headers[0], json={
        "kind": "rental_home", "external_id": "rental", "idempotency_key": "rental",
        "parsed": {"address": "Rental Home", "monthly_rent": 2100, "square_feet": 1000}}).json()
    query = {"property_ids": [prop["id"], home["id"], rental["id"]],
             "constraints": {"min_sqft": 800}, "priorities": {"price": 1}}
    ranked = client.post("/ranking", headers=headers[0], json=query).json()["ranked"]
    assert len(ranked) == 4
    response = client.post("/exports", headers=headers[0], json={**query, "scope": "listings"})
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [(row["property_id"], row["unit_id"] or None) for row in rows] == [
        (row["property_id"], row["unit_id"]) for row in ranked]
    assert [float(row["score"]) for row in rows] == [row["score"] for row in ranked]
    purchase = next(row for row in rows if row["property_id"] == home["id"])
    assert purchase["price_kind"] == "purchase" and float(purchase["price"]) == 450000
    assert purchase["monthly_total"] == ""
    assert next(row for row in rows if row["property_id"] == rental["id"])["price_kind"] == "rent"
    exported_json = client.post("/exports", headers=headers[0], json={
        **query, "scope": "listings", "format": "json"}).json()
    assert exported_json == ranked


@pytest.mark.parametrize("plan", ["premium", "premium_plus"])
def test_report_snapshots_only_include_ranked_properties_and_units(api, plan):
    paid(api, plan)
    client, _, headers, _, _ = api
    prop = save(api, units=[
        {"id": "0012", "price": 2000, "sqft": 900},
        {"id": "excluded", "price": 3500, "sqft": 1000},
        {"id": "archived-unit", "price": 1800, "sqft": 1000, "is_archived": True},
    ])
    excluded = save(api, "excluded-property", units=[{"id": "expensive", "price": 4000, "sqft": 900}])
    archived = save(api, "archived-property", is_archived=True, units=[{"id": "cheap", "price": 1700, "sqft": 900}])
    query = {"property_ids": [prop["id"], excluded["id"], archived["id"]],
             "constraints": {"rent_lte": 2500}, "priorities": {"price": 1}}
    ranked = client.post("/ranking", headers=headers[0], json=query).json()["ranked"]
    response = client.post("/reports", headers=headers[0], json={**query, "idempotency_key": "filtered-report"})
    assert response.status_code == 200, response.text
    snapshot = json.loads(response.json()["content"])
    assert snapshot["comparison"]["ranked"] == ranked
    assert [row["id"] for row in snapshot["properties"]] == [prop["id"]]
    assert [unit["id"] for unit in snapshot["properties"][0]["units"]] == ["0012"]
    assert [unit["id"] for unit in snapshot["properties"][0]["parsed"]["units"]] == ["0012"]
    saved = client.get("/properties", headers=headers[0]).json()["properties"]
    assert len(saved) == 3
    assert len(next(row for row in saved if row["id"] == prop["id"])["units"]) == 3


def test_report_property_and_unit_snapshots_follow_filtered_rank_order(api):
    paid(api)
    client, _, headers, _, _ = api
    first = save(api, "first-created", units=[
        {"id": "A-expensive", "price": 2600, "sqft": 1000},
        {"id": "Z-cheaper", "price": 2500, "sqft": 1000},
        {"id": "excluded", "price": 4000, "sqft": 1000},
    ])
    second = save(api, "second-created", units=[
        {"id": "A-expensive", "price": 1800, "sqft": 1000},
        {"id": "Z-cheaper", "price": 1700, "sqft": 1000},
    ])
    payload = {"property_ids": [first["id"], second["id"]], "constraints": {"rent_lte": 3000},
               "priorities": {"price": 1}, "idempotency_key": "ordered-report"}
    response = client.post("/reports", headers=headers[0], json=payload)
    assert response.status_code == 200, response.text
    snapshot = json.loads(response.json()["content"])
    ranked = snapshot["comparison"]["ranked"]
    assert [row["id"] for row in snapshot["properties"]] == list(dict.fromkeys(row["property_id"] for row in ranked))
    for record in snapshot["properties"]:
        expected = [row["unit_id"] for row in ranked if row["property_id"] == record["id"]]
        assert [unit["id"] for unit in record["units"]] == expected
        assert [unit["id"] for unit in record["parsed"]["units"]] == expected


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
    paid(api)
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


def test_audited_recovery_only_trusted_owned_records_and_snapshots(api):
    client, factory, headers, ids, _ = api
    with factory() as db:
        owned = Property(user_id=ids[0], property_type="HOME_FOR_SALE", address="Owned Home", sale_price=450000)
        db.add(owned)
        db.flush()
        db.add(HomeDetails(property_id=owned.id, walk_score=80, pets_policy="Pets allowed"))
        db.add(Property(user_id=None, session_id="ambiguous", property_type="HOME_FOR_SALE", address="Never Claim Me"))
        db.add(Property(user_id=ids[1], property_type="RENTAL_HOME", address="Other Account"))
        db.add(Comparison(user_id=ids[0], name="Owned snapshot", units_snapshot='[{"unit":"0012"}]'))
        db.add(Comparison(user_id=ids[1], name="Other snapshot", units_snapshot="private"))
        db.add(Comparison(user_id=None, name="Unowned snapshot", units_snapshot="unclaimed"))
        building = Building(building_key="shared-cache", building_name="Shared")
        db.add(building)
        db.flush()
        db.add(Unit(building_id=building.id, unit_number="0012", rent_price=1234))
        db.add(CreditBalance(user_id=ids[0], credits_remaining=87))
        db.commit()
    inventory = client.get("/recovery", headers=headers[0]).json()
    assert inventory["owned_legacy_properties"] == inventory["owned_comparison_snapshots"] == 1
    result = client.post("/recovery", headers=headers[0], json={"idempotency_key": "recover"})
    assert result.status_code == 200, result.text
    assert client.post("/recovery", headers=headers[0], json={"idempotency_key": "recover"}).json() == result.json()
    rows = client.get("/properties", headers=headers[0]).json()["properties"]
    assert len(rows) == 1 and rows[0]["parsed"]["address"] == "Owned Home"
    assert rows[0]["parsed"]["walk_score"] == 80 and rows[0]["units"] == []
    assert rows[0]["parsed"]["ownership_provenance"] == "existing_postgres_properties.user_id"
    ranked = client.post("/ranking", headers=headers[0], json={}).json()["ranked"]
    assert ranked[0]["price_num"] == 450000
    assert client.get("/properties", headers=headers[1]).json()["properties"] == []
    comparisons = client.get("/comparisons", headers=headers[0]).json()["comparisons"]
    assert len(comparisons) == 1 and comparisons[0]["units_snapshot"] == '[{"unit":"0012"}]'
    with factory() as db:
        assert db.query(Property).count() == 3 and db.query(Comparison).count() == 3
        assert db.query(Property).filter_by(user_id=None).one().address == "Never Claim Me"
        assert db.query(Unit).one().unit_number == "0012" and db.query(Building).count() == 1
        assert db.query(CreditBalance).one().credits_remaining == 87
    again = client.post("/recovery", headers=headers[0], json={"idempotency_key": "recover-again"}).json()
    assert again["recovered_property_ids"] == [] and len(again["already_recovered_property_ids"]) == 1


def test_recovery_preserves_existing_owned_data_above_current_caps(api):
    client, factory, headers, ids, _ = api
    with factory() as db:
        db.add_all([Property(user_id=ids[0], property_type="HOME_FOR_SALE", address=f"Owned {i}") for i in range(3)])
        db.commit()
    result = client.post("/recovery", headers=headers[0], json={"idempotency_key": "all-owned"})
    assert result.status_code == 200 and len(result.json()["recovered_property_ids"]) == 3
    assert client.get("/entitlements", headers=headers[0]).json()["usage"]["properties"] == 3
    assert client.post("/properties", headers=headers[0], json={
        "kind": "home", "parsed": {"address": "New"}, "idempotency_key": "new"}).status_code == 429


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


def test_portal_plan_change_targets_existing_subscription_without_activation(api, monkeypatch):
    client, factory, headers, ids, _ = api
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_PREMIUM_PLUS_PRICE_ID", "price_plus")
    with factory() as db:
        user = db.get(User, ids[0])
        user.stripe_customer_id = "cus_portal"
        user.stripe_subscription_id = "sub_portal"
        user.active_plan = user.tier = "premium"
        db.commit()
    sub = {"id": "sub_portal", "customer": "cus_portal", "status": "active",
           "items": {"data": [{"id": "si_portal", "price": {"id": "price_premium"}, "quantity": 1}]}}
    with patch("stripe.Subscription.retrieve", return_value=sub), patch(
        "stripe.Price.retrieve", return_value={"id": "price_plus", "active": True, "type": "recurring"}
    ), patch("stripe.billing_portal.Session.create", return_value={"url": "https://billing.stripe.com/confirm"}) as create:
        response = client.post("/billing/portal", headers=headers[0], json={"plan": "premium_plus"})
    assert response.status_code == 200, response.text
    flow = create.call_args.kwargs["flow_data"]
    assert flow["type"] == "subscription_update_confirm"
    assert flow["subscription_update_confirm"] == {
        "subscription": "sub_portal", "items": [{"id": "si_portal", "price": "price_plus", "quantity": 1}]}
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "premium"
    assert client.post("/billing/portal", headers=headers[0], json={"plan": "free"}).status_code == 422
    assert client.post("/billing/portal", headers=headers[0], json={"plan": "premium", "customer": "cus_other"}).status_code == 422
    assert client.post("/billing/portal", headers=headers[1], json={"plan": "premium_plus"}).status_code == 409
    sub["customer"] = "cus_other"
    with patch("stripe.Subscription.retrieve", return_value=sub), patch("stripe.billing_portal.Session.create") as create:
        assert client.post("/billing/portal", headers=headers[0], json={"plan": "premium_plus"}).status_code == 409
        create.assert_not_called()


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


def test_portal_price_changes_override_stale_metadata_and_preserve_data(api, monkeypatch):
    client, factory, headers, ids, _ = api
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "local-testing-only")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_PREMIUM_PRICE_ID", "price_premium")
    monkeypatch.setenv("STRIPE_PREMIUM_PLUS_PRICE_ID", "price_plus")
    prop = save(api)
    with factory() as db:
        user = db.get(User, ids[0])
        user.stripe_customer_id = "cus_portal"
        db.add(CreditBalance(user_id=user.id, credits_remaining=87))
        db.add(MonthlyUsage(user_id=user.id, period="2026-10", metric="analyses", count=4))
        db.commit()
    sub = {"id": "sub_portal", "customer": "cus_portal",
           "metadata": {"nestai_user_id": str(ids[0]), "nestai_plan": "premium"},
           "items": {"data": [{"price": {"id": "price_plus"}, "quantity": 1}]}, "status": "active"}

    def send(event_id):
        raw = json.dumps({"id": event_id, "type": "customer.subscription.updated", "livemode": False,
                          "data": {"object": {"id": sub["id"], "customer": sub["customer"]}}}).encode()
        def price(price_id, **kwargs):
            return {"id": price_id, "active": True, "type": "recurring"}
        with patch("stripe.Subscription.retrieve", return_value=sub), patch("stripe.Price.retrieve", side_effect=price):
            return client.post("/billing/webhook", content=raw,
                               headers={"Stripe-Signature": stripe_signature(raw, "local-testing-only")})

    assert send("evt_upgrade").status_code == 200
    entitlement = client.get("/entitlements", headers=headers[0]).json()
    assert entitlement["plan"] == "premium_plus" and entitlement["features"]["analytics"] is True
    assert send("evt_upgrade").json()["duplicate"] is True
    assert client.post("/billing/checkout", headers=headers[0], json={
        "plan": "premium", "idempotency_key": "already-subscribed"}).status_code == 409
    sub["metadata"]["nestai_plan"] = "premium_plus"
    sub["items"]["data"][0]["price"]["id"] = "price_premium"
    sub["cancel_at_period_end"] = True
    assert send("evt_downgrade").status_code == 200
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "premium"
    assert client.get("/billing/status", headers=headers[0]).json()["cancel_at_period_end"] is True
    del sub["metadata"]["nestai_user_id"]
    sub["items"]["data"][0]["price"]["id"] = "price_plus"
    assert send("evt_existing_without_metadata").status_code == 200
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "premium_plus"
    sub["metadata"]["nestai_user_id"] = str(ids[1])
    sub["status"] = "canceled"
    assert send("evt_wrong_owner").status_code == 200
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "premium_plus"
    sub["metadata"]["nestai_user_id"] = str(ids[0])
    sub["status"] = "active"
    sub["items"]["data"][0]["price"]["id"] = "price_unknown"
    assert send("evt_unknown_price").status_code == 200
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "free"
    with factory() as db:
        assert db.query(CreditBalance).one().credits_remaining == 87
        assert db.query(MonthlyUsage).one().count == 4
        assert db.get(AccountProperty, prop["id"]) is not None


def test_webhook_price_lookup_failure_rolls_back_for_retry(api, monkeypatch):
    import stripe
    client, factory, headers, ids, _ = api
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "local-testing-only")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_PREMIUM_PRICE_ID", "price_premium")
    with factory() as db:
        db.get(User, ids[0]).stripe_customer_id = "cus_retry"
        db.commit()
    sub = {"id": "sub_retry", "customer": "cus_retry", "metadata": {"nestai_user_id": str(ids[0])},
           "items": {"data": [{"price": {"id": "price_premium"}}]}, "status": "active"}
    raw = json.dumps({"id": "evt_retry", "type": "customer.subscription.updated", "livemode": False,
                      "data": {"object": {"id": sub["id"], "customer": sub["customer"]}}}).encode()
    with patch("stripe.Subscription.retrieve", return_value=sub), patch(
        "stripe.Price.retrieve", side_effect=stripe.APIConnectionError("mock unavailable")
    ):
        assert client.post("/billing/webhook", content=raw, headers={
            "Stripe-Signature": stripe_signature(raw, "local-testing-only")}).status_code == 502
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "free"
    with patch("stripe.Subscription.retrieve", return_value=sub), patch(
        "stripe.Price.retrieve", return_value={"id": "price_premium", "active": True, "type": "recurring"}
    ):
        response = client.post("/billing/webhook", content=raw, headers={
            "Stripe-Signature": stripe_signature(raw, "local-testing-only")})
    assert response.status_code == 200 and response.json()["duplicate"] is False
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "premium"


def test_postgres_webhook_reads_current_subscription_under_account_lock(api, monkeypatch):
    client, factory, headers, ids, backend = api
    if backend != "postgres":
        pytest.skip("Row-lock concurrency validated only on PostgreSQL")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "local-testing-only")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_PREMIUM_PRICE_ID", "price_premium")
    with factory() as db:
        db.get(User, ids[0]).stripe_customer_id = "cus_locked"
        db.commit()
    sub = {"id": "sub_locked", "customer": "cus_locked", "metadata": {"nestai_user_id": str(ids[0])},
           "items": {"data": [{"price": {"id": "price_premium"}}]}, "status": "active"}

    def retrieve(*args, **kwargs):
        with factory() as db:
            with pytest.raises(OperationalError):
                db.query(User).filter_by(id=ids[0]).with_for_update(nowait=True).one()
        return sub

    raw = json.dumps({"id": "evt_locked", "type": "customer.subscription.updated", "livemode": False,
                      "data": {"object": {"id": sub["id"], "customer": sub["customer"]}}}).encode()
    with patch("stripe.Subscription.retrieve", side_effect=retrieve), patch(
        "stripe.Price.retrieve", return_value={"id": "price_premium", "active": True, "type": "recurring"}
    ):
        assert client.post("/billing/webhook", content=raw, headers={
            "Stripe-Signature": stripe_signature(raw, "local-testing-only")}).status_code == 200
    assert client.get("/entitlements", headers=headers[0]).json()["plan"] == "premium"


def test_postgres_concurrent_save_and_restore_share_active_cap(api, monkeypatch):
    client, factory, headers, ids, backend = api
    if backend != "postgres":
        pytest.skip("Row-lock concurrency validated only on PostgreSQL")
    paid(api)
    monkeypatch.setenv("NESTAI_QUOTA_PREMIUM_PROPERTIES", "1")
    prop = save(api, "archived")
    assert client.post(f"/properties/{prop['id']}/archive", headers=headers[0], json={}).status_code == 200

    def run(operation):
        if operation == "restore":
            return client.post(f"/properties/{prop['id']}/restore", headers=headers[0], json={}).status_code
        return client.post("/properties", headers=headers[0], json={
            "kind": "home", "external_id": "concurrent-home", "parsed": {"address": "Other"},
            "idempotency_key": "concurrent-save"}).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, ["save", "restore"])) == [200, 429]
    assert client.get("/entitlements", headers=headers[0]).json()["usage"]["properties"] == 1
    with factory() as db:
        assert db.query(AccountProperty).filter_by(user_id=ids[0]).count() in {1, 2}

    def archive_all():
        for row in client.get("/properties", headers=headers[0]).json()["properties"]:
            assert client.post(f"/properties/{row['id']}/archive", headers=headers[0], json={}).status_code == 200

    archive_all()
    def save_kind(kind):
        return client.post("/properties", headers=headers[0], json={
            "kind": kind, "external_id": kind, "parsed": {"address": kind},
            "idempotency_key": kind}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save_kind, ["apartment", "rental_home"]))
    assert sorted(results) == [200, 429]
    successful = "apartment" if results[0] == 200 else "rental_home"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(save_kind, [successful, successful])) == [200, 200]
    assert client.get("/entitlements", headers=headers[0]).json()["usage"]["properties"] == 1

    archive_all()
    other = save(api, "restore-other", is_archived=True)
    def restore_id(property_id):
        return client.post(f"/properties/{property_id}/restore", headers=headers[0], json={}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(restore_id, [prop["id"], other["id"]])) == [200, 429]
    assert client.get("/entitlements", headers=headers[0]).json()["usage"]["properties"] == 1


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
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0010_browser_sessions"
            assert conn.execute(text("SELECT auth_version FROM users")).scalar() == 0
            conn.execute(text("INSERT INTO users (email, hashed_password, referral_code) VALUES ('new-default@example.com', 'hash', 'new-default-code')"))
            assert conn.execute(text("SELECT auth_version FROM users WHERE email='new-default@example.com'")).scalar() == 0
        command.downgrade(cfg, "ae05715be4e2")
        with admin.begin() as conn:
            conn.execute(text(f'SET search_path TO "{schema}"'))
            assert conn.execute(text("SELECT count(*) FROM properties")).scalar() == 1
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_concurrent_password_reset_consumes_token_once_and_revokes_sessions(api):
    client, factory, headers, ids, dialect = api
    if dialect != "postgres":
        pytest.skip("Reset account-lock concurrency requires PostgreSQL")
    from app.auth.security import hash_password, hash_reset_token, verify_password
    from app.db.models.password_reset_token import PasswordResetToken
    raw_token = uuid4().hex
    with factory() as db:
        db.add(PasswordResetToken(user_id=ids[0], token_hash=hash_reset_token(raw_token),
                                  expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
        db.get(User, ids[0]).hashed_password = hash_password("OriginalPassword123!")
        db.commit()

    def reset(password):
        response = client.post("/auth/reset-password", json={"token": raw_token, "password": password})
        return response.status_code, password

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reset, ["FirstNewPassword123!", "SecondNewPassword123!"]))
    assert sorted(code for code, _ in results) == [200, 400]
    winner = next(password for code, password in results if code == 200)
    with factory() as db:
        user = db.get(User, ids[0])
        assert user.auth_version == 1
        assert verify_password(winner, user.hashed_password)
        assert db.query(PasswordResetToken).one().used_at is not None
    for endpoint in ("/auth/me", "/properties", "/billing/status"):
        assert client.get(endpoint, headers=headers[0]).status_code == 401
    assert client.get("/auth/me", headers=headers[1]).status_code == 200
    login = client.post("/auth/login", json={"email": "user1@example.com", "password": winner})
    assert login.status_code == 200
    assert client.get("/auth/me", headers={
        "Authorization": "Bearer " + login.json()["access_token"],
    }).status_code == 200
