"""
test_feature_access.py
Tests for feature_access.py — plan capabilities, quota checks, upgrade prompts.
"""

import sys
from pathlib import Path

# Ensure legacy/streamlit is on the path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

# ── Streamlit mock ────────────────────────────────────────────────────────────
# feature_access.py imports streamlit for session_state; mock it so tests
# don't require a running Streamlit server.

import types

class _MockState(dict):
    def __getattr__(self, name):
        return self[name] if name in self else None
    def __setattr__(self, name, value):
        self[name] = value

_mock_st = types.ModuleType("streamlit")
_state = _MockState()
_mock_st.session_state = _state
sys.modules["streamlit"] = _mock_st

import feature_access as fa


def _reset():
    """Clear session state before each test."""
    _state.clear()


# ── Plan defaults ─────────────────────────────────────────────────────────────

class TestDefaults:
    def test_default_plan_is_free(self):
        _reset()
        assert fa.get_plan() == fa.PLAN_FREE

    def test_default_role_is_user(self):
        _reset()
        assert fa.get_role() == fa.ROLE_USER

    def test_not_admin_by_default(self):
        _reset()
        assert fa.is_admin() is False


# ── Free plan capabilities ────────────────────────────────────────────────────

class TestFreePlanCapabilities:
    def setup_method(self):
        _reset()

    def test_can_analyze_property(self):
        assert fa.capability("can_analyze_property") is True

    def test_can_use_basic_filters(self):
        assert fa.capability("can_use_basic_filters") is True

    def test_cannot_use_ai_chat(self):
        assert fa.capability("can_use_ai_chat") is False

    def test_cannot_use_google_apis(self):
        assert fa.capability("can_use_google_apis") is False

    def test_cannot_use_commute_analysis(self):
        assert fa.capability("can_use_commute_analysis") is False

    def test_cannot_compare_multiple_properties(self):
        assert fa.capability("can_compare_multiple_properties") is False

    def test_cannot_generate_ai_reports(self):
        assert fa.capability("can_generate_ai_reports") is False

    def test_monthly_limit_is_5(self):
        assert fa.get_quota("monthly_analyses_limit") == 5

    def test_saved_property_limit_is_1(self):
        assert fa.get_quota("saved_property_limit") == 1


# ── Premium plan capabilities ─────────────────────────────────────────────────

class TestPremiumPlanCapabilities:
    def setup_method(self):
        _reset()
        fa.set_plan(fa.PLAN_PREMIUM)

    def test_can_use_google_apis(self):
        assert fa.capability("can_use_google_apis") is True

    def test_can_use_ai_chat(self):
        assert fa.capability("can_use_ai_chat") is True

    def test_can_compare_multiple_properties(self):
        assert fa.capability("can_compare_multiple_properties") is True

    def test_monthly_limit_is_100(self):
        assert fa.get_quota("monthly_analyses_limit") == 100

    def test_saved_property_limit_is_50(self):
        assert fa.get_quota("saved_property_limit") == 50


# ── Admin override ────────────────────────────────────────────────────────────

class TestAdminRole:
    def setup_method(self):
        _reset()
        _state["nestai_role"] = fa.ROLE_ADMIN

    def test_admin_has_all_capabilities(self):
        # Even if plan is free, admin gets everything
        _state["nestai_plan"] = fa.PLAN_FREE
        assert fa.capability("can_use_google_apis") is True
        assert fa.capability("can_generate_ai_reports") is True

    def test_require_capability_returns_none_for_admin(self):
        assert fa.require_capability("can_use_ai_chat") is None


# ── require_capability ────────────────────────────────────────────────────────

class TestRequireCapability:
    def setup_method(self):
        _reset()

    def test_returns_none_when_allowed(self):
        result = fa.require_capability("can_analyze_property")
        assert result is None

    def test_returns_upgrade_prompt_when_blocked(self):
        prompt = fa.require_capability("can_use_google_apis")
        assert prompt is not None
        assert isinstance(prompt, fa.FeatureUpgradeRequired)
        assert not bool(prompt)   # falsy

    def test_upgrade_prompt_message_mentions_plan(self):
        prompt = fa.require_capability("can_use_ai_chat")
        assert "Premium" in prompt.message
        assert "Free" in prompt.message

    def test_upgrade_prompt_required_plan(self):
        prompt = fa.require_capability("can_use_google_apis")
        assert prompt.required_plan == fa.PLAN_PREMIUM


# ── Quota tracking ────────────────────────────────────────────────────────────

class TestQuotaTracking:
    def setup_method(self):
        _reset()

    def test_initial_remaining_equals_limit(self):
        assert fa.monthly_analyses_remaining() == 5

    def test_consume_deducts_one(self):
        fa.consume_monthly_analysis()
        assert fa.monthly_analyses_remaining() == 4

    def test_cannot_consume_beyond_limit(self):
        for _ in range(5):
            fa.consume_monthly_analysis()
        result = fa.consume_monthly_analysis()
        assert result is False
        assert fa.monthly_analyses_remaining() == 0

    def test_premium_has_more_quota(self):
        fa.set_plan(fa.PLAN_PREMIUM)
        assert fa.monthly_analyses_remaining() == 100


# ── can_save_another_property ─────────────────────────────────────────────────

class TestCanSave:
    def setup_method(self):
        _reset()

    def test_free_can_save_when_zero_active(self):
        assert fa.can_save_another_property(0) is True

    def test_free_cannot_save_when_one_active(self):
        assert fa.can_save_another_property(1) is False

    def test_premium_can_save_up_to_50(self):
        fa.set_plan(fa.PLAN_PREMIUM)
        assert fa.can_save_another_property(49) is True
        assert fa.can_save_another_property(50) is False


# ── Beta overrides ────────────────────────────────────────────────────────────

class TestBetaOverrides:
    def setup_method(self):
        _reset()
        fa.set_plan(fa.PLAN_BETA)

    def test_beta_has_premium_capabilities_by_default(self):
        assert fa.capability("can_use_google_apis") is True

    def test_beta_override_can_restrict_capability(self):
        fa.set_beta_overrides({"can_use_ai_reports": False})
        assert fa.capability("can_use_ai_reports") is False

    def test_beta_override_quota(self):
        fa.set_beta_overrides({"monthly_analyses_limit": 10})
        assert fa.get_quota("monthly_analyses_limit") == 10


# ── Legacy shim ───────────────────────────────────────────────────────────────

class TestLegacyShim:
    def setup_method(self):
        _reset()

    def test_parse_always_allowed(self):
        assert fa.has_feature("parse") is True

    def test_walk_score_blocked_for_free(self):
        assert fa.has_feature("walk_score") is False

    def test_walk_score_allowed_for_premium(self):
        fa.set_plan(fa.PLAN_PREMIUM)
        assert fa.has_feature("walk_score") is True

    def test_commute_blocked_for_free(self):
        assert fa.has_feature("commute") is False
