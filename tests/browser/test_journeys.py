"""Desktop/mobile journeys through the real Streamlit -> HTTP API boundary."""

import csv
import io
import json
from pathlib import Path
import re
from uuid import uuid4

import requests
import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]


def navigate(page, name):
    idle(page)
    sidebar = page.locator('[data-testid="stSidebar"]')
    expect(sidebar).to_be_attached()
    if sidebar.get_attribute("aria-expanded") == "false":
        page.locator('[data-testid="stExpandSidebarButton"]').click()
    expect(sidebar).to_have_attribute("aria-expanded", "true")
    button = sidebar.get_by_role("button", name=name, exact=True)
    button.click()
    expect(button).to_have_attribute("kind", "primary")
    idle(page)
    if page.viewport_size["width"] < 600:
        page.locator('[data-testid="stSidebarCollapseButton"]').click()
        expect(sidebar).to_have_attribute("aria-expanded", "false")


def sign_in(page, runtime, user):
    page.goto(runtime["ui"])
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("textbox", name="Email", exact=True).fill(user["email"])
    page.get_by_role("textbox", name="Password", exact=True).fill(user["password"])
    page.get_by_role("button", name="Sign In", exact=True).click()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible()


def sign_out(page):
    idle(page)
    page.get_by_role("button", name="Log out", exact=True).click()
    expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
    idle(page)


def healthy(page):
    expect(page.locator('[data-testid="stException"]')).to_have_count(0)
    expect(page.get_by_text("Account services are temporarily unavailable.", exact=True)).to_have_count(0)
    expect(page.get_by_text(re.compile("TypeError: Failed to fetch dynamically imported module"))).to_have_count(0)


def idle(page):
    expect(page.locator('[data-testid="stApp"]')).to_have_attribute("data-test-script-state", "notRunning")


def properties(runtime, user):
    response = requests.get(runtime["api"] + "/properties", headers=user["headers"], timeout=10)
    assert response.status_code == 200, response.text
    return response.json()["properties"]


def select_value(page, label, value):
    idle(page)
    select = page.get_by_role("combobox", name=label, exact=True)
    if select.input_value() != value:
        select.scroll_into_view_if_needed()
        select.click()
        select.press("ArrowDown")
        expect(select).to_have_attribute("aria-expanded", "true")
        page.get_by_role("option").filter(has_text=value).click()
    expect(select).to_have_value(value)
    idle(page)


def save_example(page, fixture_name, kind="Apartment"):
    select_value(page, "Listing type", kind)
    text = (ROOT / "legacy/streamlit/data" / fixture_name).read_text()
    page.get_by_role("textbox", name="Paste listing text", exact=True).fill(text)
    page.get_by_role("button", name="Parse listing", exact=True).click()
    expect(page.get_by_role("heading", name="Parsed listing preview", exact=True)).to_be_visible()
    page.get_by_role("button", name="Save parsed property", exact=True).click()
    expect(page.get_by_role("button", name="Save parsed property", exact=True)).to_have_count(0)
    idle(page)
    healthy(page)


def test_signup_and_all_navigation(page, runtime):
    email = f"signup-{uuid4().hex}@example.com"
    page.goto(runtime["ui"])
    page.get_by_role("button", name="Create free account", exact=True).click()
    page.get_by_role("textbox", name="Display name", exact=True).fill("Signup Browser")
    page.get_by_role("textbox", name="Email", exact=True).fill(email)
    page.get_by_role("textbox", name="Password", exact=True).fill("BrowserRegression-9274!")
    page.get_by_role("button", name="Create Account", exact=True).click()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
    for name in ["Home", "Apartment Search", "Houses", "Why NestAI", "How to Use NestAI", "Profile"]:
        navigate(page, name)
        healthy(page)
    for name in ["Account", "Subscription & Pricing", "Preferences"]:
        page.get_by_role("tab", name=name, exact=True).click()
        expect(page.get_by_role("tab", name=name, exact=True)).to_have_attribute("aria-selected", "true")
        healthy(page)
    page.get_by_role("tab", name="Account", exact=True).click()
    page.get_by_role("textbox", name="Display name", exact=True).fill("Signup Browser Updated")
    page.get_by_role("button", name="Save profile", exact=True).click()
    expect(page.get_by_text("Profile saved.", exact=True)).to_be_visible()
    sign_out(page)
    expect(page.get_by_role("button", name="Log out", exact=True)).to_have_count(0)
    sign_in(page, runtime, {"email": email, "password": "BrowserRegression-9274!"})
    navigate(page, "Profile")
    expect(page.get_by_text(email, exact=True)).to_be_visible()
    expect(page.get_by_role("textbox", name="Display name", exact=True)).to_have_value("Signup Browser Updated")


def test_mixed_saved_reload_restores_authentication_and_revocation(page, runtime, account):
    import hashlib
    from datetime import datetime, timedelta, timezone

    user = account("premium_plus")
    sign_in(page, runtime, user)
    listing = (
        "Reload Apartments\n123 Main St, Arlington, VA 22201\nPricing & Floor Plans\n"
        "A1\n$2,400\n1 Bed\n1 Bath\n750 Sq Ft\n"
        "Unit\n0012\nprice\n$2,400\nsquare feet\n750\navailabilityNow\n"
        "B2\n$2,600\n2 Bed\n2 Bath\n950 Sq Ft\n"
        "Unit\n0013\nprice\n$2,600\nsquare feet\n950\navailabilityNow\n"
    )
    page.get_by_role("textbox", name="Paste listing text", exact=True).fill(listing)
    page.get_by_role("button", name="Parse listing", exact=True).click()
    expect(page.locator('[data-testid="stJson"]')).to_have_count(0)
    page.get_by_role("button", name="Save parsed property", exact=True).click()
    expect(page.get_by_role("button", name="Save parsed property", exact=True)).to_have_count(0)
    save_example(page, "home_example_1.txt", kind="Rental house")
    saved = properties(runtime, user)
    assert len(saved) == 2
    assert sorted(len(item["units"]) for item in saved) == [0, 2]
    saved_ids = {item["id"] for item in saved}
    usage = requests.get(runtime["api"] + "/entitlements", headers=user["headers"], timeout=10).json()["usage"]
    assert usage["analyses"] == 2
    page.reload()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Saved comparison", exact=True)).to_be_visible()
    assert {item["id"] for item in properties(runtime, user)} == saved_ids
    assert requests.get(runtime["api"] + "/entitlements", headers=user["headers"], timeout=10).json()["usage"] == usage
    navigate(page, "Profile")
    expect(page.get_by_text(user["email"], exact=True)).to_be_visible()
    navigate(page, "Apartment Search")
    select_value(page, "Property", "Reload Apartments")
    expect(page.get_by_text(re.compile(r"1.*2 beds.*1.*2 baths"))).to_be_visible()

    request_text = "Rent under $2500 and at least 700 square feet. Prioritize price."
    page.get_by_role("textbox", name="Natural-language request", exact=True).fill(request_text)
    page.get_by_role("button", name="Apply request and numeric filters", exact=True).click()
    expect(page.get_by_text(re.compile(r"^Applied constraints:.*2500.*700"))).to_be_visible()
    parsed = requests.post(runtime["api"] + "/requests", headers=user["headers"],
                           json={"request": request_text}, timeout=10).json()
    ranking = requests.post(runtime["api"] + "/ranking", headers=user["headers"], json={
        "property_ids": list(saved_ids), "constraints": parsed["constraints"], "priorities": parsed["priorities"],
    }, timeout=10).json()["ranked"]
    assert len(ranking) == 2
    assert all(row["price_num"] < 2500 and row["sqft_num"] >= 700 for row in ranking)
    details = page.get_by_role("combobox", name="Listing details", exact=True)
    details.click()
    details.press("ArrowDown")
    expect(page.get_by_role("option")).to_have_text([
        f"{row.get('property') or row.get('address') or row['property_id']} · "
        f"{row.get('unit') or row.get('unit_id') or 'Home'}" for row in ranking
    ])
    details.press("Escape")
    page.get_by_role("button", name="Prepare CSV export", exact=True).click()
    with page.expect_download() as download:
        page.get_by_role("button", name="Download comparison CSV", exact=True).click()
    with open(download.value.path(), encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["property_id"], row["unit_id"] or None) for row in rows] == [
        (row["property_id"], row.get("unit_id")) for row in ranking
    ]
    page.get_by_role("button", name="Generate decision report", exact=True).click()
    with page.expect_download() as report_download:
        page.get_by_role("button", name="Download report", exact=True).click()
    with open(report_download.value.path(), encoding="utf-8") as handle:
        report = json.load(handle)
    assert report["comparison"]["ranked"] == ranking
    expect(page.get_by_role("heading", name="Decision report", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Top recommendation", exact=True).first).to_be_visible()
    expect(page.locator('[data-testid="stJson"]')).to_have_count(0)
    page.get_by_role("button", name="View advanced analytics", exact=True).click()
    expect(page.get_by_role("heading", name="Advanced analytics", exact=True).last).to_be_visible()
    expect(page.get_by_role("heading", name="Priority sensitivity", exact=True).last).to_be_visible()
    expect(page.locator('[data-testid="stJson"]')).to_have_count(0)
    idle(page)
    page.screenshot(path=f"/tmp/nestai-readable-{page.viewport_size['width']}.png", full_page=True)
    page.get_by_role("button", name="Reset filters", exact=True).click()
    expect(page.get_by_text("Applied constraints: None", exact=True)).to_be_visible()
    expect(page.get_by_text("Applied priorities: Default priorities", exact=True)).to_be_visible()
    for name in ("price", "space", "commute", "walkability", "pets"):
        expect(page.get_by_role("group", name=name.title(), exact=True).get_by_role("slider")).to_have_value("1")
    unfiltered = requests.post(runtime["api"] + "/ranking", headers=user["headers"],
                               json={"property_ids": list(saved_ids)}, timeout=10).json()["ranked"]
    assert len(unfiltered) == 3
    page.get_by_role("button", name="Prepare CSV export", exact=True).click()
    with page.expect_download() as reset_download:
        page.get_by_role("button", name="Download comparison CSV", exact=True).click()
    with open(reset_download.value.path(), encoding="utf-8-sig") as handle:
        restored_rows = list(csv.DictReader(handle))
    assert [(row["property_id"], row["unit_id"] or None) for row in restored_rows] == [
        (row["property_id"], row.get("unit_id")) for row in unfiltered
    ]

    sign_out(page)
    expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_have_count(0)
    sign_in(page, runtime, user)
    raw_reset = uuid4().hex
    engine = create_engine(runtime["database_url"])
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, created_at)
                VALUES (:user_id, :token_hash, :expires_at, now())
            """), {"user_id": user["id"], "token_hash": hashlib.sha256(raw_reset.encode()).hexdigest(),
                   "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)})
    finally:
        engine.dispose()
    reset = requests.post(runtime["api"] + "/auth/reset-password", json={
        "token": raw_reset, "password": "ResetBrowserPassword123!",
    }, timeout=10)
    assert reset.status_code == 200
    page.reload()
    expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_have_count(0)
    user["password"] = "ResetBrowserPassword123!"
    sign_in(page, runtime, user)
    healthy(page)


def test_password_reset_revokes_old_session_and_restores_saved_data(page, runtime, account):
    user = account("free")
    sign_in(page, runtime, user)
    save_example(page, "app_listing_1.txt")
    saved_ids = {item["id"] for item in properties(runtime, user)}
    forgot = requests.post(runtime["api"] + "/auth/forgot-password",
                           json={"email": user["email"]}, timeout=10)
    assert forgot.status_code == 200, forgot.text
    reset_link = forgot.json()["reset_link"]
    assert reset_link
    page.goto(reset_link)
    page.get_by_role("textbox", name="New password", exact=True).fill("BrowserNewPassword-9274!")
    page.get_by_role("button", name="Reset password", exact=True).click()
    expect(page.get_by_text("Password reset successfully. Please sign in.", exact=True)).to_be_visible()
    assert requests.get(runtime["api"] + "/properties", headers=user["headers"], timeout=10).status_code == 401
    assert requests.post(runtime["api"] + "/auth/login", json={
        "email": user["email"], "password": user["password"],
    }, timeout=10).status_code == 401
    page.get_by_role("textbox", name="Email", exact=True).fill(user["email"])
    page.get_by_role("textbox", name="Password", exact=True).fill("BrowserNewPassword-9274!")
    page.get_by_role("button", name="Sign In", exact=True).click()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
    navigate(page, "Apartment Search")
    expect(page.locator('[data-testid="stTable"] tbody tr')).to_have_count(29)
    login = requests.post(runtime["api"] + "/auth/login", json={
        "email": user["email"], "password": "BrowserNewPassword-9274!",
    }, timeout=10)
    assert login.status_code == 200
    user["headers"] = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert {item["id"] for item in properties(runtime, user)} == saved_ids
    healthy(page)


@pytest.mark.parametrize("plan", ["premium", "premium_plus"])
def test_paid_plan_switch_without_provider_configuration_fails_closed(page, runtime, account, plan):
    user = account(plan)
    sign_in(page, runtime, user)
    navigate(page, "Profile")
    page.get_by_role("tab", name="Subscription & Pricing", exact=True).click()
    page.get_by_role("button", name="Change subscription securely", exact=True).click()
    expect(page.get_by_text(
        "Subscription management is unavailable. Your current access and balance are unchanged.",
        exact=True,
    )).to_be_visible()
    expect(page.get_by_role("button", name="Continue to Stripe →", exact=True)).to_have_count(0)
    response = requests.get(runtime["api"] + "/entitlements", headers=user["headers"], timeout=10)
    assert response.status_code == 200, response.text
    assert response.json()["plan"] == plan
    healthy(page)


@pytest.mark.parametrize("plan", ["free", "premium", "premium_plus"])
def test_all_account_tabs_and_house_preferences_restore_after_reload(page, runtime, account, plan):
    user = account(plan)
    sign_in(page, runtime, user)
    navigate(page, "Houses")
    save_example(page, "home_example_1.txt", kind="Rental house")
    save_example(page, "home_example_2.txt", kind="Rental house")
    saved_ids = {item["id"] for item in properties(runtime, user)}
    expect(page.get_by_role("tab", name="Referrals", exact=True)).to_have_count(0)
    navigate(page, "Profile")
    for name in ["Account", "Subscription & Pricing", "Preferences"]:
        page.get_by_role("tab", name=name, exact=True).click()
        expect(page.get_by_role("tab", name=name, exact=True)).to_have_attribute("aria-selected", "true")
        healthy(page)
    select_value(page, "Pet-friendly preference", "Yes")
    page.get_by_role("button", name="Save preferences", exact=True).click()
    expect(page.get_by_text("Preferences saved to your account.", exact=True)).to_be_visible()
    navigate(page, "Houses")
    page.get_by_text("Decision details", exact=True).click()
    expect(page.get_by_text("$145/mo less expensive", exact=False).first).to_be_visible()
    expect(page.get_by_text("25 sq ft less space", exact=False).first).to_be_visible()
    expect(page.get_by_text("$145/mo more expensive", exact=False)).to_have_count(0)
    page.reload()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
    idle(page)
    assert {item["id"] for item in properties(runtime, user)} == saved_ids
    navigate(page, "Profile")
    page.get_by_role("tab", name="Preferences", exact=True).click()
    expect(page.get_by_role("combobox", name="Pet-friendly preference", exact=True)).to_have_value("Yes")
    healthy(page)


@pytest.mark.parametrize("plan", ["premium", "premium_plus"])
def test_exact_numeric_request_download_and_reset(page, runtime, account, plan):
    user = account(plan)
    sign_in(page, runtime, user)
    save_example(page, "app_listing_1.txt")
    save_example(page, "app_listing_2.txt")
    saved = properties(runtime, user)
    page.get_by_role("textbox", name="Natural-language request", exact=True).fill(
        "Only show units under $2,500 per month with at least 700 square feet."
    )
    page.get_by_role("button", name="Apply request and numeric filters", exact=True).click()
    expect(page.get_by_text(re.compile(r"^Applied constraints:.*'rent_lt': 2500.*'min_sqft': 700"))).to_be_visible()
    inputs = {"property_ids": [item["id"] for item in saved],
              "constraints": {"rent_lt": 2500, "min_sqft": 700}}
    response = requests.post(runtime["api"] + "/ranking", headers=user["headers"], json=inputs, timeout=10)
    assert response.status_code == 200, response.text
    ranked = response.json()["ranked"]
    assert ranked and all(row["price_num"] < 2500 and row["sqft_num"] >= 700 for row in ranked)
    page.get_by_role("button", name="Prepare CSV export", exact=True).click()
    with page.expect_download() as download:
        page.get_by_role("button", name="Download comparison CSV", exact=True).click()
    assert download.value.failure() is None
    with open(download.value.path(), encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["property_id"], row["unit_id"]) for row in rows] == [
        (row["property_id"], row["unit_id"]) for row in ranked
    ]
    assert all(float(row["price"]) < 2500 and float(row["square_feet"]) >= 700 for row in rows)
    page.get_by_role("button", name="Reset filters", exact=True).click()
    expect(page.get_by_role("textbox", name="Natural-language request", exact=True)).to_have_value("")
    expect(page.get_by_text("Applied constraints: None", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Download comparison CSV", exact=True)).to_have_count(0)
    assert sum(len(item["units"]) for item in properties(runtime, user)) == 42
    healthy(page)


def test_apartment_save_dedup_persists_and_free_has_no_native_downloads(page, runtime, account):
    user = account("free")
    sign_in(page, runtime, user)
    save_example(page, "app_listing_1.txt")
    assert [len(item["units"]) for item in properties(runtime, user)] == [29]
    save_example(page, "app_listing_2.txt")
    assert sorted(len(item["units"]) for item in properties(runtime, user)) == [13, 29]
    save_example(page, "app_listing_1.txt")
    assert sorted(len(item["units"]) for item in properties(runtime, user)) == [13, 29]
    # Streamlit's native dataframe toolbar can bypass a missing app export button.
    expect(page.locator('[data-testid="stDataFrame"]')).to_have_count(0)
    expect(page.locator('[data-testid="stDataFrame"] button[aria-label*="Download"]')).to_have_count(0)
    expect(page.locator('[data-testid="stDownloadButton"]')).to_have_count(0)
    sign_out(page)
    sign_in(page, runtime, user)
    assert sum(len(item["units"]) for item in properties(runtime, user)) == 42
    expect(page.get_by_role("heading", name="Saved comparison", exact=True)).to_be_visible()
    navigate(page, "Profile")
    page.get_by_role("tab", name="Preferences", exact=True).click()
    budget = page.get_by_role("spinbutton", name="Max monthly budget ($)", exact=True)
    budget.fill("3500")
    page.get_by_role("button", name="Save preferences", exact=True).click()
    expect(page.get_by_text("Preferences saved to your account.", exact=True)).to_be_visible()
    sign_out(page)
    sign_in(page, runtime, user)
    navigate(page, "Profile")
    page.get_by_role("tab", name="Preferences", exact=True).click()
    expect(page.get_by_role("spinbutton", name="Max monthly budget ($)", exact=True)).to_have_value("3500")
    # A new WebSocket restores the tab through a server-revocable credential.
    saved_ids = {item["id"] for item in properties(runtime, user)}
    page.reload()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
    idle(page)
    expect(page.get_by_role("heading", name="Saved comparison", exact=True)).to_be_visible()
    expect(page.locator('[data-testid="stTable"]').first.locator("tbody tr")).to_have_count(42)
    assert {item["id"] for item in properties(runtime, user)} == saved_ids
    navigate(page, "Profile")
    page.get_by_role("tab", name="Preferences", exact=True).click()
    expect(page.get_by_role("spinbutton", name="Max monthly budget ($)", exact=True)).to_have_value("3500")
    healthy(page)
    sign_out(page)
    isolated_user = account("free")
    sign_in(page, runtime, isolated_user)
    expect(page.get_by_text("Save a listing to begin your comparison.", exact=True)).to_be_visible()
    expect(page.locator('[data-testid="stTable"]')).to_have_count(0)
    navigate(page, "Profile")
    page.get_by_role("tab", name="Preferences", exact=True).click()
    expect(page.get_by_role("spinbutton", name="Max monthly budget ($)", exact=True)).to_have_value("0")
    with page.context.browser.new_context(viewport=page.viewport_size) as fresh_context:
        fresh_page = fresh_context.new_page()
        sign_in(fresh_page, runtime, user)
        expect(fresh_page.locator('[data-testid="stTable"]').first.locator("tbody tr")).to_have_count(42)
        navigate(fresh_page, "Profile")
        fresh_page.get_by_role("tab", name="Preferences", exact=True).click()
        expect(fresh_page.get_by_role("spinbutton", name="Max monthly budget ($)", exact=True)).to_have_value("3500")
        healthy(fresh_page)


@pytest.mark.parametrize("plan", ["premium", "premium_plus"])
def test_natural_priorities_and_filtered_downloads_match_visible_comparison(page, runtime, account, plan):
    user = account(plan)
    sign_in(page, runtime, user)
    save_example(page, "app_listing_1.txt")
    save_example(page, "app_listing_2.txt")
    page.get_by_role("textbox", name="Natural-language request", exact=True).fill("prioritize space over price")
    page.get_by_role("button", name="Apply request and numeric filters", exact=True).click()
    expect(page.get_by_text(re.compile(r"^Applied priorities:.*space"))).to_be_visible()
    idle(page)
    space_options = page.get_by_role("combobox", name="Listing details", exact=True).input_value()
    page.get_by_role("textbox", name="Natural-language request", exact=True).fill("prioritize price over space")
    page.get_by_role("button", name="Apply request and numeric filters", exact=True).click()
    expect(page.get_by_text(re.compile(r"^Applied priorities:.*'price': 3\.0.*'space': 1\.0"))).to_be_visible()
    idle(page)
    assert page.get_by_role("combobox", name="Listing details", exact=True).input_value() != space_options
    save_example(page, "home_example_1.txt", kind="Rental house")
    page.get_by_role("spinbutton", name="Maximum rent ($/month)", exact=True).fill("2800")
    page.get_by_role("spinbutton", name="Minimum square feet", exact=True).fill("800")
    page.get_by_role("button", name="Apply request and numeric filters", exact=True).click()
    expect(page.get_by_text(re.compile(r"^Applied constraints:.*'rent_lte': 2800.*'min_sqft': 800"))).to_be_visible()
    saved = properties(runtime, user)
    parsed_request = requests.post(runtime["api"] + "/requests", headers=user["headers"],
                                   json={"request": "prioritize price over space"}, timeout=10)
    assert parsed_request.status_code == 200, parsed_request.text
    inputs = {"property_ids": [item["id"] for item in saved],
              "constraints": {"rent_lte": 2800, "min_sqft": 800},
              "priorities": parsed_request.json()["priorities"]}
    response = requests.post(runtime["api"] + "/ranking", headers=user["headers"], json=inputs, timeout=10)
    assert response.status_code == 200, response.text
    ranked = response.json()["ranked"]
    assert 0 < len(ranked) < 43
    assert any(row.get("unit_id") is None for row in ranked)
    expected = [(row["property_id"], row.get("unit_id")) for row in ranked]
    page.get_by_role("button", name="Prepare CSV export", exact=True).click()
    with page.expect_download() as csv_download:
        page.get_by_role("button", name="Download comparison CSV", exact=True).click()
    with open(csv_download.value.path(), encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["property_id"], row["unit_id"] or None) for row in rows] == expected
    for exported, visible in zip(rows, ranked):
        assert int(exported["rank"]) == visible["rank"]
        assert exported["price_kind"] == visible["price_kind"]
        assert exported["name"] == visible["property"]
        for csv_key, rank_key in [
            ("price", "price_num"), ("square_feet", "sqft_num"),
            ("beds", "beds_num"), ("baths", "baths_num"),
            ("score", "score"), ("monthly_total", "monthly_total"),
        ]:
            if visible.get(rank_key) is None:
                assert exported[csv_key] == ""
            else:
                assert float(exported[csv_key]) == visible[rank_key]
        assert exported["fees_complete"] == str(visible["fees_complete"])
    page.get_by_role("button", name="Generate decision report", exact=True).click()
    with page.expect_download() as report_download:
        page.get_by_role("button", name="Download report", exact=True).click()
    with open(report_download.value.path(), encoding="utf-8") as handle:
        report = json.load(handle)
    assert [(row["property_id"], row.get("unit_id")) for row in report["comparison"]["ranked"]] == expected
    assert report["comparison"]["ranked"] == ranked
    assert [item["id"] for item in report["properties"]] == list(dict.fromkeys(row["property_id"] for row in ranked))
    assert [(item["id"], unit["id"]) for item in report["properties"] for unit in item["units"]] == [
        (row["property_id"], row["unit_id"])
        for property_id in dict.fromkeys(row["property_id"] for row in ranked)
        for row in ranked if row["property_id"] == property_id and row.get("unit_id") is not None
    ]
    page.get_by_role("spinbutton", name="Maximum rent ($/month)", exact=True).fill("2600")
    page.get_by_role("button", name="Apply request and numeric filters", exact=True).click()
    expect(page.get_by_role("button", name="Download comparison CSV", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Download report", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Reset filters", exact=True).click()
    expect(page.get_by_role("spinbutton", name="Maximum rent ($/month)", exact=True)).to_have_value("0")
    expect(page.get_by_role("textbox", name="Natural-language request", exact=True)).to_have_value("")
    expect(page.get_by_text("Applied constraints: None", exact=True)).to_be_visible()
    healthy(page)


def test_paid_csv_download_contains_actual_saved_units(page, runtime, account):
    user = account("premium_plus")
    sign_in(page, runtime, user)
    save_example(page, "app_listing_1.txt")
    save_example(page, "app_listing_2.txt")
    select_value(page, "CSV export scope", "Apartment units")
    page.get_by_role("button", name="Prepare CSV export", exact=True).click()
    with page.expect_download() as download_info:
        page.get_by_role("button", name="Download comparison CSV", exact=True).click()
    download = download_info.value
    assert download.failure() is None
    assert download.suggested_filename.endswith(".csv")
    with open(download.path(), encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(io.StringIO(handle.read())))
    assert len(rows) == 42
    assert {row["property_id"] for row in rows} == {item["id"] for item in properties(runtime, user)}
    assert len({(row["property_id"], row["unit_id"]) for row in rows}) == 42
    assert {(row["property_id"], row["unit_id"]) for row in rows} == {
        (item["id"], unit["id"]) for item in properties(runtime, user) for unit in item["units"]
    }
    page.get_by_role("button", name="Generate decision report", exact=True).click()
    with page.expect_download() as report_download:
        page.get_by_role("button", name="Download report", exact=True).click()
    with open(report_download.value.path(), encoding="utf-8") as handle:
        report = json.load(handle)
    assert len(report["comparison"]["ranked"]) == 42
    assert len(report["properties"]) == 2
    page.get_by_role("button", name="View advanced analytics", exact=True).click()
    expect(page.get_by_text("sensitivity", exact=False).first).to_be_visible()
    page.get_by_role("textbox", name="Natural-language request", exact=True).fill("under $1")
    page.get_by_role("button", name="Apply request and numeric filters", exact=True).click()
    expect(page.get_by_text("No saved listings match these filters.", exact=True)).to_be_visible()
    page.get_by_role("textbox", name="Natural-language request", exact=True).fill("")
    page.get_by_role("spinbutton", name="Maximum rent ($/month)", exact=True).fill("1")
    page.get_by_role("button", name="Apply request and numeric filters", exact=True).click()
    expect(page.get_by_text("No saved listings match these filters.", exact=True)).to_be_visible()
    assert sum(len(item["units"]) for item in properties(runtime, user)) == 42
    healthy(page)


def test_free_house_account_and_shared_limit(page, runtime, account):
    user = account("free")
    sign_in(page, runtime, user)
    navigate(page, "Houses")
    save_example(page, "home_example_1.txt", kind="Rental house")
    save_example(page, "home_example_2.txt", kind="Rental house")
    saved = properties(runtime, user)
    assert len(saved) == 2
    assert {item["kind"] for item in saved} == {"rental_home"}
    assert {item["parsed"]["monthly_rent"] for item in saved} == {2245, 2100}
    expect(page.locator('[data-testid="stDataFrame"]')).to_have_count(0)
    expect(page.locator('[data-testid="stDownloadButton"]')).to_have_count(0)
    sign_out(page)
    sign_in(page, runtime, user)
    navigate(page, "Houses")
    expect(page.get_by_role("button", name="Archive property", exact=True)).to_be_visible()
    assert {item["id"] for item in properties(runtime, user)} == {item["id"] for item in saved}
    healthy(page)


def test_free_mixed_account_uses_one_shared_property_allowance(page, runtime, account):
    user = account("free")
    sign_in(page, runtime, user)
    save_example(page, "app_listing_1.txt")
    navigate(page, "Houses")
    save_example(page, "home_example_1.txt", kind="Rental house")
    before = properties(runtime, user)
    assert {item["kind"] for item in before} == {"apartment", "rental_home"}
    assert sum(len(item["units"]) for item in before) == 29
    page.get_by_role("textbox", name="Paste listing text", exact=True).fill(
        (ROOT / "legacy/streamlit/data/home_example_2.txt").read_text()
    )
    page.get_by_role("button", name="Parse listing", exact=True).click()
    page.get_by_role("button", name="Save parsed property", exact=True).click()
    expect(page.get_by_text(re.compile("monthly allowance|account limit"))).to_be_visible()
    assert {item["id"] for item in properties(runtime, user)} == {item["id"] for item in before}
    expect(page.locator('[data-testid="stDownloadButton"]')).to_have_count(0)
    healthy(page)


def test_free_restore_after_reload_respects_shared_limit_and_ownership(page, runtime, account):
    user, other = account("free"), account("free")
    sign_in(page, runtime, user)
    save_example(page, "app_listing_1.txt")
    apartment = properties(runtime, user)[0]
    page.get_by_role("button", name="Archive property", exact=True).click()
    expect(page.get_by_text("Save a listing to begin your comparison.", exact=True)).to_be_visible()
    save_example(page, "home_example_1.txt", kind="Rental house")
    house = next(item for item in properties(runtime, user) if item["kind"] == "rental_home")
    page.reload()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
    page.get_by_text("Archived properties", exact=True).click()
    restore = page.get_by_role("button", name="Restore", exact=True)
    expect(restore).to_be_enabled()
    assert requests.post(runtime["api"] + f"/properties/{apartment['id']}/restore",
                         headers=other["headers"], json={}, timeout=10).status_code == 404
    restore.click()
    expect(restore).to_have_count(0)
    saved = properties(runtime, user)
    assert {item["id"] for item in saved} == {apartment["id"], house["id"]}
    assert all(not item["is_archived"] for item in saved)
    assert len(next(item for item in saved if item["id"] == apartment["id"])["units"]) == 29

    # Fill the released slot with a second house, then reject restoration at capacity.
    assert requests.post(runtime["api"] + f"/properties/{apartment['id']}/archive",
                         headers=user["headers"], json={}, timeout=10).status_code == 200
    page.reload()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
    save_example(page, "home_example_2.txt", kind="Rental house")
    page.reload()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
    page.get_by_text("Archived properties", exact=True).click()
    expect(page.get_by_role("button", name="Restore", exact=True)).to_be_disabled()
    assert requests.post(runtime["api"] + f"/properties/{apartment['id']}/restore",
                         headers=user["headers"], json={}, timeout=10).status_code == 429
    after = properties(runtime, user)
    assert sum(not item["is_archived"] for item in after) == 2
    assert next(item for item in after if item["id"] == apartment["id"])["is_archived"]
    assert properties(runtime, other) == []
    healthy(page)


def test_feedback_browser_submission_reaches_durable_admin_store(page, runtime, account):
    user, admin = account("free"), account("free", admin=True)
    title = "Browser feedback " + uuid4().hex
    description = "Confirm the UI sends feedback to the real API-backed administrator store."
    sign_in(page, runtime, user)
    page.get_by_role("button", name="Report a bug", exact=True).click()
    page.get_by_role("textbox", name="Feedback title", exact=True).fill(title)
    page.get_by_role("textbox", name="Describe the issue or suggestion", exact=True).fill(description)
    page.get_by_role("button", name="Submit feedback", exact=True).click()
    notice = page.get_by_text(re.compile(r"^Feedback saved\. Reference: NA-"))
    expect(notice).to_be_visible()
    reference = notice.inner_text().split("Reference: ", 1)[1].strip()
    response = requests.get(runtime["api"] + "/admin/feedback", headers=admin["headers"], timeout=10)
    assert response.status_code == 200, response.text
    record = next(item for item in response.json() if item["public_reference"] == reference)
    assert record["title"] == title
    assert record["category"] == "bug"
    assert record["status"] == "new"
    engine = create_engine(runtime["database_url"])
    try:
        with engine.connect() as conn:
            stored = conn.execute(text("""
                SELECT user_id, description, contact_email, user_contact_allowed
                FROM feedback_reports WHERE id = :id
            """), {"id": record["id"]}).mappings().one()
        assert stored["user_id"] == user["id"]
        assert stored["description"] == description
        assert stored["contact_email"] is None
        assert stored["user_contact_allowed"] is False
    finally:
        engine.dispose()
    sign_out(page)
    sign_in(page, runtime, user)
    response = requests.get(runtime["api"] + "/admin/feedback", headers=admin["headers"], timeout=10)
    assert response.status_code == 200
    assert any(item["public_reference"] == reference for item in response.json())
    healthy(page)


def test_paid_runtime_advisor_enrichment_commute_and_negotiation(page, runtime, account):
    user = account("premium_plus")
    sign_in(page, runtime, user)
    navigate(page, "Houses")
    save_example(page, "home_example_1.txt", kind="Rental house")

    def usage():
        response = requests.get(runtime["api"] + "/entitlements", headers=user["headers"], timeout=10)
        assert response.status_code == 200, response.text
        return response.json()["usage"]

    sidebar = page.locator('[data-testid="stSidebar"]')
    if sidebar.get_attribute("aria-expanded") == "false":
        page.locator('[data-testid="stExpandSidebarButton"]').click()
    expect(sidebar).to_have_attribute("aria-expanded", "true")
    sidebar.get_by_role("textbox", name="Ask about your saved properties", exact=True).fill(
        "Explain the confirmed listing costs without inventing market statistics."
    )
    sidebar.get_by_role("button", name="Ask advisor", exact=True).click()
    expect(sidebar.get_by_text("MOCK ONLY: compare confirmed costs and request written concessions.", exact=True)).to_be_visible()
    assert usage()["ai"] == 1
    if page.viewport_size["width"] < 600:
        page.locator('[data-testid="stSidebarCollapseButton"]').click()
        expect(sidebar).to_have_attribute("aria-expanded", "false")
    idle(page)
    page.get_by_role("button", name="Enrich neighborhood", exact=True).click()
    expect(page.locator('[data-testid="stJson"]').filter(has_text="mock")).to_be_visible()
    assert usage()["enrichment"] == 1
    page.get_by_role("textbox", name="Destination", exact=True).fill("Washington DC")
    page.get_by_role("button", name="Calculate commute", exact=True).click()
    expect(page.get_by_text(re.compile("Mock mode has no real travel times"))).to_be_visible()
    assert usage()["commute"] == 1
    page.get_by_role("button", name="Generate negotiation guidance", exact=True).click()
    # The advisor already displays identical mock text; wait for a second response.
    expect(page.get_by_text("MOCK ONLY: compare confirmed costs and request written concessions.", exact=True)).to_have_count(2)
    assert usage()["ai"] == 2
    healthy(page)
