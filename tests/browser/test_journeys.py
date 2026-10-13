"""Desktop/mobile journeys through the real Streamlit -> HTTP API boundary."""

import csv
import io
import json
from pathlib import Path
import re
from uuid import uuid4

import requests
from playwright.sync_api import expect

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
    page.get_by_role("button", name="Log out", exact=True).click()
    expect(page.get_by_role("button", name="Log out", exact=True)).to_have_count(0)
    sign_in(page, runtime, {"email": email, "password": "BrowserRegression-9274!"})
    navigate(page, "Profile")
    expect(page.get_by_text(email, exact=True)).to_be_visible()
    expect(page.get_by_role("textbox", name="Display name", exact=True)).to_have_value("Signup Browser Updated")


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
    page.get_by_role("button", name="Log out", exact=True).click()
    sign_in(page, runtime, user)
    assert sum(len(item["units"]) for item in properties(runtime, user)) == 42
    expect(page.get_by_role("heading", name="Saved comparison", exact=True)).to_be_visible()
    navigate(page, "Profile")
    page.get_by_role("tab", name="Preferences", exact=True).click()
    budget = page.get_by_role("spinbutton", name="Max monthly budget ($)", exact=True)
    budget.fill("3500")
    page.get_by_role("button", name="Save preferences", exact=True).click()
    expect(page.get_by_text("Preferences saved to your account.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Log out", exact=True).click()
    sign_in(page, runtime, user)
    navigate(page, "Profile")
    page.get_by_role("tab", name="Preferences", exact=True).click()
    expect(page.get_by_role("spinbutton", name="Max monthly budget ($)", exact=True)).to_have_value("3500")


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
    page.get_by_role("button", name="Log out", exact=True).click()
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
