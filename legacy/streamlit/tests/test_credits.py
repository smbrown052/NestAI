"""
Tests for credits.py — tier system including Premium Plus.

streamlit is not installed in the test environment, so we provide a minimal
mock before importing credits.
"""

import sys
import os
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Minimal streamlit mock ────────────────────────────────────────────────────

class _MockSessionState(dict):
    """Dict-backed session_state that also supports attribute access."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        self[key] = value

    def __contains__(self, key):
        return dict.__contains__(self, key)


_st_mock = types.ModuleType("streamlit")
_st_mock.session_state = _MockSessionState()
_st_mock.markdown = lambda *a, **kw: None
_st_mock.write = lambda *a, **kw: None
_st_mock.warning = lambda *a, **kw: None
_st_mock.success = lambda *a, **kw: None
_st_mock.info = lambda *a, **kw: None
_st_mock.caption = lambda *a, **kw: None
_st_mock.button = lambda *a, **kw: False
_st_mock.rerun = lambda *a, **kw: None
_st_mock.columns = lambda n: [types.SimpleNamespace(
    markdown=lambda *a, **kw: None,
    button=lambda *a, **kw: False,
)] * n

sys.modules["streamlit"] = _st_mock

# ── Import credits after mock is installed ────────────────────────────────────

import pytest


def _fresh_state(**kwargs):
    """Return a clean session_state for a test."""
    defaults = {
        "nestai_tier": "free",
        "nestai_analyses_used": 0,
        "nestai_extra_credits": 0,
        "nestai_enriched_buildings": set(),
    }
    defaults.update(kwargs)
    state = _MockSessionState()
    state.update(defaults)
    return state


# ── Tier definition tests (no session_state needed) ───────────────────────────

class TestTierDefinitions:
    def test_all_three_tiers_defined(self):
        from credits import TIERS
        assert "free" in TIERS
        assert "premium" in TIERS
        assert "premium_plus" in TIERS

    def test_free_has_five_analyses(self):
        from credits import TIERS
        assert TIERS["free"]["analyses"] == 5

    def test_premium_has_hundred_analyses(self):
        from credits import TIERS
        assert TIERS["premium"]["analyses"] == 100

    def test_premium_plus_has_unlimited_analyses(self):
        from credits import TIERS
        assert TIERS["premium_plus"]["analyses"] is None

    def test_free_has_no_ai(self):
        from credits import TIERS
        assert TIERS["free"]["ai_chat"] is False

    def test_premium_has_all_features(self):
        from credits import TIERS
        tier = TIERS["premium"]
        for feature in ("ai_chat", "walk_score", "commute", "neighborhood",
                        "decision_reports", "exports", "negotiation"):
            assert tier[feature] is True, f"premium missing feature: {feature}"

    def test_premium_plus_has_all_features(self):
        from credits import TIERS
        tier = TIERS["premium_plus"]
        for feature in ("ai_chat", "walk_score", "commute", "neighborhood",
                        "decision_reports", "exports", "negotiation"):
            assert tier[feature] is True, f"premium_plus missing feature: {feature}"


# ── Function-level tests (session_state required) ─────────────────────────────

class TestAnalysesLimit:
    def test_free_limit_is_five(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free")
        from credits import analyses_limit
        assert analyses_limit() == 5

    def test_premium_limit_is_hundred(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="premium")
        from credits import analyses_limit
        assert analyses_limit() == 100

    def test_premium_plus_limit_is_none(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="premium_plus")
        from credits import analyses_limit
        assert analyses_limit() is None

    def test_extra_credits_added_to_limit(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free", nestai_extra_credits=50)
        from credits import analyses_limit
        assert analyses_limit() == 55


class TestAnalysesRemaining:
    def test_free_remaining_decreases(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free", nestai_analyses_used=3)
        from credits import analyses_remaining
        assert analyses_remaining() == 2

    def test_free_remaining_floor_at_zero(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free", nestai_analyses_used=10)
        from credits import analyses_remaining
        assert analyses_remaining() == 0

    def test_premium_plus_remaining_is_none(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="premium_plus", nestai_analyses_used=99)
        from credits import analyses_remaining
        assert analyses_remaining() is None


class TestCanEnrichBuilding:
    def test_premium_plus_can_always_enrich(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="premium_plus", nestai_analyses_used=500)
        from credits import can_enrich_building
        assert can_enrich_building("any_building") is True

    def test_free_tier_blocked_at_limit(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free", nestai_analyses_used=5)
        from credits import can_enrich_building
        assert can_enrich_building("new_building") is False

    def test_already_enriched_building_allowed(self):
        import streamlit as st
        st.session_state = _fresh_state(
            nestai_tier="free",
            nestai_analyses_used=5,
            nestai_enriched_buildings={"bldg_abc"},
        )
        from credits import can_enrich_building
        assert can_enrich_building("bldg_abc") is True


class TestConsumeAnalysis:
    def test_premium_plus_consumes_without_limit(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="premium_plus", nestai_analyses_used=999)
        from credits import consume_analysis
        assert consume_analysis("bldg_xyz") is True

    def test_free_tier_fails_when_exhausted(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free", nestai_analyses_used=5)
        from credits import consume_analysis
        assert consume_analysis("bldg_new") is False

    def test_free_tier_succeeds_and_increments(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free", nestai_analyses_used=0)
        from credits import consume_analysis
        result = consume_analysis("bldg_ok")
        assert result is True
        assert st.session_state.nestai_analyses_used == 1

    def test_idempotent_same_building(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free", nestai_analyses_used=4)
        from credits import consume_analysis
        consume_analysis("bldg_repeat")
        count_after_first = st.session_state.nestai_analyses_used
        consume_analysis("bldg_repeat")
        assert st.session_state.nestai_analyses_used == count_after_first  # no double charge


class TestHasFeature:
    def test_premium_plus_has_ai_chat(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="premium_plus")
        from credits import has_feature
        assert has_feature("ai_chat") is True

    def test_free_tier_no_ai_chat(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free")
        from credits import has_feature
        assert has_feature("ai_chat") is False

    def test_parse_always_free(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free")
        from credits import has_feature
        assert has_feature("parse") is True

    def test_premium_has_walk_score(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="premium")
        from credits import has_feature
        assert has_feature("walk_score") is True

    def test_premium_plus_has_negotiation(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="premium_plus")
        from credits import has_feature
        assert has_feature("negotiation") is True


class TestSetTier:
    def test_set_tier_accepts_premium_plus(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free")
        from credits import set_tier, get_tier
        set_tier("premium_plus")
        assert get_tier() == "premium_plus"

    def test_set_tier_accepts_premium(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free")
        from credits import set_tier, get_tier
        set_tier("premium")
        assert get_tier() == "premium"

    def test_set_tier_rejects_unknown(self):
        import streamlit as st
        st.session_state = _fresh_state(nestai_tier="free")
        from credits import set_tier, get_tier
        set_tier("enterprise")  # invalid — should be ignored
        assert get_tier() == "free"

