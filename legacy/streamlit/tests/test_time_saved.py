"""
test_time_saved.py
Tests for time_saved.py — time estimation module.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from time_saved import (
    ASSUMPTIONS,
    SessionActions,
    calculate_minutes,
    format_display,
    build_breakdown,
    get_session_actions,
)


# ── SessionActions defaults ───────────────────────────────────────────────────

class TestSessionActionsDefaults:
    def test_default_is_zero(self):
        a = SessionActions()
        assert a.properties_organized == 0
        assert a.comparisons_done is False
        assert a.decision_reports_generated == 0
        assert a.enrichments_done == 0
        assert a.negotiations_done == 0
        assert a.renewals_done == 0


# ── calculate_minutes ─────────────────────────────────────────────────────────

class TestCalculateMinutes:
    def test_zero_actions_gives_zero(self):
        assert calculate_minutes(SessionActions()) == 0

    def test_negative_output_clamped_to_zero(self):
        a = SessionActions(properties_organized=-5)
        assert calculate_minutes(a) >= 0

    def test_one_property_organized(self):
        a = SessionActions(properties_organized=1)
        expected = ASSUMPTIONS["minutes_per_property_organized"]
        assert calculate_minutes(a) == expected

    def test_two_properties_with_comparison(self):
        a = SessionActions(properties_organized=2, comparisons_done=True)
        expected = (
            2 * ASSUMPTIONS["minutes_per_property_organized"]
            + 1 * ASSUMPTIONS["minutes_per_additional_comparison"]
        )
        assert calculate_minutes(a) == expected

    def test_comparison_not_counted_without_multiple_properties(self):
        # comparisons_done=True but only 1 property — no extra comparison time
        a = SessionActions(properties_organized=1, comparisons_done=True)
        expected = ASSUMPTIONS["minutes_per_property_organized"]
        assert calculate_minutes(a) == expected

    def test_enrichment_adds_minutes(self):
        a = SessionActions(enrichments_done=3)
        expected = 3 * ASSUMPTIONS["minutes_per_enrichment"]
        assert calculate_minutes(a) == expected

    def test_negotiation_adds_minutes(self):
        a = SessionActions(negotiations_done=2)
        expected = 2 * ASSUMPTIONS["minutes_per_negotiation"]
        assert calculate_minutes(a) == expected

    def test_decision_reports_adds_minutes(self):
        a = SessionActions(decision_reports_generated=1)
        expected = ASSUMPTIONS["minutes_per_decision_report"]
        assert calculate_minutes(a) == expected

    def test_renewal_adds_minutes(self):
        a = SessionActions(renewals_done=1)
        expected = ASSUMPTIONS["minutes_per_renewal"]
        assert calculate_minutes(a) == expected

    def test_all_actions_sum_correctly(self):
        a = SessionActions(
            properties_organized=3,
            comparisons_done=True,
            decision_reports_generated=1,
            enrichments_done=2,
            negotiations_done=1,
            renewals_done=0,
        )
        expected = (
            3 * ASSUMPTIONS["minutes_per_property_organized"]
            + 2 * ASSUMPTIONS["minutes_per_additional_comparison"]  # 3-1=2 extra
            + 1 * ASSUMPTIONS["minutes_per_decision_report"]
            + 2 * ASSUMPTIONS["minutes_per_enrichment"]
            + 1 * ASSUMPTIONS["minutes_per_negotiation"]
        )
        assert calculate_minutes(a) == expected

    def test_custom_assumptions(self):
        custom = {k: 1 for k in ASSUMPTIONS}
        a = SessionActions(
            properties_organized=2,
            comparisons_done=True,
            negotiations_done=1,
        )
        # 2 props * 1 + 1 extra comparison * 1 + 1 negotiation * 1 = 4
        assert calculate_minutes(a, assumptions=custom) == 4

    def test_no_double_counting_enrichment_and_properties(self):
        # Three separate properties + three enrichments should not double-count
        a = SessionActions(properties_organized=3, enrichments_done=3)
        result = calculate_minutes(a)
        props_cost = 3 * ASSUMPTIONS["minutes_per_property_organized"]
        enrich_cost = 3 * ASSUMPTIONS["minutes_per_enrichment"]
        assert result == props_cost + enrich_cost


# ── format_display ────────────────────────────────────────────────────────────

class TestFormatDisplay:
    def test_zero_returns_zero_min(self):
        assert format_display(0) == "0 min"

    def test_negative_returns_zero_min(self):
        assert format_display(-5) == "0 min"

    def test_under_one_hour(self):
        assert format_display(45) == "45 min"

    def test_exactly_one_hour(self):
        assert format_display(60) == "1 hr"

    def test_over_one_hour_with_remainder(self):
        assert format_display(90) == "1 hr 30 min"

    def test_two_hours(self):
        assert format_display(120) == "2 hr"

    def test_one_hr_42_min(self):
        assert format_display(102) == "1 hr 42 min"


# ── build_breakdown ───────────────────────────────────────────────────────────

class TestBuildBreakdown:
    def test_empty_returns_empty_list(self):
        assert build_breakdown(SessionActions()) == []

    def test_properties_appears(self):
        a = SessionActions(properties_organized=2)
        lines = build_breakdown(a)
        assert any("propert" in line for line in lines)

    def test_comparison_appears_with_multiple_properties(self):
        a = SessionActions(properties_organized=3, comparisons_done=True)
        lines = build_breakdown(a)
        assert any("comparison" in line for line in lines)

    def test_comparison_absent_with_single_property(self):
        a = SessionActions(properties_organized=1, comparisons_done=True)
        lines = build_breakdown(a)
        assert not any("comparison" in line for line in lines)

    def test_negotiation_appears(self):
        a = SessionActions(negotiations_done=1)
        lines = build_breakdown(a)
        assert any("negotiation" in line for line in lines)

    def test_enrichment_appears(self):
        a = SessionActions(enrichments_done=2)
        lines = build_breakdown(a)
        assert any("enrichment" in line for line in lines)

    def test_singular_property_label(self):
        a = SessionActions(properties_organized=1)
        lines = build_breakdown(a)
        assert any("property" in line.lower() and "properties" not in line.lower() for line in lines)

    def test_plural_properties_label(self):
        a = SessionActions(properties_organized=3)
        lines = build_breakdown(a)
        assert any("properties" in line for line in lines)


# ── get_session_actions ───────────────────────────────────────────────────────

class TestGetSessionActions:
    def _mock_state(self, **kwargs):
        """Return a simple dict-like object acting as session_state."""
        class _S(dict):
            def get(self, k, d=None):
                return super().get(k, d)
            @property
            def empty(self):
                return len(self) == 0

        import pandas as pd

        s = _S()
        s["comparison_df"] = kwargs.get("comparison_df", pd.DataFrame())
        s["building_cache"] = kwargs.get("building_cache", {})
        s["enrichment_done"] = kwargs.get("enrichment_done", False)
        s["negotiation_outputs"] = kwargs.get("negotiation_outputs", {})
        s["nestai_ts_reports_generated"] = kwargs.get("nestai_ts_reports_generated", 0)
        s["nestai_ts_renewals_done"] = kwargs.get("nestai_ts_renewals_done", 0)
        return s

    def test_empty_state_gives_zero_actions(self):
        import pandas as pd
        state = self._mock_state()
        actions = get_session_actions(state)
        assert actions.properties_organized == 0
        assert actions.comparisons_done is False

    def test_two_properties_gives_comparison_true(self):
        import pandas as pd
        df = pd.DataFrame([{"unit": "1A"}, {"unit": "1B"}])
        state = self._mock_state(comparison_df=df)
        actions = get_session_actions(state)
        assert actions.properties_organized == 2
        assert actions.comparisons_done is True

    def test_enrichment_counted_when_done(self):
        state = self._mock_state(
            enrichment_done=True,
            building_cache={"addr1": {}, "addr2": {}},
        )
        actions = get_session_actions(state)
        assert actions.enrichments_done == 2

    def test_enrichment_not_counted_when_not_done(self):
        state = self._mock_state(
            enrichment_done=False,
            building_cache={"addr1": {}},
        )
        actions = get_session_actions(state)
        assert actions.enrichments_done == 0

    def test_negotiations_counted(self):
        state = self._mock_state(
            negotiation_outputs={"key1": "script", "key2": "script"},
        )
        actions = get_session_actions(state)
        assert actions.negotiations_done == 2

    def test_reports_from_session_state(self):
        state = self._mock_state(nestai_ts_reports_generated=3)
        actions = get_session_actions(state)
        assert actions.decision_reports_generated == 3
