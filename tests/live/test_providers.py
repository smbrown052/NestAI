"""Explicit opt-in, read-only provider smoke checks; never charge or send mail."""

import os

import pytest
import requests


def _credential(name):
    if os.getenv("NESTAI_RUN_LIVE_TESTS") != "1":
        pytest.skip("BLOCKED: live provider checks require NESTAI_RUN_LIVE_TESTS=1")
    value = os.getenv(name)
    if not value:
        pytest.skip(f"BLOCKED: missing live provider credential {name}")
    return value


def test_google_geocoding_live():
    key = _credential("GOOGLE_MAPS_API_KEY")
    response = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
                            params={"key": key, "address": "1401 N Taft St, Arlington, VA"},
                            timeout=20)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "OK", result.get("error_message", result["status"])
    assert result["results"][0]["geometry"]["location"]["lat"] > 0


def test_walkscore_live():
    key = _credential("WALKSCORE_API_KEY")
    response = requests.get("https://api.walkscore.com/score",
                            params={"wsapikey": key, "format": "json", "lat": 38.8905,
                                    "lon": -77.084, "address": "1401 N Taft St, Arlington, VA"},
                            timeout=20)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == 1
    assert 0 <= payload["walkscore"] <= 100


def test_openai_live_read_only():
    key = _credential("OPENAI_API_KEY")
    response = requests.get("https://api.openai.com/v1/models",
                            headers={"Authorization": "Bearer " + key}, timeout=20)
    assert response.status_code == 200
    assert response.json()["data"]


def test_stripe_sandbox_live_read_only():
    key = _credential("STRIPE_SECRET_KEY")
    if not key.startswith(("sk_test_", "rk_test_")):
        pytest.skip("BLOCKED: only Stripe sandbox keys are permitted; no live charges")
    response = requests.get("https://api.stripe.com/v1/balance", auth=(key, ""), timeout=20)
    assert response.status_code == 200
    assert response.json()["livemode"] is False


def test_email_delivery_is_explicitly_blocked():
    pytest.skip("BLOCKED: live email delivery intentionally excluded; smoke tests never send email")
