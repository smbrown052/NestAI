"""
test_plan_ui.py
Tests for the OWNER_TEST plan, plan_ui data helpers, dev-mode switching,
and upgrade prompt logic.

These tests do NOT render Streamlit widgets.  They verify the underlying
data and logic that the UI components rely on.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure legacy/streamlit is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
import types


# ── Streamlit mock ────────────────────────────────────────────────────────────
# If a previous test file already injected a streamlit mock, reuse it so that
# feature_access.py's module-level `import streamlit as st` stays bound to the
# same mock object.  Creating a second mock would cause _state mutations here
# to be invisible inside feature_access.

class _MockState(dict):
    def __getattr__(self, name):
        return self[name] if name in self else None

    def __setattr__(self, name, value):
        self[name] = value

    def get(self, name, default=None):
        return self[name] if name in self else default


class _NullCtx:
    def __enter__(self):
        return self
    def __exit__(self, *a):
        pass


if "streamlit" not in sys.modules:
    _mock_st = types.ModuleType("streamlit")
    _mock_st.session_state = _MockState()
    sys.modules["streamlit"] = _mock_st

# Ensure the mock has all widget stubs plan_ui needs (add only if missing)
_mock_st = sys.modules["streamlit"]
for _attr, _stub in [
    ("container", lambda **kw: _NullCtx()),
    ("expander", lambda *a, **kw: _NullCtx()),
    ("columns", lambda n: [_NullCtx() for _ in range(n if isinstance(n, int) else len(n))]),
    ("button", lambda *a, **kw: False),
    ("selectbox", lambda *a, **kw: None),
    ("markdown", lambda *a, **kw: None),
    ("caption", lambda *a, **kw: None),
    ("warning", lambda *a, **kw: None),
    ("info", lambda *a, **kw: None),
    ("success", lambda *a, **kw: None),
    ("divider", lambda **kw: None),
    ("rerun", lambda: None),
]:
    if not hasattr(_mock_st, _attr):
        setattr(_mock_st, _attr, _stub)

import feature_access as fa
from plan_ui import get_pricing_plans, PRICING_PLANS, PLAN_FREE, PLAN_PREMIUM, PLAN_PREMIUM_PLUS

# Always use the same session_state object that feature_access.py is bound to.
_state = fa.st.session_state


def _reset():
    _state.clear()


# ── OWNER_TEST constant ───────────────────────────────────────────────────────

class TestOwnerTestConstant:
    def test_owner_test_plan_constant_exists(self):
        assert fa.PLAN_OWNER_TEST == "OWNER_TEST"

    def test_owner_test_in_all_plans(self):
        assert fa.PLAN_OWNER_TEST in fa._ALL_PLANS

    def test_owner_test_has_label(self):
        assert fa._PLAN_LABELS.get(fa.PLAN_OWNER_TEST) is not None


# ── OWNER_TEST capabilities ───────────────────────────────────────────────────

class TestOwnerTestCapabilities:
    def setup_method(self):
        _reset()
        os.environ.pop("NESTAI_OWNER_MODE", None)
        os.environ.pop("NESTAI_DEV_MODE", None)

    def teardown_method(self):
        os.environ.pop("NESTAI_OWNER_MODE", None)
        os.environ.pop("NESTAI_DEV_MODE", None)

    def _set_owner_test(self):
        _state["nestai_plan"] = fa.PLAN_OWNER_TEST

    def test_owner_test_grants_ai_chat(self):
        self._set_owner_test()
        assert fa.capability("can_use_ai_chat") is True

    def test_owner_test_grants_google_apis(self):
        self._set_owner_test()
        assert fa.capability("can_use_google_apis") is True

    def test_owner_test_grants_commute(self):
        self._set_owner_test()
        assert fa.capability("can_use_commute_analysis") is True

    def test_owner_test_grants_ai_reports(self):
        self._set_owner_test()
        assert fa.capability("can_generate_ai_reports") is True

    def test_owner_test_grants_comparison(self):
        self._set_owner_test()
        assert fa.capability("can_compare_multiple_properties") is True

    def test_owner_test_grants_natural_language_filtering(self):
        self._set_owner_test()
        assert fa.capability("can_use_natural_language_filtering") is True

    def test_owner_test_grants_lifestyle_score(self):
        self._set_owner_test()
        assert fa.capability("can_use_lifestyle_score") is True

    def test_owner_test_grants_walk_score(self):
        self._set_owner_test()
        assert fa.capability("can_use_walk_score_api") is True

    def test_owner_test_grants_export(self):
        self._set_owner_test()
        assert fa.capability("can_export") is True

    def test_owner_test_grants_negotiation(self):
        self._set_owner_test()
        assert fa.capability("can_use_ai_negotiation") is True

    def test_owner_test_grants_save_property(self):
        self._set_owner_test()
        assert fa.capability("can_save_property") is True

    def test_owner_test_require_capability_returns_none(self):
        self._set_owner_test()
        assert fa.require_capability("can_use_google_apis") is None
        assert fa.require_capability("can_use_ai_chat") is None
        assert fa.require_capability("can_compare_multiple_properties") is None


# ── OWNER_TEST quotas are unlimited (None) ────────────────────────────────────

class TestOwnerTestQuotas:
    def setup_method(self):
        _reset()
        os.environ.pop("NESTAI_OWNER_MODE", None)
        _state["nestai_plan"] = fa.PLAN_OWNER_TEST

    def teardown_method(self):
        os.environ.pop("NESTAI_OWNER_MODE", None)

    def test_analyses_quota_is_none(self):
        assert fa.get_quota("monthly_analyses_limit") is None

    def test_saved_property_quota_is_none(self):
        assert fa.get_quota("saved_property_limit") is None

    def test_monthly_analyses_remaining_is_none(self):
        assert fa.monthly_analyses_remaining() is None

    def test_can_save_unlimited_properties(self):
        assert fa.can_save_another_property(0) is True
        assert fa.can_save_another_property(9999) is True

    def test_consume_monthly_analysis_returns_true(self):
        result = fa.consume_monthly_analysis()
        assert result is True

    def test_consume_does_not_increment_counter(self):
        fa.consume_monthly_analysis()
        fa.consume_monthly_analysis()
        assert _state.get("nestai_analyses_used_month", 0) == 0

    def test_is_owner_test_returns_true(self):
        assert fa.is_owner_test() is True


# ── Free plan remains restricted ──────────────────────────────────────────────

class TestFreePlanRestrictions:
    def setup_method(self):
        _reset()
        os.environ.pop("NESTAI_OWNER_MODE", None)

    def teardown_method(self):
        os.environ.pop("NESTAI_OWNER_MODE", None)

    def test_free_cannot_use_ai_chat(self):
        assert fa.capability("can_use_ai_chat") is False

    def test_free_cannot_use_google_apis(self):
        assert fa.capability("can_use_google_apis") is False

    def test_free_cannot_compare(self):
        assert fa.capability("can_compare_multiple_properties") is False

    def test_free_analyses_quota_is_5(self):
        assert fa.get_quota("monthly_analyses_limit") == 5

    def test_free_saved_limit_is_1(self):
        assert fa.get_quota("saved_property_limit") == 1

    def test_free_monthly_remaining_is_int(self):
        remaining = fa.monthly_analyses_remaining()
        assert isinstance(remaining, int)

    def test_free_cannot_save_second_property(self):
        assert fa.can_save_another_property(1) is False

    def test_free_is_owner_test_returns_false(self):
        assert fa.is_owner_test() is False

    def test_free_require_capability_returns_prompt(self):
        prompt = fa.require_capability("can_use_ai_chat")
        assert isinstance(prompt, fa.FeatureUpgradeRequired)
        assert not bool(prompt)

    def test_free_upgrade_prompt_mentions_plans(self):
        prompt = fa.require_capability("can_use_ai_chat")
        assert "Premium" in prompt.message
        assert "Free" in prompt.message


# ── OWNER_TEST activation via env var ─────────────────────────────────────────

class TestOwnerModeEnvVar:
    def setup_method(self):
        _reset()
        os.environ.pop("NESTAI_OWNER_MODE", None)

    def teardown_method(self):
        os.environ.pop("NESTAI_OWNER_MODE", None)

    def test_owner_mode_env_false_by_default(self):
        assert fa.is_owner_mode_env() is False

    def test_owner_mode_env_true_when_set(self):
        os.environ["NESTAI_OWNER_MODE"] = "true"
        assert fa.is_owner_mode_env() is True

    def test_owner_mode_env_true_case_insensitive(self):
        os.environ["NESTAI_OWNER_MODE"] = "TRUE"
        assert fa.is_owner_mode_env() is True

    def test_owner_mode_env_forces_owner_test_plan(self):
        os.environ["NESTAI_OWNER_MODE"] = "true"
        fa._init()
        assert _state.get("nestai_plan") == fa.PLAN_OWNER_TEST

    def test_owner_mode_env_grants_all_capabilities(self):
        os.environ["NESTAI_OWNER_MODE"] = "true"
        assert fa.capability("can_use_google_apis") is True
        assert fa.capability("can_generate_ai_reports") is True

    def test_owner_mode_env_overrides_free_session_state(self):
        _state["nestai_plan"] = fa.PLAN_FREE
        os.environ["NESTAI_OWNER_MODE"] = "true"
        fa._init()
        assert _state.get("nestai_plan") == fa.PLAN_OWNER_TEST

    def test_session_state_cannot_override_owner_mode_env(self):
        os.environ["NESTAI_OWNER_MODE"] = "true"
        fa._init()
        # Even after forcing plan back to FREE, _init re-applies OWNER_TEST
        _state["nestai_plan"] = fa.PLAN_FREE
        fa._init()
        assert _state.get("nestai_plan") == fa.PLAN_OWNER_TEST


# ── Dev mode env var ──────────────────────────────────────────────────────────

class TestDevModeEnvVar:
    def setup_method(self):
        _reset()
        os.environ.pop("NESTAI_DEV_MODE", None)
        os.environ.pop("NESTAI_OWNER_MODE", None)

    def teardown_method(self):
        os.environ.pop("NESTAI_DEV_MODE", None)
        os.environ.pop("NESTAI_OWNER_MODE", None)

    def test_dev_mode_false_by_default(self):
        assert fa.is_dev_mode() is False

    def test_dev_mode_true_when_set(self):
        os.environ["NESTAI_DEV_MODE"] = "true"
        assert fa.is_dev_mode() is True

    def test_dev_mode_allows_set_plan_owner_test(self):
        os.environ["NESTAI_DEV_MODE"] = "true"
        fa.set_plan(fa.PLAN_OWNER_TEST)
        assert fa.get_plan() == fa.PLAN_OWNER_TEST

    def test_set_plan_owner_test_blocked_without_flags(self):
        # Neither DEV nor OWNER mode — set_plan(OWNER_TEST) must be a no-op
        fa._init()  # ensures nestai_plan = FREE (default)
        fa.set_plan(fa.PLAN_OWNER_TEST)
        assert fa.get_plan() == fa.PLAN_FREE

    def test_dev_mode_allows_plan_switching(self):
        os.environ["NESTAI_DEV_MODE"] = "true"
        fa.set_plan(fa.PLAN_PREMIUM)
        assert fa.get_plan() == fa.PLAN_PREMIUM
        fa.set_plan(fa.PLAN_FREE)
        assert fa.get_plan() == fa.PLAN_FREE

    def test_switching_to_premium_unlocks_capabilities(self):
        os.environ["NESTAI_DEV_MODE"] = "true"
        fa.set_plan(fa.PLAN_PREMIUM)
        assert fa.capability("can_use_ai_chat") is True
        assert fa.capability("can_compare_multiple_properties") is True

    def test_switching_back_to_free_re_locks_capabilities(self):
        os.environ["NESTAI_DEV_MODE"] = "true"
        fa.set_plan(fa.PLAN_PREMIUM)
        fa.set_plan(fa.PLAN_FREE)
        assert fa.capability("can_use_ai_chat") is False


# ── Pricing cards do not include OWNER_TEST ───────────────────────────────────

class TestPricingCards:
    def test_get_pricing_plans_returns_three_plans(self):
        plans = get_pricing_plans()
        assert len(plans) == 3

    def test_pricing_plans_are_free_premium_premium_plus(self):
        ids = [p["id"] for p in get_pricing_plans()]
        assert PLAN_FREE in ids
        assert PLAN_PREMIUM in ids
        assert PLAN_PREMIUM_PLUS in ids

    def test_pricing_plans_exclude_owner_test(self):
        ids = [p["id"] for p in get_pricing_plans()]
        assert fa.PLAN_OWNER_TEST not in ids

    def test_pricing_plans_exclude_beta(self):
        ids = [p["id"] for p in get_pricing_plans()]
        assert fa.PLAN_BETA not in ids

    def test_free_plan_card_has_features(self):
        free_card = next(p for p in PRICING_PLANS if p["id"] == PLAN_FREE)
        assert len(free_card["features"]) > 0

    def test_premium_card_has_highlight(self):
        premium_card = next(p for p in PRICING_PLANS if p["id"] == PLAN_PREMIUM)
        assert premium_card.get("highlight") is True

    def test_premium_plus_card_has_features(self):
        pp_card = next(p for p in PRICING_PLANS if p["id"] == PLAN_PREMIUM_PLUS)
        assert len(pp_card["features"]) > 0

    def test_free_card_has_not_included(self):
        free_card = next(p for p in PRICING_PLANS if p["id"] == PLAN_FREE)
        assert "not_included" in free_card
        assert len(free_card["not_included"]) > 0

    def test_free_plan_price_is_zero(self):
        free_card = next(p for p in PRICING_PLANS if p["id"] == PLAN_FREE)
        assert "$0" in free_card["price"]

    def test_premium_plan_has_price(self):
        card = next(p for p in PRICING_PLANS if p["id"] == PLAN_PREMIUM)
        assert "$" in card["price"]

    def test_premium_plus_plan_has_higher_price_than_premium(self):
        premium = next(p for p in PRICING_PLANS if p["id"] == PLAN_PREMIUM)
        pp = next(p for p in PRICING_PLANS if p["id"] == PLAN_PREMIUM_PLUS)
        premium_price = int(premium["price"].replace("$", ""))
        pp_price = int(pp["price"].replace("$", ""))
        assert pp_price > premium_price


# ── credits.py OWNER_TEST bypass ─────────────────────────────────────────────

class TestCreditsBypassOwnerTest:
    """Verify that credits.py honours NESTAI_OWNER_MODE."""

    def setup_method(self):
        _reset()
        os.environ.pop("NESTAI_OWNER_MODE", None)

    def teardown_method(self):
        os.environ.pop("NESTAI_OWNER_MODE", None)

    def test_has_feature_walk_score_owner_mode(self):
        os.environ["NESTAI_OWNER_MODE"] = "true"
        import credits
        assert credits.has_feature("walk_score") is True

    def test_has_feature_commute_owner_mode(self):
        os.environ["NESTAI_OWNER_MODE"] = "true"
        import credits
        assert credits.has_feature("commute") is True

    def test_analyses_remaining_unlimited_owner_mode(self):
        os.environ["NESTAI_OWNER_MODE"] = "true"
        import credits
        _state["nestai_analyses_used"] = 100
        assert credits.analyses_remaining() > 0

    def test_can_enrich_building_owner_mode(self):
        os.environ["NESTAI_OWNER_MODE"] = "true"
        import credits
        _state["nestai_analyses_used"] = 100
        assert credits.can_enrich_building("any-building-id") is True

    def test_consume_analysis_owner_mode_does_not_deduct(self):
        os.environ["NESTAI_OWNER_MODE"] = "true"
        import credits
        _state["nestai_analyses_used"] = 0
        credits.consume_analysis("building-123")
        assert _state.get("nestai_analyses_used", 0) == 0

    def test_has_feature_blocked_free_no_owner_mode(self):
        import credits
        _state["nestai_tier"] = "free"
        assert credits.has_feature("walk_score") is False
