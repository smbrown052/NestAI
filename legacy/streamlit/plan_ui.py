"""
plan_ui.py
Pricing page, plan badge, upgrade prompt, and dev-mode plan switcher for NestAI.

Public surface:
    render_plan_sidebar()               — call inside a ``with st.sidebar:`` block
    render_pricing_cards()              — call anywhere in the main content area
    render_upgrade_prompt(feature, ...) — inline gated-feature upgrade panel
    get_pricing_plans()                 — returns the public plan card data (no OWNER_TEST)

Environment flags:
    NESTAI_OWNER_MODE=true  — forces OWNER_TEST; sidebar shows unlimited badge
    NESTAI_DEV_MODE=true    — shows the development plan switcher in the sidebar
"""

from __future__ import annotations

import streamlit as st

from feature_access import (
    PLAN_FREE,
    PLAN_PREMIUM,
    PLAN_PREMIUM_PLUS,
    PLAN_BETA,
    PLAN_OWNER_TEST,
    _PLAN_LABELS,
    capability,
    get_plan,
    get_quota,
    is_dev_mode,
    is_owner_mode_env,
    is_owner_test,
    monthly_analyses_remaining,
    require_capability,
    set_plan,
)

# ── Public plan card data ─────────────────────────────────────────────────────
# OWNER_TEST is intentionally excluded — it must never appear on the pricing page.

PRICING_PLANS: list[dict] = [
    {
        "id": PLAN_FREE,
        "name": "Free",
        "price": "$0",
        "period": "forever",
        "badge": "🆓",
        "features": [
            "5 property analyses per month",
            "1 active saved property",
            "Apartment and home listing parsing",
            "Basic filters and sorting",
            "Cross-property ranking",
        ],
        "not_included": [
            "Walk Score / commute / neighborhood APIs",
            "Multi-property side-by-side comparison",
            "Natural-language filtering",
            "Lifestyle Score and AI explanations",
            "AI reports and exports",
        ],
    },
    {
        "id": PLAN_PREMIUM,
        "name": "Premium",
        "price": "$12",
        "period": "/ month",
        "badge": "⭐",
        "highlight": True,
        "features": [
            "100 property analyses per month",
            "Up to 50 saved properties",
            "Multi-property side-by-side comparison",
            "Natural-language filtering",
            "Lifestyle Score",
            "AI recommendations and explanations",
            "AI reports",
            "Commute analysis (Google Maps)",
            "Walk Score and neighborhood enrichment",
            "Property exports",
            "AI rent negotiation scripts",
        ],
    },
    {
        "id": PLAN_PREMIUM_PLUS,
        "name": "Premium Plus",
        "price": "$25",
        "period": "/ month",
        "badge": "🌟",
        "features": [
            "500 property analyses per month",
            "Up to 200 saved properties",
            "Everything in Premium",
            "Higher AI and Google API quotas",
            "Advanced AI reports",
            "Future portfolio tools",
            "Early access to new features",
        ],
    },
]


def get_pricing_plans() -> list[dict]:
    """Return the public-facing plan card data.

    OWNER_TEST and BETA are never included — they are not purchasable plans.
    """
    return PRICING_PLANS


# ── Sidebar plan badge + usage summary ───────────────────────────────────────

def render_plan_sidebar() -> None:
    """Render the plan badge, usage summary, and upgrade entry point.

    Must be called inside a ``with st.sidebar:`` block.
    """
    plan = get_plan()

    # ── Owner Test Mode ───────────────────────────────────────────────────────
    if is_owner_test():
        st.success("🔑 **Owner Test Mode — Unlimited**")
        st.caption("All features and quotas are bypassed.")
        st.caption("Property analyses: **Unlimited**")
        st.caption("Saved properties: **Unlimited**")
        st.caption("AI usage: **Unlimited**")
        st.caption("Google usage: **Unlimited**")
        if is_dev_mode() or is_owner_mode_env():
            _render_dev_plan_switcher()
        return

    # ── Plan badge ────────────────────────────────────────────────────────────
    badge_map = {
        PLAN_FREE: "🆓 **Free Plan**",
        PLAN_PREMIUM: "⭐ **Premium**",
        PLAN_PREMIUM_PLUS: "🌟 **Premium Plus**",
        PLAN_BETA: "🔬 **Beta**",
    }
    st.markdown(f"**Current plan:** {badge_map.get(plan, plan)}")

    # ── Usage summary ─────────────────────────────────────────────────────────
    remaining = monthly_analyses_remaining()
    quota = get_quota("monthly_analyses_limit")
    if remaining is None or quota is None:
        st.caption("Property analyses: **Unlimited**")
    else:
        st.caption(f"Property analyses: **{remaining}** / {quota} this month")

    saved_limit = get_quota("saved_property_limit")
    if saved_limit is None:
        st.caption("Saved properties: **Unlimited**")
    else:
        st.caption(f"Saved properties: up to **{saved_limit}**")

    # ── CTA for Free users ────────────────────────────────────────────────────
    if plan == PLAN_FREE:
        if st.button(
            "⬆️ View Plans & Upgrade",
            use_container_width=True,
            key="sidebar_view_plans_btn",
        ):
            st.session_state.nestai_show_pricing = True
            st.rerun()

    # ── Dev plan switcher ─────────────────────────────────────────────────────
    if is_dev_mode():
        _render_dev_plan_switcher()


# ── Dev-only plan switcher ────────────────────────────────────────────────────

def _render_dev_plan_switcher() -> None:
    """Render the development plan selector.

    Visible only when NESTAI_DEV_MODE=true.
    OWNER_TEST is included here so all plans can be tested end-to-end.
    """
    _PLAN_OPTS = [PLAN_FREE, PLAN_PREMIUM, PLAN_PREMIUM_PLUS, PLAN_BETA, PLAN_OWNER_TEST]
    _PLAN_DISP = {
        PLAN_FREE: "Free",
        PLAN_PREMIUM: "Premium",
        PLAN_PREMIUM_PLUS: "Premium Plus",
        PLAN_BETA: "Beta",
        PLAN_OWNER_TEST: "Owner Test (Unlimited)",
    }

    with st.expander("🛠 Development Plan Preview", expanded=False):
        st.caption("⚠️ Development only — hidden in production.")
        current = get_plan()
        current_idx = _PLAN_OPTS.index(current) if current in _PLAN_OPTS else 0
        selected = st.selectbox(
            "Active plan",
            options=_PLAN_OPTS,
            format_func=lambda p: _PLAN_DISP[p],
            index=current_idx,
            key="dev_plan_selector",
        )
        if st.button("Apply Plan", use_container_width=True, key="dev_apply_plan_btn"):
            set_plan(selected)
            st.success(f"✅ Plan set to: {_PLAN_DISP[selected]}")
            st.rerun()


# ── Pricing cards ─────────────────────────────────────────────────────────────

def render_pricing_cards() -> None:
    """Render the three public plan cards (FREE, PREMIUM, PREMIUM_PLUS).

    Does NOT display OWNER_TEST or BETA — those are not purchasable plans.
    Upgrade buttons show a "billing coming soon" notice; no payment is processed.
    """
    plan = get_plan()

    st.markdown("## 💳 Plans & Pricing")
    st.caption(
        "Choose the plan that fits your home search. "
        "Billing setup is coming soon — your interest will be recorded."
    )

    cols = st.columns(3)
    for col, card in zip(cols, PRICING_PLANS):
        with col:
            _render_plan_card(card, is_current=(plan == card["id"]))


def _render_plan_card(card: dict, is_current: bool) -> None:
    if card.get("highlight"):
        st.markdown("🟡 **Most Popular**")

    st.markdown(f"### {card['badge']} {card['name']}")
    st.markdown(
        f"<span style='font-size:2em; font-weight:bold;'>{card['price']}</span>"
        f"<span style='color:gray;'> {card['period']}</span>",
        unsafe_allow_html=True,
    )

    st.markdown("**Includes:**")
    for feat in card["features"]:
        st.markdown(f"✅ {feat}")

    if "not_included" in card:
        with st.expander("What's not included", expanded=False):
            for feat in card["not_included"]:
                st.markdown(f"🔒 {feat}")

    st.markdown("")  # visual spacer

    plan_id = card["id"]
    if is_current:
        st.button(
            "✓ Current Plan",
            disabled=True,
            use_container_width=True,
            key=f"plan_cta_{plan_id}",
        )
    elif plan_id == PLAN_PREMIUM:
        if st.button(
            "⬆️ Upgrade to Premium",
            use_container_width=True,
            key=f"plan_cta_{plan_id}",
            type="primary",
        ):
            st.info("💳 Billing setup coming soon. Your interest in **Premium** has been noted.")
            st.session_state.nestai_upgrade_intent = PLAN_PREMIUM
    elif plan_id == PLAN_PREMIUM_PLUS:
        if st.button(
            "⬆️ Upgrade to Premium Plus",
            use_container_width=True,
            key=f"plan_cta_{plan_id}",
        ):
            st.info(
                "💳 Billing setup coming soon. "
                "Your interest in **Premium Plus** has been noted."
            )
            st.session_state.nestai_upgrade_intent = PLAN_PREMIUM_PLUS


# ── Inline upgrade prompt ─────────────────────────────────────────────────────

def render_upgrade_prompt(feature: str, feature_label: str = "") -> None:
    """Render an inline upgrade panel when a Free user hits a gated feature.

    Does NOT make any external API calls.

    Args:
        feature:       The capability key (e.g. "can_use_commute_analysis").
        feature_label: Human-readable name for display.  Derived from *feature*
                       automatically when omitted.
    """
    prompt = require_capability(feature)
    if prompt is None:
        return  # already allowed for this plan

    label = feature_label or feature.replace("can_", "").replace("_", " ").title()
    current_label = _PLAN_LABELS.get(prompt.current_plan, prompt.current_plan)
    required_label = _PLAN_LABELS.get(prompt.required_plan, prompt.required_plan)

    with st.container(border=True):
        st.warning(
            f"🔒 **{label}** requires the **{required_label}** plan.  \n"
            f"You are currently on the **{current_label}** plan."
        )

        up_col1, up_col2 = st.columns(2)
        with up_col1:
            st.markdown("**⭐ Premium includes:**")
            for feat in PRICING_PLANS[1]["features"][:5]:
                st.caption(f"✅ {feat}")
        with up_col2:
            st.markdown("**🌟 Premium Plus includes:**")
            for feat in PRICING_PLANS[2]["features"][:4]:
                st.caption(f"✅ {feat}")

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button(
                "⬆️ Upgrade to Premium",
                use_container_width=True,
                key=f"upgrade_prompt_{feature}_premium",
                type="primary",
            ):
                st.info("💳 Billing setup coming soon.")
                st.session_state.nestai_upgrade_intent = PLAN_PREMIUM
        with btn_col2:
            if st.button(
                "⬆️ Upgrade to Premium Plus",
                use_container_width=True,
                key=f"upgrade_prompt_{feature}_plus",
            ):
                st.info("💳 Billing setup coming soon.")
                st.session_state.nestai_upgrade_intent = PLAN_PREMIUM_PLUS
