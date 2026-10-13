"""HTTP regressions against the same migrated service used by browser journeys."""

import json
from uuid import uuid4

import pytest
import requests
from sqlalchemy import create_engine, text


def call(runtime, user, method, path, payload=None, status=200):
    response = requests.request(method, runtime["api"] + path, headers=user["headers"],
                                json=payload, timeout=20)
    assert response.status_code == status, response.text
    return response


def save(runtime, user, *, name, rent, pets, beds=1, sqft=800):
    return call(runtime, user, "POST", "/properties", {
        "idempotency_key": uuid4().hex, "kind": "rental_home",
        "parsed": {"display_name": name, "address": name, "monthly_rent": rent,
                   "bedrooms": beds, "bathrooms": 1, "square_feet": sqft,
                   "pets_policy": pets},
    }).json()


def test_numeric_and_natural_constraints_share_results_hard_pets_and_soft_mismatch(runtime, account):
    user = account("premium_plus")
    saved = [
        save(runtime, user, name="Pets welcome", rent=2400, pets="Pets allowed", sqft=900),
        save(runtime, user, name="Pets prohibited", rent=2200, pets="No pets", sqft=900),
        save(runtime, user, name="Policy unknown", rent=2000, pets=None, sqft=900),
        save(runtime, user, name="Exactly budget boundary", rent=3000, pets="Pets allowed", sqft=900),
        save(runtime, user, name="Below minimum area", rent=2300, pets="Pets allowed", sqft=800),
    ]
    ids = [item["id"] for item in saved]
    call(runtime, user, "PUT", "/profile", {"preferences": {"pets": "Yes"}})
    soft = call(runtime, user, "POST", "/ranking", {"property_ids": ids}).json()["ranked"]
    assert {row["property_id"] for row in soft} == set(ids), "Soft pet preferences must not remove listings"
    rejected = next(row for row in soft if row["property_id"] == saved[1]["id"])
    unknown = next(row for row in soft if row["property_id"] == saved[2]["id"])
    assert "Pet preference mismatch" in rejected["unmet_preferences"]
    assert "Pet policy unknown" in unknown["unmet_preferences"]
    parsed = call(runtime, user, "POST", "/requests", {
        "request": "under $3000 and at least 850 sqft and must allow pets",
    }).json()
    constraints = parsed["constraints"]
    assert constraints["rent_lt"] == 3000
    assert constraints["min_sqft"] == 850
    assert constraints["pet_friendly"] is True
    natural = call(runtime, user, "POST", "/ranking",
                   {"property_ids": ids, "constraints": constraints}).json()["ranked"]
    numeric = call(runtime, user, "POST", "/ranking", {
        "property_ids": ids, "constraints": {"rent_lt": 3000, "min_sqft": 850, "pet_friendly": True},
    }).json()["ranked"]
    assert [row["property_id"] for row in natural] == [saved[0]["id"]]
    assert [row["property_id"] for row in numeric] == [saved[0]["id"]]
    call(runtime, user, "POST", "/requests", {"request": "a magical view guaranteed forever"}, status=422)


def test_reports_plus_details_and_explicit_mock_provider_evidence(runtime, account):
    user = account("premium_plus")
    first = save(runtime, user, name="1401 N Taft St Arlington VA", rent=2400, pets="Pets allowed", sqft=900)
    second = save(runtime, user, name="Second confirmed listing", rent=2800, pets="No pets", sqft=750)
    ids = [first["id"], second["id"]]
    ranked = call(runtime, user, "POST", "/ranking", {"property_ids": ids}).json()["ranked"]
    assert len(ranked) == 2
    assert all("components" in row and "confidence" in row for row in ranked)
    assert ranked[0]["comparison"]["deltas"]["price"] is not None
    report_payload = {"property_ids": ids, "idempotency_key": uuid4().hex}
    report = call(runtime, user, "POST", "/reports", report_payload).json()
    assert json.loads(report["content"])["comparison"]["ranked"] == ranked
    replay = call(runtime, user, "POST", "/reports", report_payload).json()
    assert replay == report
    download = call(runtime, user, "GET", report["download_url"])
    assert download.json() == json.loads(report["content"])
    assert "attachment" in download.headers["Content-Disposition"]
    analytics = call(runtime, user, "POST", "/analytics", {
        "property_ids": ids, "idempotency_key": uuid4().hex,
    }).json()
    assert analytics["baseline"]["ranked"] == ranked
    assert analytics["sensitivity"]
    for path in ["/advisor", "/negotiation", "/enrichment", "/commute"]:
        response = call(runtime, user, "POST", path, {
            "property_ids": [first["id"]], "idempotency_key": uuid4().hex,
            "question": "Compare only confirmed facts", "destination": "Washington DC", "mode": "transit",
        }).json()
        assert response["mock"] is True
        assert response["provider"] == "mock"
    stranger = account("premium_plus")
    call(runtime, stranger, "GET", report["download_url"], status=404)


@pytest.mark.parametrize("path", ["/exports", "/reports", "/analytics", "/advisor", "/enrichment", "/commute"])
def test_free_api_cannot_bypass_ui_gates(runtime, account, path):
    user = account("free")
    prop = save(runtime, user, name="Free property", rent=2100, pets="No pets")
    payload = {"property_ids": [prop["id"]]}
    if path == "/exports":
        payload.update(format="csv", scope="properties")
    else:
        payload.update(idempotency_key=uuid4().hex)
    call(runtime, user, "POST", path, payload, status=403)


def test_feedback_idempotency_admin_visibility_and_durable_database_record(runtime, account):
    user, admin = account("free"), account("free", admin=True)
    payload = {
        "idempotency_key": uuid4().hex, "category": "bug",
        "title": "Persisted API feedback " + uuid4().hex,
        "description": "The regression verifies the real PostgreSQL-backed admin record.",
        "actual_behavior": "Before fix, browser feedback and admin used different stores.",
        "expected_behavior": "One durable record visible to authorized administrators.",
        "route_or_screen": "Apartment Search", "user_contact_allowed": False,
    }
    created = call(runtime, user, "POST", "/feedback", payload).json()
    assert call(runtime, user, "POST", "/feedback", payload).json() == created
    reports = call(runtime, admin, "GET", "/admin/feedback?status=new").json()
    record = next(report for report in reports if report["id"] == created["id"])
    assert record["public_reference"] == created["public_reference"]
    assert record["title"] == payload["title"]
    assert record["category"] == "bug"
    assert record["user_plan"] == "free"
    call(runtime, user, "GET", "/admin/feedback", status=403)
    engine = create_engine(runtime["database_url"])
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT user_id, description, actual_behavior, expected_behavior,
                       route_or_screen, contact_email, user_contact_allowed
                FROM feedback_reports WHERE public_reference = :reference
            """), {"reference": created["public_reference"]}).mappings().all()
        assert len(rows) == 1
        assert rows[0]["user_id"] == user["id"]
        assert rows[0]["description"] == payload["description"]
        assert rows[0]["actual_behavior"] == payload["actual_behavior"]
        assert rows[0]["expected_behavior"] == payload["expected_behavior"]
        assert rows[0]["route_or_screen"] == payload["route_or_screen"]
        assert rows[0]["contact_email"] is None
        assert rows[0]["user_contact_allowed"] is False
    finally:
        engine.dispose()
