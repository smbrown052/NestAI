"""Readable UI projections must never rewrite the API download payloads."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Keep the runner's generated script files in the project, never system temp.
with patch("tempfile.TemporaryDirectory", return_value=SimpleNamespace(name=str(ROOT))):
    from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "legacy" / "streamlit"))

import api_views
from shared.decision import rank_rows, sensitivity
from shared.entitlement_copy import free_plan_summary
from text_parser import parse_apartment_text
from parser.home_listing import parse_home_listing_text


@pytest.fixture(autouse=True)
def project_test_scripts(monkeypatch):
    import streamlit.testing.v1.app_test as app_test
    before = set(ROOT.iterdir())
    monkeypatch.setattr(app_test, "TMP_DIR", SimpleNamespace(name=str(ROOT)))
    yield
    for path in set(ROOT.iterdir()) - before:
        if path.is_file() and len(path.name) == 32 and all(char in "0123456789abcdef" for char in path.name):
            path.unlink()


def ui_script(body):
    return (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        f"sys.path.insert(0, {str(ROOT / 'legacy' / 'streamlit')!r})\n"
        "import streamlit as st\n"
        "from api_views import *\n"
        + body
    )


def assert_readable(app):
    assert not app.exception
    assert not app.get("json")
    assert not app.code


@pytest.mark.parametrize("item,noun,expected", [
    ({"units": [{"beds_num": 0}, {"beds_num": 2}]}, "bed", "0–2 beds"),
    ({"units": [{"baths_num": 1}, {"baths_num": 1.5}, {}]}, "bath", "1–1.5 baths"),
    ({"bedrooms": 99, "units": [{"parsed": {"beds_num": 1}}, {"beds": 2}]}, "bed", "1–2 beds"),
    ({"units": [{"beds_num": None, "beds": "Studio"}, {"beds_num": 0}]}, "bed", "0 beds"),
    ({"parsed": {"bathrooms": 1.5}}, "bath", "1.5 baths"),
    ({"units": [{"beds_num": None}, {"beds_num": float("nan")}]}, "bed", "Beds unknown"),
    ({}, "bath", "Baths unknown"),
    ({"bedrooms": 0}, "bed", "0 beds"),
])
def test_room_summary_known_ranges_and_missing_values(item, noun, expected):
    before = deepcopy(item)
    assert api_views.room_summary(item, noun) == expected
    # NaN is not equal to itself, so use its serialized representation.
    assert json.dumps(item, sort_keys=True) == json.dumps(before, sort_keys=True)


@pytest.mark.parametrize("fixture", ["app_listing_1.txt", "app_listing_2.txt"])
def test_real_apartment_preview_is_readable_and_free_has_no_downloads(fixture):
    parsed = parse_apartment_text((ROOT / "legacy/streamlit/data" / fixture).read_text())
    app = AppTest.from_string(ui_script(
        f"parsed = {parsed!r}\n"
        "st.session_state.auth_token = 'test'\n"
        "st.session_state.account_entitlements = {'plan': 'free', 'capabilities': {'can_export': False}}\n"
        "render_listing_preview(parsed)\n"
        "st.session_state.preview_after = parsed\n"
    )).run()
    assert_readable(app)
    assert app.subheader[0].value == "Parsed listing preview"
    assert app.metric[0].value == api_views.room_summary(parsed, "bed")
    assert app.metric[1].value == api_views.room_summary(parsed, "bath")
    assert "unknown" not in app.metric[0].value.lower()
    assert len(app.table[0].value) == len(parsed["units"])
    assert app.table[0].value["Unit"].tolist() == [unit["unit"] for unit in parsed["units"]]
    assert not app.dataframe
    assert not app.get("download_button")
    assert app.session_state.preview_after == parsed


@pytest.mark.parametrize("fixture", ["home_example_1.txt", "home_example_2.txt"])
def test_house_preview_has_readable_price_rooms_and_area(fixture):
    parsed = vars(parse_home_listing_text((ROOT / "legacy/streamlit/data" / fixture).read_text()))
    app = AppTest.from_string(ui_script(f"render_listing_preview({parsed!r})")).run()
    assert_readable(app)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Bedrooms"] == api_views.number_label(parsed["bedrooms"], "bed")
    assert metrics["Bathrooms"] == api_views.number_label(parsed["bathrooms"], "bath")
    assert metrics["Monthly rent"] == f"${parsed['monthly_rent']:,.0f}"
    assert metrics["Square feet"] == f"{parsed['square_feet']:g}"


def snapshot():
    rows = [
        {"property_id": "second", "unit_id": "0002", "property": "Second property", "unit": "0002",
         "price_num": 2100, "sqft_num": 780, "beds_num": 0, "baths_num": 1.5},
        {"property_id": "first", "unit_id": "0001", "property": "First property", "unit": "0001",
         "price_num": 2245, "sqft_num": 805, "beds_num": 2, "baths_num": 2},
    ]
    ranked = rank_rows(rows, {"price": 4, "space": 1})
    comparison = {"ranked": ranked, "warnings": ["Unknown facts use neutral contributions."]}
    return {
        "report_level": "plus", "comparison": comparison,
        "properties": [{"id": row["property_id"], "units": [{"id": row["unit_id"]}]} for row in ranked],
        "analytics": {"baseline": comparison, "sensitivity": sensitivity(rows, {"price": 4, "space": 1})},
        "disclaimer": "Listing facts are not independently verified.",
    }


def test_report_and_analytics_render_sections_table_chart_without_mutation():
    data = snapshot()
    report = {"content": json.dumps(data), "report_id": "snapshot-report", "filename": "report.json",
              "media_type": "application/json"}
    app = AppTest.from_string(ui_script(
        f"report = {report!r}\n"
        "render_decision_report(report)\n"
        "st.session_state.report_after = report\n"
    )).run()
    assert_readable(app)
    assert [heading.value for heading in app.subheader] == ["Decision report", "Advanced analytics"]
    markdown = [entry.value for entry in app.markdown]
    assert "#### Top recommendation" in markdown
    assert "#### Strengths" in markdown
    assert "#### Tradeoffs" in markdown
    assert "#### Unknown facts" in markdown
    assert "#### Priority sensitivity" in markdown
    assert any("$145/mo less expensive" in entry for entry in markdown)
    assert any("25 sq ft less space" in entry for entry in markdown)
    assert app.get("vega_lite_chart") or app.get("arrow_vega_lite_chart")
    ranked = data["comparison"]["ranked"]
    tables = app.table
    assert tables[0].value["Unit"].tolist() == [row["unit"] for row in ranked]
    assert tables[0].value["Property"].tolist() == [row["property"] for row in ranked]
    assert app.session_state.report_after == report


@pytest.mark.parametrize("content", ["not json", "[]", "null"])
def test_invalid_report_preview_fails_gracefully(content):
    report = {"content": content}
    app = AppTest.from_string(ui_script(f"render_decision_report({report!r})")).run()
    assert_readable(app)
    assert "original report download is unchanged" in app.warning[0].value


def test_empty_analytics_has_no_fabricated_winner_or_chart():
    app = AppTest.from_string(ui_script("render_analytics({'baseline': {'ranked': []}, 'sensitivity': []})")).run()
    assert_readable(app)
    assert [entry.value for entry in app.info] == [
        "No eligible listings in this snapshot.", "No sensitivity scenarios available.",
    ]
    assert not app.get("arrow_vega_lite_chart")
    assert not app.get("vega_lite_chart")


def test_report_download_identity_and_analytics_survive_reruns_until_filters_change():
    data = snapshot()
    report = {"content": json.dumps(data), "report_id": "snapshot-report", "filename": "report.json",
              "media_type": "application/json"}
    script = ui_script(
        f"report = {report!r}\n"
        f"data = {data!r}\n"
        "class Response:\n"
        "    status_code = 200\n"
        "    text = report['content']\n"
        "    def __init__(self, payload): self.payload = payload\n"
        "    def json(self): return self.payload\n"
        "class Client:\n"
        "    def request(self, method, path, json=None):\n"
        "        st.session_state.setdefault('requests_seen', []).append((method, path, json))\n"
        "        return Response({'/ranking': data['comparison'], '/reports': report,\n"
        "                         '/analytics': data['analytics']}.get(path, {}))\n"
        "st.session_state.auth_token = 'test'\n"
        "st.session_state.account_entitlements = {'plan': 'premium_plus', 'capabilities': {\n"
        "    'can_export': True, 'can_generate_ai_reports': True}}\n"
        "render_comparison(Client(), [{'id': 'second'}, {'id': 'first'}])\n"
    )
    app = AppTest.from_string(script).run()
    assert_readable(app)
    next(button for button in app.button if button.label == "Generate decision report").click().run()
    assert_readable(app)
    assert app.session_state["account_report"] == report
    assert json.loads(app.session_state["account_report"]["content"]) == data
    assert ("GET", "/reports/snapshot-report/download", None) in app.session_state["requests_seen"]
    assert [element.proto.label for element in app.get("download_button")] == ["Download report"]
    next(button for button in app.button if button.label == "View advanced analytics").click().run()
    assert_readable(app)
    assert app.session_state["account_analytics"] == data["analytics"]
    # An unrelated widget rerun must not discard the paid analytics result.
    next(box for box in app.selectbox if box.label == "Listing details").select_index(1).run()
    assert_readable(app)
    assert app.session_state["account_analytics"] == data["analytics"]
    assert app.session_state["account_report"] == report
    next(button for button in app.button if button.label == "Reset filters").click().run()
    assert_readable(app)
    assert "account_report" not in app.session_state
    assert "account_analytics" not in app.session_state
    assert not app.get("download_button")


def test_free_landing_copy_uses_contract_and_does_not_claim_enrichment(monkeypatch):
    monkeypatch.setenv("NESTAI_QUOTA_FREE_PROPERTIES", "3")
    assert free_plan_summary() == (
        "Free accounts can save and compare up to 3 properties. "
        "Neighborhood enrichment and commute analysis require Premium or Premium Plus."
    )
    source = (ROOT / "legacy/streamlit/app.py").read_text()
    assert "st.info(free_plan_summary())" in source
    assert "Free accounts can fully compare and enrich" not in source


def test_clear_stale_analytics_with_comparison_downloads(monkeypatch):
    state = {key: "old" for key in ["account_report", "account_export", "account_export_scope", "account_analytics"]}
    state["account_properties"] = ["preserve"]
    monkeypatch.setattr(api_views.st, "session_state", state)
    api_views.clear_comparison_downloads()
    assert state == {"account_properties": ["preserve"]}
