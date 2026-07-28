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
    OWNER_TEST    — dev/owner only; unlimited everything; never shown on pricing page

Environment flags:
    NESTAI_OWNER_MODE=true  — enables OWNER_TEST preview (session starts there)
    NESTAI_DEV_MODE=true    — enables the in-app development plan switcher

Usage::

    from feature_access import capability, require_capability, FeatureUpgradeRequired
    if capability("can_compare_multiple_properties"):
        ...  # show comparison UI
    else:
        prompt = require_capability("can_compare_multiple_properties")
        # prompt.message describes the upgrade needed
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import streamlit as st

# ── Plan and role constants ───────────────────────────────────────────────────

PLAN_FREE = "FREE"
PLAN_PREMIUM = "PREMIUM"
PLAN_PREMIUM_PLUS = "PREMIUM_PLUS"
PLAN_BETA = "BETA"
PLAN_OWNER_TEST = "OWNER_TEST"   # dev/owner only — NOT a purchasable plan

ROLE_USER = "USER"
ROLE_ADMIN = "ADMIN"

_ALL_PLANS = {PLAN_FREE, PLAN_PREMIUM, PLAN_PREMIUM_PLUS, PLAN_BETA, PLAN_OWNER_TEST}

# Credits.py only knows "free" / "premium"; map richer plans to the closest equivalent.
_CREDITS_TIER_MAP = {
    PLAN_FREE: "free",
    PLAN_PREMIUM: "premium",
    PLAN_PREMIUM_PLUS: "premium",
    PLAN_BETA: "premium",
    PLAN_OWNER_TEST: "premium",
}

# ── Per-plan capability and quota definitions ─────────────────────────────────

_CAPABILITIES: dict[str, dict[str, Any]] = {
    PLAN_FREE: {
        # Analyses
        "can_analyze_property": True,
        "monthly_analyses_limit": 10,
        # Saved properties — Free allows 2 active properties
        "can_save_property": True,
        "saved_property_limit": 2,
        "can_restore_archived_property": False,
        # Comparison — Free can compare the 2 saved properties
        "can_compare_multiple_properties": True,
        # Filtering and sorting
        "can_use_basic_filters": True,
        "can_use_natural_language_filtering": False,
        # Ranking
        "can_use_ranking_table": True,
        # Decision Recommendation
        "can_use_basic_decision_recommendation": True,
        # Notes
        "can_add_notes": True,
        # Parsing — Free gets apartment and house parsing
        "can_parse_apartments": True,
        "can_parse_houses": True,
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
        # Negotiation — Premium Plus only
        "can_use_ai_negotiation": False,
        # Saved searches / alerts — Premium only
        "can_use_saved_searches": False,
        "can_use_new_listing_alerts": False,
        "can_use_price_drop_alerts": False,
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
        "can_use_ranking_table": True,
        "can_use_basic_decision_recommendation": True,
        "can_add_notes": True,
        "can_parse_apartments": True,
        "can_parse_houses": True,
        "can_use_lifestyle_score": True,
        "can_use_ai_explanations": True,
        "can_generate_ai_reports": True,
        "can_use_google_apis": True,
        "can_use_commute_analysis": True,
        "can_use_neighborhood_enrichment": True,
        "can_use_walk_score_api": True,
        "can_use_ai_chat": True,
        "can_export": True,
        "can_use_ai_negotiation": False,       # Premium Plus only
        "can_use_saved_searches": True,
        "can_use_new_listing_alerts": True,
        "can_use_price_drop_alerts": True,
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
        "can_use_ranking_table": True,
        "can_use_basic_decision_recommendation": True,
        "can_add_notes": True,
        "can_parse_apartments": True,
        "can_parse_houses": True,
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
        "can_use_saved_searches": True,
        "can_use_new_listing_alerts": True,
        "can_use_price_drop_alerts": True,
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
        "can_use_ranking_table": True,
        "can_use_basic_decision_recommendation": True,
        "can_add_notes": True,
        "can_parse_apartments": True,
        "can_parse_houses": True,
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
        "can_use_saved_searches": True,
        "can_use_new_listing_alerts": True,
        "can_use_price_drop_alerts": True,
    },
}

# ── Plan labels ───────────────────────────────────────────────────────────────

_PLAN_LABELS = {
    PLAN_FREE: "Free",
    PLAN_PREMIUM: "Premium",
    PLAN_PREMIUM_PLUS: "Premium Plus",
    PLAN_BETA: "Beta",
    PLAN_OWNER_TEST: "Owner Test",
}

# Plan value normalization for backend/session inputs
_PLAN_INPUT_MAP = {
    "free": PLAN_FREE,
    "plan_free": PLAN_FREE,
    "premium": PLAN_PREMIUM,
    "plan_premium": PLAN_PREMIUM,
    "premium_plus": PLAN_PREMIUM_PLUS,
    "plan_premium_plus": PLAN_PREMIUM_PLUS,
    "beta": PLAN_BETA,
    "plan_beta": PLAN_BETA,
    "owner_test": PLAN_OWNER_TEST,
    "plan_owner_test": PLAN_OWNER_TEST,
}

# Feature → minimum plan required (for upgrade prompts)
_FEATURE_REQUIRED_PLAN: dict[str, str] = {
    # Comparison is Free (up to 2 properties); saving a 3rd requires Premium
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
    "can_use_saved_searches": PLAN_PREMIUM,
    "can_use_new_listing_alerts": PLAN_PREMIUM,
    "can_use_price_drop_alerts": PLAN_PREMIUM,
    # Negotiation is Premium Plus only
    "can_use_ai_negotiation": PLAN_PREMIUM_PLUS,
}

# ── Environment flag helpers ──────────────────────────────────────────────────

def is_owner_mode_env() -> bool:
    """Return True when NESTAI_OWNER_MODE=true is set in the environment.

    When active, OWNER_TEST is allowed in the dev preview switcher and is used
    as the initial preview plan for the session.
    """
    return os.environ.get("NESTAI_OWNER_MODE", "").lower() in ("1", "true", "yes")


def is_dev_mode() -> bool:
    """Return True when NESTAI_DEV_MODE=true is set in the environment.

    When active, the development plan switcher is visible in the sidebar.
    """
    return os.environ.get("NESTAI_DEV_MODE", "").lower() in ("1", "true", "yes")

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
    "nestai_owner_mode_initialized": False,
}


def _init() -> None:
    for k, v in _DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ── Owner mode default (session-local) ─────────────────────────────────
    # First run with owner mode starts in OWNER_TEST, but developers can still
    # switch to other plans in the preview control for full UI testing.
    if is_owner_mode_env() and not bool(st.session_state.get("nestai_owner_mode_initialized")):
        st.session_state.nestai_plan = PLAN_OWNER_TEST
        st.session_state.nestai_tier = "premium"   # keep credits.py happy
        st.session_state.nestai_owner_mode_initialized = True

    # ── Backwards compatibility with credits.py ────────────────────────────
    # credits.py stores plan in `nestai_tier` ("free"/"premium").
    # Mirror into the canonical key ONLY when the plan is still at the
    # default FREE value — never downgrade a richer plan back to FREE.
    if st.session_state.nestai_plan == PLAN_FREE and "nestai_tier" in st.session_state:
        legacy_tier = st.session_state.nestai_tier.upper()
        if legacy_tier in _ALL_PLANS and legacy_tier != PLAN_FREE:
            st.session_state.nestai_plan = legacy_tier
        elif legacy_tier == "PREMIUM":
            st.session_state.nestai_plan = PLAN_PREMIUM


# ── Public API ────────────────────────────────────────────────────────────────

def get_plan() -> str:
    """Return the current user's plan (FREE / PREMIUM / PREMIUM_PLUS / BETA)."""
    _init()
    return st.session_state.nestai_plan


def normalize_plan_value(plan: str | None, *, beta_access: bool = False) -> str:
    """Normalize backend/session plan values to canonical constants."""
    raw = (plan or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapped = _PLAN_INPUT_MAP.get(raw)
    if mapped:
        return mapped
    if beta_access:
        return PLAN_BETA
    return PLAN_FREE


def get_effective_plan(backend_plan: str | None = None, *, beta_access: bool = False) -> str:
    """Return the plan the UI should render for this session.

    - Production mode (no dev/owner flag): backend plan is authoritative
    - Dev/owner mode: session preview plan is authoritative
    """
    _init()
    if is_dev_mode() or is_owner_mode_env():
        return get_plan()
    if backend_plan is not None or beta_access:
        return normalize_plan_value(backend_plan, beta_access=beta_access)
    return get_plan()


def get_role() -> str:
    """Return the current user's role (USER / ADMIN)."""
    _init()
    return st.session_state.nestai_role


def is_admin() -> bool:
    return get_role() == ROLE_ADMIN


def set_plan(plan: str) -> None:
    """Change the current session plan.  Only safe to call after auth/payment confirmation.

    OWNER_TEST can only be set when NESTAI_DEV_MODE or NESTAI_OWNER_MODE is active.
    """
    _init()
    if plan not in _ALL_PLANS:
        return
    if plan == PLAN_OWNER_TEST and not (is_owner_mode_env() or is_dev_mode()):
        return
    st.session_state.nestai_plan = plan
    # Keep credits.py tier in sync using the closest legacy tier
    if "nestai_tier" in st.session_state:
        st.session_state.nestai_tier = _CREDITS_TIER_MAP.get(plan, "free")


def is_owner_test() -> bool:
    """Return True if the active plan is OWNER_TEST (unlimited dev/owner mode)."""
    _init()
    return st.session_state.nestai_plan == PLAN_OWNER_TEST


def capability(feature: str) -> bool:
    """Return True if the current user's plan includes *feature*.

    Always returns True for admin users and for OWNER_TEST.
    """
    _init()
    if is_admin() or is_owner_test():
        return True

    plan = get_plan()
    plan_caps = _CAPABILITIES.get(plan, _CAPABILITIES[PLAN_FREE])

    # Apply beta overrides if present
    overrides = st.session_state.nestai_beta_overrides
    if plan == PLAN_BETA and overrides:
        return bool(overrides.get(feature, plan_caps.get(feature, False)))

    return bool(plan_caps.get(feature, False))


def get_quota(quota_name: str) -> Optional[int]:
    """Return the numeric quota for *quota_name* under the current plan.

    Returns ``None`` for OWNER_TEST (unlimited).
    Returns 0 if the quota is not defined for the plan.
    Callers must treat ``None`` as unlimited.
    """
    _init()
    if is_owner_test():
        return None   # unlimited for OWNER_TEST
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


def monthly_analyses_remaining() -> Optional[int]:
    """Return how many property analyses remain this billing period.

    Returns ``None`` for OWNER_TEST (unlimited).
    """
    _init()
    limit = get_quota("monthly_analyses_limit")
    if limit is None:
        return None   # unlimited
    used = int(st.session_state.nestai_analyses_used_month)
    return max(0, limit - used)


def consume_monthly_analysis() -> bool:
    """Deduct one analysis from the monthly budget.

    Returns True if the analysis was consumed or the plan is unlimited.
    Returns False if none remain.
    """
    _init()
    remaining = monthly_analyses_remaining()
    if remaining is None:
        return True   # unlimited — no deduction needed
    if remaining <= 0:
        return False
    st.session_state.nestai_analyses_used_month += 1
    return True


def can_save_another_property(current_active_count: int) -> bool:
    """Return True if the user can save an additional property."""
    limit = get_quota("saved_property_limit")
    if limit is None:
        return True   # unlimited
    return current_active_count < limit


# ── Premium trial helpers ─────────────────────────────────────────────────────

def get_trial_status(user: dict | None = None) -> dict:
    """Return a dict describing the current trial state.

    The returned dict always has keys:
        trial_used:    bool — whether the trial has ever been started
        trial_active:  bool — trial is running right now
        trial_expired: bool — trial was used and has now expired
        ends_at:       datetime | None — UTC expiry time when active
        days_remaining: int | None — whole days remaining (None if not active)
        hours_remaining: int | None — hours remaining if < 24h left

    ``user`` should be the dict from /auth/me (or session_state auth_user).
    When running in dev mode, the trial state reflects session state only and
    never modifies the backend.
    """
    from datetime import datetime, timezone

    result: dict = {
        "trial_used": False,
        "trial_active": False,
        "trial_expired": False,
        "ends_at": None,
        "days_remaining": None,
        "hours_remaining": None,
    }
    if not user:
        return result

    trial_used = bool(user.get("premium_trial_used"))
    result["trial_used"] = trial_used

    ends_at_raw = user.get("premium_trial_ends_at")
    if not ends_at_raw:
        return result

    if isinstance(ends_at_raw, str):
        try:
            from datetime import datetime
            ends_at = datetime.fromisoformat(ends_at_raw)
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return result
    else:
        ends_at = ends_at_raw

    result["ends_at"] = ends_at
    now = datetime.now(timezone.utc)
    if ends_at > now:
        delta = ends_at - now
        total_hours = int(delta.total_seconds() / 3600)
        result["trial_active"] = True
        result["days_remaining"] = delta.days
        result["hours_remaining"] = total_hours if total_hours < 24 else None
    else:
        result["trial_expired"] = True

    return result


def get_effective_plan_with_trial(
    backend_plan: str | None = None,
    *,
    user: dict | None = None,
    beta_access: bool = False,
) -> str:
    """Like :func:`get_effective_plan` but also applies an active Premium trial.

    In dev mode, preview plan is used (trial is NOT consumed/applied).
    In production mode, if the user has an active trial and is on Free/no plan,
    the effective plan is Premium for the duration of the trial.
    """
    _init()
    # In dev/owner mode the preview plan is always authoritative
    if is_dev_mode() or is_owner_mode_env():
        return get_plan()

    # Determine base plan from backend
    base = normalize_plan_value(backend_plan, beta_access=beta_access)

    # If base is already Premium or higher, trial is irrelevant
    _premium_or_above = {PLAN_PREMIUM, PLAN_PREMIUM_PLUS, PLAN_BETA}
    if base in _premium_or_above:
        return base

    # Check whether an active trial should elevate Free → Premium
    trial = get_trial_status(user)
    if trial["trial_active"]:
        return PLAN_PREMIUM

    return base


# ── Legacy shim ───────────────────────────────────────────────────────────────


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


# ── Capability set helpers (used by tests and plan_ui) ───────────────────────

def get_plan_capabilities(plan: str) -> dict:
    """Return the capability dict for *plan* (does not apply OWNER_TEST bypass)."""
    return dict(_CAPABILITIES.get(plan, _CAPABILITIES[PLAN_FREE]))


def get_bool_capabilities(plan: str) -> set:
    """Return the set of capability keys that are True (boolean) for *plan*.

    Quota keys (int) are excluded.  Useful for superset assertions::

        assert get_bool_capabilities(PLAN_PREMIUM) <= get_bool_capabilities(PLAN_PREMIUM_PLUS)
    """
    caps = _CAPABILITIES.get(plan, _CAPABILITIES[PLAN_FREE])
    return {k for k, v in caps.items() if v is True}


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
