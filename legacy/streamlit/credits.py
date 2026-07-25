"""
credits.py
NestAI V2 credit and tier system.

Tiers
-----
free      — 5 apartment analyses (building enrichments), no AI/commute/walk score
premium   — 100 analyses, all features
extra     — add-on pack of 50 analyses for $9.99

An "analysis" is a building-level enrichment (Level 2 enrichment).
Parsing and Level 1 comparison are always free.
AI chat / Decision Reports do NOT consume credits once the building is already enriched.
"""

from __future__ import annotations

import streamlit as st

# ── Tier definitions ──────────────────────────────────────────────────────────

TIERS: dict[str, dict] = {
    "free": {
        "label": "Free",
        "analyses": 5,
        "ai_chat": False,
        "walk_score": False,
        "commute": False,
        "neighborhood": False,
        "decision_reports": False,
        "exports": False,
        "negotiation": False,
    },
    "premium": {
        "label": "Premium",
        "analyses": 100,
        "ai_chat": True,
        "walk_score": True,
        "commute": True,
        "neighborhood": True,
        "decision_reports": True,
        "exports": True,
        "negotiation": True,
    },
}

_EXTRA_PACK_SIZE = 50

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
    return st.session_state.nestai_analyses_used


def analyses_limit() -> int:
    _init()
    tier = TIERS[get_tier()]
    return tier["analyses"] + st.session_state.nestai_extra_credits


def analyses_remaining() -> int:
    return max(0, analyses_limit() - analyses_used())


def has_feature(feature: str) -> bool:
    """
    Return True if the current tier includes *feature*.

    Always returns True for 'parse' (parsing is always free).
    Returns True for paid features only on premium tier.
    """
    _init()
    if feature == "parse":
        return True
    return bool(TIERS[get_tier()].get(feature, False))


def can_enrich_building(building_id: str) -> bool:
    """
    Return True if user can enrich this building (has remaining credits or
    the building was already enriched this session — no double-charge).
    """
    _init()
    if building_id in st.session_state.nestai_enriched_buildings:
        return True  # already paid for this session
    return analyses_remaining() > 0


def consume_analysis(building_id: str) -> bool:
    """
    Deduct one analysis credit for enriching a building.
    Returns True if credit was consumed, False if insufficient credits.
    Idempotent within the same session (same building is not charged twice).
    """
    _init()
    if building_id in st.session_state.nestai_enriched_buildings:
        return True  # already enriched, no charge
    if analyses_remaining() <= 0:
        return False
    st.session_state.nestai_analyses_used += 1
    st.session_state.nestai_enriched_buildings.add(building_id)
    return True


def add_extra_credits(n: int = _EXTRA_PACK_SIZE) -> None:
    """Add *n* extra analysis credits (e.g. after purchase)."""
    _init()
    st.session_state.nestai_extra_credits += n


def upgrade_to_premium() -> None:
    """Simulate upgrading to Premium (called after payment confirmation)."""
    _init()
    st.session_state.nestai_tier = "premium"


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
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⭐ Upgrade — $24.99", use_container_width=True, key="upgrade_btn"):
                upgrade_to_premium()
                st.success("Upgraded to Premium!")
                st.rerun()
        with col2:
            if st.button("➕ 50 credits — $9.99", use_container_width=True, key="buy_credits_btn"):
                add_extra_credits(50)
                st.success("50 credits added!")
                st.rerun()
    else:
        st.markdown(
            f"**⭐ Premium** · {remaining}/{limit} analyses left"
        )
        if st.button("➕ More credits — $9.99 / 50", use_container_width=True, key="buy_more_btn"):
            add_extra_credits(50)
            st.success("50 credits added!")
            st.rerun()
