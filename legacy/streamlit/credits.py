"""Compatibility displays for shared monthly quotas and account-backed usage.

Legacy balances remain independent and are never converted or granted here.
Authenticated analyses and provider calls are charged only by API operations.
"""

from __future__ import annotations

import os

import streamlit as st
from feature_access import get_plan_capabilities

# ── Tier definitions ──────────────────────────────────────────────────────────

_FEATURES = {
    "ai_chat": "can_use_ai_chat", "walk_score": "can_use_walk_score_api",
    "commute": "can_use_commute_analysis", "neighborhood": "can_use_neighborhood_enrichment",
    "decision_reports": "can_generate_ai_reports", "exports": "can_export",
    "negotiation": "can_use_ai_negotiation",
}

TIERS = {}
for _tier in ("free", "beta", "premium", "premium_plus"):
    _caps = get_plan_capabilities(_tier.upper())
    TIERS[_tier] = {"label": _tier.replace("_", " ").title(),
                    "analyses": _caps["monthly_analyses_limit"],
                    **{feature: _caps[capability] for feature, capability in _FEATURES.items()}}

_EXTRA_PACK_SIZE = 50


def _owner_mode_enabled() -> bool:
    return os.environ.get("NESTAI_OWNER_MODE", "").lower() in {"1", "true", "yes"}

# ── Session state helpers ─────────────────────────────────────────────────────

_DEFAULTS = {
    "nestai_tier": "free",
    "nestai_analyses_used": 0,
    "nestai_extra_credits": 0,
    "nestai_enriched_buildings": set(),  # building_ids already enriched this session
}


def _init() -> None:
    for k, v in _DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Public API ────────────────────────────────────────────────────────────────

def get_tier() -> str:
    _init()
    return st.session_state.nestai_tier


def set_tier(tier: str) -> None:
    _init()
    if tier in TIERS:
        st.session_state.nestai_tier = tier


def get_tier_info() -> dict:
    return TIERS[get_tier()]


def analyses_used() -> int:
    _init()
    if st.session_state.get("account_entitlements"):
        return int(st.session_state["account_entitlements"].get("usage", {}).get("analyses_used", 0))
    return st.session_state.nestai_analyses_used


def analyses_limit() -> int | None:
    _init()
    if st.session_state.get("auth_token"):
        from feature_access import get_quota
        return get_quota("monthly_analyses_limit")
    if _owner_mode_enabled():
        return 10**9
    tier = TIERS[get_tier()]
    if tier["analyses"] is None:
        return None
    return tier["analyses"] + st.session_state.nestai_extra_credits


def analyses_remaining() -> int | None:
    limit = analyses_limit()
    if limit is None:
        return None
    return max(0, limit - analyses_used())


def has_feature(feature: str) -> bool:
    """
    Return True if the current tier includes *feature*.

    Always returns True for 'parse' (parsing is always free).
    Returns True for paid features only on premium tier.
    """
    _init()
    if st.session_state.get("auth_token"):
        from feature_access import has_feature as account_feature
        return account_feature(feature)
    if feature == "parse":
        return True
    if _owner_mode_enabled():
        return True
    return bool(TIERS[get_tier()].get(feature, False))


def can_enrich_building(building_id: str) -> bool:
    """
    Return True if user can enrich this building (has remaining credits or
    the building was already enriched this session — no double-charge).
    """
    _init()
    if _owner_mode_enabled():
        return True
    if building_id in st.session_state.nestai_enriched_buildings:
        return True  # already paid for this session
    remaining = analyses_remaining()
    return remaining is None or remaining > 0


def consume_analysis(building_id: str) -> bool:
    """
    Deduct one analysis credit for enriching a building.
    Returns True if credit was consumed, False if insufficient credits.
    Idempotent within the same session (same building is not charged twice).
    """
    _init()
    if st.session_state.get("auth_token"):
        return False  # Account credits are debited only by the feature endpoint.
    if _owner_mode_enabled():
        st.session_state.nestai_enriched_buildings.add(building_id)
        return True
    if building_id in st.session_state.nestai_enriched_buildings:
        return True  # already enriched, no charge
    remaining = analyses_remaining()
    if remaining == 0:
        return False
    if remaining is not None:
        st.session_state.nestai_analyses_used += 1
    st.session_state.nestai_enriched_buildings.add(building_id)
    return True


def add_extra_credits(n: int = _EXTRA_PACK_SIZE) -> None:
    """Add *n* extra analysis credits (e.g. after purchase)."""
    _init()
    raise RuntimeError("Credits can only be granted by the account service.")


def upgrade_to_premium() -> None:
    """Reject local plan activation; verified billing owns subscriptions."""
    _init()
    raise RuntimeError("Subscriptions can only be activated by verified billing.")


# ── Demo helper used by the sidebar ──────────────────────────────────────────

def render_tier_badge() -> None:
    """Render a compact tier status widget in the sidebar."""
    _init()
    tier = get_tier()
    info = get_tier_info()
    remaining = analyses_remaining()
    limit = analyses_limit()

    if tier == "free":
        st.markdown(
            f"**🆓 Free Plan** · {remaining}/{limit} analyses left"
        )
        if remaining == 0:
            st.warning("You've used all free analyses.")
    else:
        st.markdown(
            f"**⭐ {info['label']}** · {remaining}/{limit} analyses left"
        )
    if st.button("View subscription plans", key="credit_view_plans"):
        st.session_state["main_nav"] = "Pricing"
        st.rerun()
