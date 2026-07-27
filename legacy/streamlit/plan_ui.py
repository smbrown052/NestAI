"""
plan_ui.py
Pricing page, plan badge, upgrade prompt, and dev-mode plan switcher for NestAI.

Public surface:
    navigate_to_plans(highlight_plan)   — set active_view="plans" and rerun
    render_plan_sidebar()               — call inside a ``with st.sidebar:`` block
    render_pricing_cards()              — call in the Plans view only
    render_upgrade_prompt(feature, ...) — inline gated-feature upgrade panel
    get_pricing_plans()                 — returns the public plan card data (no OWNER_TEST)

Navigation state keys (in st.session_state):
    nestai_active_view    — "apartments" | "homes" | "plans"
    nestai_highlight_plan — plan id to highlight on the Plans view, or None
    nestai_upgrade_intent — plan id the user expressed interest in

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

# ── Canonical feature label lists ─────────────────────────────────────────────
# These are the single source of truth for plan card feature copy.
# Premium Plus features are DERIVED from Premium features + extras so they
# can never silently drift apart.

PREMIUM_FEATURE_LABELS: list[str] = [
    "Multiple saved properties (up to 50)",
    "Cross-property comparison",
    "Natural-language filtering",
    "Priority weighting",
    "Lifestyle Score",
    "AI recommendations",
    "AI explanations",
    "AI reports",
    "Commute analysis (Google Maps)",
    "Neighborhood and Walk Score insights",
    "Saved preferences",
    "Generous monthly AI and map usage (100 analyses/month)",
]

PREMIUM_PLUS_EXTRA_LABELS: list[str] = [
    "Higher AI usage limits (500 analyses/month)",
    "Higher map and commute limits (up to 200 saved properties)",
    "More report generations",
    "Advanced comparison reports",
    "Future portfolio tools",
    "Future investment analysis",
    "Early access to new features",
    "Priority access to experimental capabilities",
]

# Public plan card data ────────────────────────────────────────────────────────
# OWNER_TEST is intentionally excluded — it must never appear on the pricing page.

PLAN_DESCRIPTIONS: dict[str, str] = {
    PLAN_FREE: (
        "Explore listings and organize one active property "
        "with essential comparison tools."
    ),
    PLAN_PREMIUM: (
        "Compare multiple properties and unlock personalized AI, "
        "commute, and lifestyle insights."
    ),
    PLAN_PREMIUM_PLUS: (
        "Get everything in Premium with higher usage limits, "
        "advanced reports, and early access to new tools."
    ),
}

PRICING_PLANS: list[dict] = [
    {
        "id": PLAN_FREE,
        "name": "Free",
        "price": "$0",
        "period": "/month",
        "badge": "🆓",
        "description": PLAN_DESCRIPTIONS[PLAN_FREE],
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
        "period": "/month",
        "badge": "⭐",
        "highlight": True,
        "description": PLAN_DESCRIPTIONS[PLAN_PREMIUM],
        "features": PREMIUM_FEATURE_LABELS,
    },
    {
        "id": PLAN_PREMIUM_PLUS,
        "name": "Premium Plus",
        "price": "$25",
        "period": "/month",
        "badge": "🌟",
        "description": PLAN_DESCRIPTIONS[PLAN_PREMIUM_PLUS],
        # All Premium features are inherited; extras are listed separately.
        "features": PREMIUM_FEATURE_LABELS,
        "extras": PREMIUM_PLUS_EXTRA_LABELS,
    },
]

PLAN_FREE_DATA = PRICING_PLANS[0]
PLAN_PREMIUM_DATA = PRICING_PLANS[1]
PLAN_PREMIUM_PLUS_DATA = PRICING_PLANS[2]


def get_pricing_plans() -> list[dict]:
    """Return the public-facing plan card data.

    OWNER_TEST and BETA are never included — they are not purchasable plans.
    """
    return PRICING_PLANS


# ── Navigation helper ─────────────────────────────────────────────────────────

def navigate_to_plans(highlight_plan: str | None = None) -> None:
    """Switch the active view to Plans and optionally highlight a plan.

    Sets ``st.session_state["nestai_active_view"] = "plans"`` and calls
    ``st.rerun()``.  Any caller that wants to direct the user to the Plans
    page (e.g. "View Plans" or "Upgrade" buttons) should use this helper
    instead of manipulating state directly.

    Args:
        highlight_plan: Optional plan id (e.g. PLAN_PREMIUM) to visually
                        highlight when the Plans view renders.
    """
    st.session_state["nestai_active_view"] = "plans"
    if highlight_plan is not None:
        st.session_state["nestai_highlight_plan"] = highlight_plan
    elif "nestai_highlight_plan" in st.session_state:
        st.session_state["nestai_highlight_plan"] = None
    st.rerun()


# ── Sidebar: Account, Usage, and Actions ─────────────────────────────────────

def render_plan_sidebar() -> None:
    """Render the plan/account sidebar sections.

    Renders three coherent sections:
    - Account (Beta access / session label, Owner Test badge when active)
    - Usage (analyses remaining, saved-property limit)
    - Actions (View Plans, Upgrade)

    Must be called inside a ``with st.sidebar:`` block.
    """
    plan = get_plan()

    # ── Owner Test Mode ───────────────────────────────────────────────────────
    if is_owner_test():
        st.success("🔑 **Owner Test Mode — Unlimited**")
        st.caption("All features and quotas are bypassed.")
        _render_owner_usage()
        if is_dev_mode() or is_owner_mode_env():
            _render_dev_plan_switcher()
        return

    # ── Account section ───────────────────────────────────────────────────────
    st.markdown("### 👤 Account")

    # Plan badge
    badge_map = {
        PLAN_FREE: "🆓 **Free**",
        PLAN_PREMIUM: "⭐ **Premium**",
        PLAN_PREMIUM_PLUS: "🌟 **Premium Plus**",
        PLAN_BETA: "🔬 **Beta**",
    }
    st.markdown(f"**Current plan:** {badge_map.get(plan, plan)}")

    # Beta access expander — honest session-based invite-code entry
    with st.expander("🔬 Beta Access", expanded=False):
        if st.session_state.get("beta_tester"):
            st.success("✅ Beta features unlocked!")
        else:
            st.caption(
                "Have an invite code? Enter it below to unlock beta features."
            )
            beta_code_input = st.text_input(
                "Invite code",
                placeholder="e.g. NEST-BETA-2025",
                type="password",
                key="beta_code_input",
                label_visibility="collapsed",
            )
            if st.button(
                "Activate Beta Access",
                use_container_width=True,
                key="sidebar_activate_beta_btn",
            ):
                from feedback import validate_beta_code
                if validate_beta_code(beta_code_input):
                    st.session_state.beta_tester = True
                    st.success("✅ Beta access activated!")
                    st.rerun()
                else:
                    st.error("Invalid invite code.")

    st.caption("_Session-based access — sign-in coming soon._")
    st.divider()

    # ── Usage section ─────────────────────────────────────────────────────────
    st.markdown("### 📊 Usage")

    remaining = monthly_analyses_remaining()
    quota = get_quota("monthly_analyses_limit")
    if remaining is None or quota is None:
        st.caption("Property analyses: **Unlimited**")
    else:
        st.caption(f"Property analyses: **{remaining}** / {quota} this month")

    saved_limit = get_quota("saved_property_limit")
    if saved_limit is None:
        st.caption("Saved properties: **Unlimited**")
    elif saved_limit == 1:
        st.caption("Active saved properties: up to **1**")
    else:
        st.caption(f"Saved properties: up to **{saved_limit}**")

    if plan == PLAN_FREE:
        st.caption("AI requests: 🔒 Locked (upgrade to unlock)")
        st.caption("Map requests: 🔒 Locked (upgrade to unlock)")
    else:
        st.caption("AI requests: ✅ Included")
        st.caption("Map requests: ✅ Included")

    st.divider()

    # ── Actions section ───────────────────────────────────────────────────────
    st.markdown("### ⬆️ Actions")

    if st.button(
        "💳 View Plans",
        use_container_width=True,
        key="sidebar_view_plans_btn",
    ):
        navigate_to_plans()

    if plan == PLAN_FREE:
        if st.button(
            "⬆️ Upgrade",
            use_container_width=True,
            key="sidebar_upgrade_btn",
            type="primary",
        ):
            navigate_to_plans(highlight_plan=PLAN_PREMIUM)
    elif plan == PLAN_PREMIUM:
        if st.button(
            "⬆️ Upgrade to Premium Plus",
            use_container_width=True,
            key="sidebar_upgrade_btn",
            type="primary",
        ):
            navigate_to_plans(highlight_plan=PLAN_PREMIUM_PLUS)

    # ── Dev plan switcher ─────────────────────────────────────────────────────
    if is_dev_mode():
        _render_dev_plan_switcher()


def _render_owner_usage() -> None:
    """Render the usage summary for Owner Test Mode."""
    st.markdown("### 📊 Usage")
    st.caption("Property analyses: **Unlimited**")
    st.caption("Saved properties: **Unlimited**")
    st.caption("AI requests: **Unlimited**")
    st.caption("Map requests: **Unlimited**")
    st.divider()


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
    Upgrade buttons record intent and show a billing-coming-soon notice.

    Reads ``st.session_state["nestai_highlight_plan"]`` to visually emphasise
    a recommended plan (set by navigate_to_plans(highlight_plan=...)).
    """
    plan = get_plan()
    highlight = st.session_state.get("nestai_highlight_plan")

    st.markdown("## 💳 Plans & Pricing")
    st.caption(
        "Choose the plan that fits your home search. "
        "Billing setup is coming soon — your interest will be recorded."
    )

    # Show billing notice if the user just clicked an upgrade CTA
    intent = st.session_state.get("nestai_upgrade_intent")
    if intent and intent in (PLAN_PREMIUM, PLAN_PREMIUM_PLUS):
        intent_label = _PLAN_LABELS.get(intent, intent)
        st.info(
            f"💳 **Billing setup is coming soon.**  \n"
            f"Your selected plan (**{intent_label}**) has been saved for checkout."
        )

    cols = st.columns(3)
    for col, card in zip(cols, PRICING_PLANS):
        with col:
            is_highlighted = highlight == card["id"] and not (plan == card["id"])
            _render_plan_card(card, is_current=(plan == card["id"]), highlighted=is_highlighted)


def _render_plan_card(card: dict, is_current: bool, highlighted: bool = False) -> None:
    """Render a single plan card."""
    if card.get("highlight"):
        st.markdown("🟡 **Most Popular**")

    # Visual emphasis when this plan is recommended
    if highlighted:
        st.markdown("👆 **Recommended for you**")

    st.markdown(f"### {card['badge']} {card['name']}")

    # Price display — always includes $ and /month
    st.markdown(
        f"<span style='font-size:2em; font-weight:bold;'>{card['price']}</span>"
        f"<span style='color:gray;'>{card['period']}</span>",
        unsafe_allow_html=True,
    )

    # Plan description
    if card.get("description"):
        st.caption(card["description"])

    st.markdown("")  # spacer

    # Feature list
    plan_id = card["id"]
    if plan_id == PLAN_PREMIUM_PLUS:
        # Explicitly show "Everything in Premium, plus:" layout
        st.markdown("**✅ Everything in Premium, plus:**")
        for feat in card.get("extras", PREMIUM_PLUS_EXTRA_LABELS):
            st.markdown(f"✅ {feat}")
        with st.expander("See all included Premium features", expanded=False):
            for feat in card.get("features", PREMIUM_FEATURE_LABELS):
                st.markdown(f"✅ {feat}")
    else:
        st.markdown("**Includes:**")
        for feat in card.get("features", []):
            st.markdown(f"✅ {feat}")

    if "not_included" in card:
        with st.expander("What's not included", expanded=False):
            for feat in card["not_included"]:
                st.markdown(f"🔒 {feat}")

    st.markdown("")  # visual spacer

    # CTA button
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
            st.session_state.nestai_upgrade_intent = PLAN_PREMIUM
            st.session_state.nestai_highlight_plan = None
            st.rerun()
    elif plan_id == PLAN_PREMIUM_PLUS:
        if st.button(
            "⬆️ Upgrade to Premium Plus",
            use_container_width=True,
            key=f"plan_cta_{plan_id}",
        ):
            st.session_state.nestai_upgrade_intent = PLAN_PREMIUM_PLUS
            st.session_state.nestai_highlight_plan = None
            st.rerun()


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
            for feat in PREMIUM_FEATURE_LABELS[:5]:
                st.caption(f"✅ {feat}")
        with up_col2:
            st.markdown("**🌟 Premium Plus adds:**")
            for feat in PREMIUM_PLUS_EXTRA_LABELS[:4]:
                st.caption(f"✅ {feat}")

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button(
                "⬆️ Upgrade to Premium",
                use_container_width=True,
                key=f"upgrade_prompt_{feature}_premium",
                type="primary",
            ):
                navigate_to_plans(highlight_plan=PLAN_PREMIUM)
        with btn_col2:
            if st.button(
                "⬆️ Upgrade to Premium Plus",
                use_container_width=True,
                key=f"upgrade_prompt_{feature}_plus",
            ):
                navigate_to_plans(highlight_plan=PLAN_PREMIUM_PLUS)

