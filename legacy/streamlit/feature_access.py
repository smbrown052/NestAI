"""
feature_access.py
Centralized plan/role/capability service for NestAI.

NOTE (local/session-based enforcement):
    Plan state is stored in Streamlit session_state and is therefore
    session-scoped, not account-backed.  This is intentional for the
    current Streamlit-only deployment.  All capability checks are
    designed behind a clean interface so the backing store can later
    be replaced by an API-driven identity/quota service without
    changing call sites.

    Controls in this module are LOCAL and not production-grade until
    they are backed by a server-side identity layer.

Roles (separate from plans):
    USER    — default application user
    ADMIN   — platform operator (not a subscription plan)

Plans:
    FREE          — limited analyses, local-only features
    PREMIUM       — paid tier, all core features
    PREMIUM_PLUS  — paid tier, higher quotas + advanced features
    BETA          — admin-granted, configurable quotas + expiration

Usage::

    from feature_access import capability, require_capability, FeatureUpgradeRequired
    if capability("can_compare_multiple_properties"):
        ...  # show comparison UI
    else:
        prompt = require_capability("can_compare_multiple_properties")
        # prompt.message describes the upgrade needed
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import streamlit as st

# ── Plan and role constants ───────────────────────────────────────────────────

PLAN_FREE = "FREE"
PLAN_PREMIUM = "PREMIUM"
PLAN_PREMIUM_PLUS = "PREMIUM_PLUS"
PLAN_BETA = "BETA"

ROLE_USER = "USER"
ROLE_ADMIN = "ADMIN"

_ALL_PLANS = {PLAN_FREE, PLAN_PREMIUM, PLAN_PREMIUM_PLUS, PLAN_BETA}

# ── Per-plan capability and quota definitions ─────────────────────────────────

_CAPABILITIES: dict[str, dict[str, Any]] = {
    PLAN_FREE: {
        # Analyses
        "can_analyze_property": True,
        "monthly_analyses_limit": 5,
        # Saved properties
        "can_save_property": True,
        "saved_property_limit": 1,          # one active saved property
        "can_restore_archived_property": False,
        # Comparison
        "can_compare_multiple_properties": False,
        # Filtering
        "can_use_basic_filters": True,
        "can_use_natural_language_filtering": False,
        # AI features
        "can_use_lifestyle_score": False,
        "can_use_ai_explanations": False,
        "can_generate_ai_reports": False,
        # External API features — MUST be false for Free
        "can_use_google_apis": False,
        "can_use_commute_analysis": False,
        "can_use_neighborhood_enrichment": False,
        # Walk Score (via paid Walk Score API)
        "can_use_walk_score_api": False,
        # Chat
        "can_use_ai_chat": False,
        # Exports
        "can_export": False,
        # Negotiation
        "can_use_ai_negotiation": False,
    },
    PLAN_PREMIUM: {
        "can_analyze_property": True,
        "monthly_analyses_limit": 100,
        "can_save_property": True,
        "saved_property_limit": 50,
        "can_restore_archived_property": True,
        "can_compare_multiple_properties": True,
        "can_use_basic_filters": True,
        "can_use_natural_language_filtering": True,
        "can_use_lifestyle_score": True,
        "can_use_ai_explanations": True,
        "can_generate_ai_reports": True,
        "can_use_google_apis": True,
        "can_use_commute_analysis": True,
        "can_use_neighborhood_enrichment": True,
        "can_use_walk_score_api": True,
        "can_use_ai_chat": True,
        "can_export": True,
        "can_use_ai_negotiation": True,
    },
    PLAN_PREMIUM_PLUS: {
        "can_analyze_property": True,
        "monthly_analyses_limit": 500,
        "can_save_property": True,
        "saved_property_limit": 200,
        "can_restore_archived_property": True,
        "can_compare_multiple_properties": True,
        "can_use_basic_filters": True,
        "can_use_natural_language_filtering": True,
        "can_use_lifestyle_score": True,
        "can_use_ai_explanations": True,
        "can_generate_ai_reports": True,
        "can_use_google_apis": True,
        "can_use_commute_analysis": True,
        "can_use_neighborhood_enrichment": True,
        "can_use_walk_score_api": True,
        "can_use_ai_chat": True,
        "can_export": True,
        "can_use_ai_negotiation": True,
    },
    PLAN_BETA: {
        # BETA grants Premium capabilities while active.
        # Admin-configured quota overrides are applied at runtime
        # via set_beta_overrides().
        "can_analyze_property": True,
        "monthly_analyses_limit": 50,   # admin-overridable
        "can_save_property": True,
        "saved_property_limit": 10,     # admin-overridable
        "can_restore_archived_property": True,
        "can_compare_multiple_properties": True,
        "can_use_basic_filters": True,
        "can_use_natural_language_filtering": True,
        "can_use_lifestyle_score": True,
        "can_use_ai_explanations": True,
        "can_generate_ai_reports": True,
        "can_use_google_apis": True,
        "can_use_commute_analysis": True,
        "can_use_neighborhood_enrichment": True,
        "can_use_walk_score_api": True,
        "can_use_ai_chat": True,
        "can_export": True,
        "can_use_ai_negotiation": True,
    },
}

# ── Plan labels ───────────────────────────────────────────────────────────────

_PLAN_LABELS = {
    PLAN_FREE: "Free",
    PLAN_PREMIUM: "Premium",
    PLAN_PREMIUM_PLUS: "Premium Plus",
    PLAN_BETA: "Beta",
}

# Feature → minimum plan required (for upgrade prompts)
_FEATURE_REQUIRED_PLAN: dict[str, str] = {
    "can_compare_multiple_properties": PLAN_PREMIUM,
    "can_restore_archived_property": PLAN_PREMIUM,
    "can_use_natural_language_filtering": PLAN_PREMIUM,
    "can_use_lifestyle_score": PLAN_PREMIUM,
    "can_use_ai_explanations": PLAN_PREMIUM,
    "can_generate_ai_reports": PLAN_PREMIUM,
    "can_use_google_apis": PLAN_PREMIUM,
    "can_use_commute_analysis": PLAN_PREMIUM,
    "can_use_neighborhood_enrichment": PLAN_PREMIUM,
    "can_use_walk_score_api": PLAN_PREMIUM,
    "can_use_ai_chat": PLAN_PREMIUM,
    "can_export": PLAN_PREMIUM,
    "can_use_ai_negotiation": PLAN_PREMIUM,
}

# ── FeatureUpgradeRequired ────────────────────────────────────────────────────

@dataclass
class FeatureUpgradeRequired:
    """Returned when a Free (or lower) user requests a gated feature.

    The caller should NOT call the external provider when this is returned.
    Instead it should surface the message and upgrade prompt to the user.
    """
    feature: str
    current_plan: str
    required_plan: str
    message: str
    upgrade_action: str = "upgrade"   # action identifier for the UI

    def __bool__(self) -> bool:
        return False   # so `if require_capability(...)` evaluates falsy


# ── Session-state helpers ─────────────────────────────────────────────────────

_DEFAULTS: dict[str, Any] = {
    # v2 compatibility: keep existing tier key; new plan key mirrors it
    "nestai_plan": PLAN_FREE,           # canonical plan key used by this module
    "nestai_role": ROLE_USER,
    "nestai_analyses_used_month": 0,
    "nestai_beta_overrides": {},        # dict of capability overrides for BETA
}


def _init() -> None:
    for k, v in _DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ── Backwards compatibility with credits.py ────────────────────────────
    # credits.py stores plan in `nestai_tier` ("free"/"premium").
    # Mirror into the new canonical key so callers of feature_access.py
    # see the same plan even when credits.py is the source of truth.
    if "nestai_tier" in st.session_state:
        legacy_tier = st.session_state.nestai_tier.upper()
        if legacy_tier in _ALL_PLANS:
            st.session_state.nestai_plan = legacy_tier
        elif legacy_tier == "PREMIUM":
            st.session_state.nestai_plan = PLAN_PREMIUM


# ── Public API ────────────────────────────────────────────────────────────────

def get_plan() -> str:
    """Return the current user's plan (FREE / PREMIUM / PREMIUM_PLUS / BETA)."""
    _init()
    return st.session_state.nestai_plan


def get_role() -> str:
    """Return the current user's role (USER / ADMIN)."""
    _init()
    return st.session_state.nestai_role


def is_admin() -> bool:
    return get_role() == ROLE_ADMIN


def set_plan(plan: str) -> None:
    """Change the current session plan.  Only safe to call after auth/payment confirmation."""
    _init()
    if plan in _ALL_PLANS:
        st.session_state.nestai_plan = plan
        # Keep credits.py tier in sync
        if "nestai_tier" in st.session_state:
            st.session_state.nestai_tier = plan.lower()


def capability(feature: str) -> bool:
    """Return True if the current user's plan includes *feature*.

    Always returns True for admin users.
    """
    _init()
    if is_admin():
        return True

    plan = get_plan()
    plan_caps = _CAPABILITIES.get(plan, _CAPABILITIES[PLAN_FREE])

    # Apply beta overrides if present
    overrides = st.session_state.nestai_beta_overrides
    if plan == PLAN_BETA and overrides:
        return bool(overrides.get(feature, plan_caps.get(feature, False)))

    return bool(plan_caps.get(feature, False))


def get_quota(quota_name: str) -> int:
    """Return the numeric quota for *quota_name* under the current plan.

    Returns 0 if the quota is not defined for the plan.
    """
    _init()
    plan = get_plan()
    plan_caps = _CAPABILITIES.get(plan, _CAPABILITIES[PLAN_FREE])
    overrides = st.session_state.nestai_beta_overrides
    if plan == PLAN_BETA and quota_name in overrides:
        return int(overrides[quota_name])
    return int(plan_caps.get(quota_name, 0))


def require_capability(feature: str) -> Optional[FeatureUpgradeRequired]:
    """Return a :class:`FeatureUpgradeRequired` if the feature is not allowed.

    Returns ``None`` when the feature IS allowed, so callers can write::

        if prompt := require_capability("can_use_google_apis"):
            st.warning(prompt.message)
            return
        # proceed with the API call

    This ensures paid API calls are never made for Free-plan users even if the
    UI button is somehow reachable.
    """
    if capability(feature):
        return None
    plan = get_plan()
    required = _FEATURE_REQUIRED_PLAN.get(feature, PLAN_PREMIUM)
    required_label = _PLAN_LABELS.get(required, required)
    current_label = _PLAN_LABELS.get(plan, plan)
    return FeatureUpgradeRequired(
        feature=feature,
        current_plan=plan,
        required_plan=required,
        message=(
            f"This feature requires the {required_label} plan. "
            f"You are currently on the {current_label} plan."
        ),
    )


def monthly_analyses_remaining() -> int:
    """Return how many property analyses remain this billing period."""
    _init()
    used = int(st.session_state.nestai_analyses_used_month)
    limit = get_quota("monthly_analyses_limit")
    return max(0, limit - used)


def consume_monthly_analysis() -> bool:
    """Deduct one analysis from the monthly budget.

    Returns True if the analysis was consumed; False if none remain.
    """
    _init()
    if monthly_analyses_remaining() <= 0:
        return False
    st.session_state.nestai_analyses_used_month += 1
    return True


def can_save_another_property(current_active_count: int) -> bool:
    """Return True if the user can save an additional property."""
    limit = get_quota("saved_property_limit")
    return current_active_count < limit


def set_beta_overrides(overrides: dict) -> None:
    """Apply admin-configured overrides for a BETA user.

    Example overrides::

        {
            "monthly_analyses_limit": 25,
            "saved_property_limit": 5,
            "can_use_ai_reports": False,
        }
    """
    _init()
    st.session_state.nestai_beta_overrides = overrides


# ── Backwards-compatibility shim for credits.py callers ──────────────────────

def has_feature(feature: str) -> bool:
    """Legacy shim: maps credits.py feature names to capability checks.

    This allows existing ``has_feature(...)`` calls in app.py to continue
    working while capability() is used for new code.
    """
    _LEGACY_MAP = {
        "parse": True,                              # always allowed
        "ai_chat": "can_use_ai_chat",
        "walk_score": "can_use_walk_score_api",
        "commute": "can_use_commute_analysis",
        "neighborhood": "can_use_neighborhood_enrichment",
        "decision_reports": "can_generate_ai_reports",
        "exports": "can_export",
        "negotiation": "can_use_ai_negotiation",
    }
    mapped = _LEGACY_MAP.get(feature)
    if mapped is True:
        return True
    if mapped:
        return capability(mapped)
    # Unknown feature → fall back to plan caps raw lookup
    return capability(feature)
