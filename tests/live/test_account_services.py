"""Opt-in service acceptance checks against dedicated, pre-provisioned accounts."""

import json
import os
from uuid import uuid4

import pytest
import requests


def account(tier):
    if os.getenv("NESTAI_RUN_LIVE_TESTS") != "1":
        pytest.skip("BLOCKED: set NESTAI_RUN_LIVE_TESTS=1 for live acceptance")
    base = os.getenv("NESTAI_LIVE_API_BASE_URL", "").rstrip("/")
    if not base.startswith("https://"):
        pytest.skip("BLOCKED: configure HTTPS NESTAI_LIVE_API_BASE_URL")
    prefix = f"NESTAI_LIVE_{tier.upper()}"
    email, password = os.getenv(prefix + "_EMAIL"), os.getenv(prefix + "_PASSWORD")
    if not email or not password:
        pytest.skip(f"BLOCKED: provision dedicated account and configure {prefix}_EMAIL and {prefix}_PASSWORD")
    session = requests.Session()
    response = session.post(base + "/auth/login", json={"email": email, "password": password}, timeout=30)
    assert response.status_code == 200, f"Live login failed ({response.status_code})"
    session.headers["Authorization"] = "Bearer " + response.json()["access_token"]
    response = session.get(base + "/entitlements", timeout=30)
    assert response.status_code == 200
    expected = {"free": "free", "premium": "premium", "plus": "premium_plus"}[tier]
    assert response.json()["plan"] == expected
    return base, session


@pytest.mark.parametrize("tier", ["free", "premium", "plus"])
def test_live_reauthentication_restores_account_snapshot(tier):
    base, first = account(tier)
    try:
        saved = first.get(base + "/properties", timeout=30)
        profile = first.get(base + "/profile", timeout=30)
        assert saved.status_code == profile.status_code == 200
        properties = saved.json()["properties"]
        if not properties:
            pytest.skip(f"BLOCKED: seed saved sample listings in dedicated {tier} account")
        second_base, second = account(tier)
        try:
            assert second_base == base
            restored = second.get(base + "/properties", timeout=30)
            restored_profile = second.get(base + "/profile", timeout=30)
            assert restored.status_code == restored_profile.status_code == 200
            assert restored.json() == saved.json()
            assert restored_profile.json() == profile.json()
        finally:
            second.close()
    finally:
        first.close()


@pytest.mark.parametrize("tier", ["premium", "plus"])
def test_live_grounded_advisor_and_filtered_artifacts(tier):
    if os.getenv("NESTAI_LIVE_ALLOW_ACCOUNT_OPERATIONS") != "1":
        pytest.skip("BLOCKED: authorize dedicated-account quota/provider use with NESTAI_LIVE_ALLOW_ACCOUNT_OPERATIONS=1")
    base, session = account(tier)
    try:
        saved = session.get(base + "/properties", timeout=30)
        assert saved.status_code == 200
        ids = [row["id"] for row in saved.json()["properties"]
               if row["kind"] == "apartment" and not row["parsed"].get("is_archived")]
        if not ids:
            pytest.skip(f"BLOCKED: seed saved sample listings in dedicated {tier} account")
        parsed = session.post(base + "/requests", json={
            "request": "Only show units under $2,500 per month with at least 700 square feet"
        }, timeout=30)
        assert parsed.status_code == 200
        selection = {"property_ids": ids, "constraints": parsed.json()["constraints"]}
        ranking = session.post(base + "/ranking", json=selection, timeout=30)
        assert ranking.status_code == 200
        ranked = ranking.json()["ranked"]
        assert ranked, "Dedicated live fixtures must include matching units"
        assert all(row["price_num"] < 2500 and row["sqft_num"] >= 700 for row in ranked)
        advisor = session.post(base + "/advisor", json={
            **selection, "idempotency_key": uuid4().hex,
            "question": "Compare the first two ranked options using only verified rent and space deltas. Identify unknown fees."
        }, timeout=90)
        assert advisor.status_code == 200, f"Live advisor failed ({advisor.status_code})"
        answer = advisor.json()
        assert answer["mock"] is False and answer["answer"].strip()
        assert answer["citations"] and all(citation["property_id"] in ids for citation in answer["citations"])
        export = session.post(base + "/exports", json={**selection, "format": "json", "scope": "units"}, timeout=30)
        assert export.status_code == 200
        assert export.json() == ranked
        report = session.post(base + "/reports", json={**selection, "idempotency_key": uuid4().hex}, timeout=60)
        assert report.status_code == 200
        download = session.get(base + report.json()["download_url"], timeout=30)
        assert download.status_code == 200
        assert "attachment" in download.headers.get("Content-Disposition", "").lower()
        content = download.json()
        assert content == json.loads(report.json()["content"])
        assert content["comparison"]["ranked"] == ranked
        assert content["report_level"] == ("plus" if tier == "plus" else "premium")
        if tier == "plus":
            assert content["analytics"]["baseline"]["ranked"] == ranked
    finally:
        session.close()


@pytest.mark.parametrize("tier", ["premium", "plus"])
def test_live_enrichment_commute_and_review_only_negotiation(tier):
    if os.getenv("NESTAI_LIVE_ALLOW_ACCOUNT_OPERATIONS") != "1":
        pytest.skip("BLOCKED: authorize dedicated-account provider use with NESTAI_LIVE_ALLOW_ACCOUNT_OPERATIONS=1")
    base, session = account(tier)
    try:
        saved = session.get(base + "/properties", timeout=30)
        assert saved.status_code == 200
        properties = [row for row in saved.json()["properties"]
                      if row["kind"] == "apartment" and not row["parsed"].get("is_archived")]
        if not properties:
            pytest.skip(f"BLOCKED: seed apartment sample in dedicated {tier} account")
        selected = {"property_ids": [properties[0]["id"]]}
        enrichment = session.post(base + "/enrichment", json={
            **selected, "idempotency_key": uuid4().hex
        }, timeout=180)
        assert enrichment.status_code == 200, f"Live enrichment failed ({enrichment.status_code})"
        assert enrichment.json()["mock"] is False
        commute = session.post(base + "/commute", json={
            **selected, "idempotency_key": uuid4().hex,
            "destination": "Union Station, Washington, DC", "mode": "transit"
        }, timeout=90)
        assert commute.status_code == 200, f"Live commute failed ({commute.status_code})"
        assert commute.json()["mock"] is False and commute.json()["routes"]
        negotiation = session.post(base + "/negotiation", json={
            **selected, "idempotency_key": uuid4().hex,
            "question": "Draft a rent negotiation request for my review using only this listing's facts. Do not send it."
        }, timeout=90)
        assert negotiation.status_code == 200, f"Live negotiation failed ({negotiation.status_code})"
        assert negotiation.json()["mock"] is False and negotiation.json()["answer"].strip()
        if tier == "plus":
            analytics = session.post(base + "/analytics", json={
                **selected, "idempotency_key": uuid4().hex,
                "priorities": {"price": 1, "space": 5}
            }, timeout=30)
            assert analytics.status_code == 200
            assert analytics.json()["sensitivity"]
    finally:
        session.close()
