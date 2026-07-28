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

from html import escape

import streamlit as st

from feature_access import (
    PLAN_FREE,
    PLAN_PREMIUM,
    PLAN_PREMIUM_PLUS,
    PLAN_BETA,
    PLAN_OWNER_TEST,
    _PLAN_LABELS,
    capability,
    get_effective_plan,
    get_plan,
    get_quota,
    is_dev_mode,
    is_owner_mode_env,
    is_owner_test,
    monthly_analyses_remaining,
    require_capability,
    set_plan,
)
from ui_theme import plan_meta, tier_class

# ── Canonical feature label lists ─────────────────────────────────────────────
# These are the single source of truth for plan card feature copy.
# Premium Plus features are DERIVED from Premium features + extras so they
# can never silently drift apart.

FREE_FEATURE_LABELS: list[str] = [
    "Full experience for up to 2 saved properties",
    "Apartment and house listing parsing",
    "Lifestyle Score",
    "AI recommendation",
    "Decision comparison",
    "Decision Report",
    "Regret insights",
    "Notes",
    "Time Saved estimate",
]

FREE_NOT_INCLUDED: list[str] = [
    "Upgrade required to save a third active property",
    "Commute-aware rankings and neighborhood enrichment",
    "Multi-property side-by-side comparison",
    "Advanced AI insights and negotiation tools",
]

PREMIUM_FEATURE_LABELS: list[str] = [
    "Everything in Free, plus:",
    "More saved properties (up to 50)",
    "Saved searches and new-listing alerts",
    "Price-drop alerts",
    "Commute calculations and neighborhood intelligence",
    "Multiple saved-search profiles",
    "Comparison history",
    "PDF exports",
    "AI Apartment Advisor",
    "100 analyses per month",
]

PREMIUM_PLUS_EXTRA_LABELS: list[str] = [
    "Negotiation Assistant",
    "Renewal Advisor",
    "True Monthly Cost panel",
    "Advanced Deal Score",
    "Premium AI Insights",
    "Highest usage and enrichment limits (500 analyses/month)",
    "Up to 200 saved properties",
    "Exclusive Unlocked with Premium Plus area",
    "Early access to future ownership and investment tools",
]

BETA_FEATURE_LABELS: list[str] = [
    "Everything in Free with elevated early-access styling",
    "Experimental features clearly labeled as beta",
    "Invite-code access with configurable higher limits",
    "Built-in feedback prompts to help shape NestAI",
    "Modern comparison tools before general release",
]

# Public plan card data ────────────────────────────────────────────────────────
# OWNER_TEST is intentionally excluded — it must never appear on the pricing page.

PLAN_DESCRIPTIONS: dict[str, str] = {
    PLAN_FREE: "Explore and organize up to 2 properties.",
    PLAN_BETA: "Help shape the future of NestAI.",
    PLAN_PREMIUM: "Make confident decisions with full decision intelligence.",
    PLAN_PREMIUM_PLUS: "The most advanced decision and savings tier.",
}

PRICING_PLANS: list[dict] = [
    {
        "id": PLAN_FREE,
        "name": "Free",
        "price": "$0",
        "period": "/month",
        "badge": "Free",
        "description": PLAN_DESCRIPTIONS[PLAN_FREE],
        "eyebrow": "Essentials",
        "features": FREE_FEATURE_LABELS,
        "not_included": FREE_NOT_INCLUDED,
        "cta_label": "Create Free Account",
    },
    {
        "id": PLAN_BETA,
        "name": "Beta",
        "price": "$0",
        "period": "/month",
        "badge": "Beta · Early Access",
        "description": PLAN_DESCRIPTIONS[PLAN_BETA],
        "eyebrow": "Invite only",
        "features": BETA_FEATURE_LABELS,
        "not_included": [
            "Guaranteed long-term availability",
            "Production-grade billing and support commitments",
        ],
        "cta_label": "Join with Invite Code",
        "coming_soon": "Experimental features may change as we learn from feedback.",
    },
    {
        "id": PLAN_PREMIUM,
        "name": "Premium",
        "price": "$12",
        "period": "/month",
        "badge": "Premium",
        "highlight": True,
        "description": PLAN_DESCRIPTIONS[PLAN_PREMIUM],
        "eyebrow": "Recommended",
        "features": PREMIUM_FEATURE_LABELS,
        "cta_label": "Choose Premium",
    },
    {
        "id": PLAN_PREMIUM_PLUS,
        "name": "Premium Plus",
        "price": "$25",
        "period": "/month",
        "badge": "Premium Plus",
        "description": PLAN_DESCRIPTIONS[PLAN_PREMIUM_PLUS],
        "eyebrow": "Most advanced",
        # All Premium features are inherited; extras are listed separately.
        "features": PREMIUM_FEATURE_LABELS,
        "extras": PREMIUM_PLUS_EXTRA_LABELS,
        "cta_label": "Choose Premium Plus",
    },
]

PLAN_FREE_DATA = PRICING_PLANS[0]
PLAN_PREMIUM_DATA = PRICING_PLANS[2]
PLAN_PREMIUM_PLUS_DATA = PRICING_PLANS[3]


def get_pricing_plans() -> list[dict]:
    """Return the public-facing plan card data.

    OWNER_TEST is never included — it is not a public plan.
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
    st.session_state["main_nav"] = "Pricing"
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

    # ── DEV MODE diagnostic banner ────────────────────────────────────────────
    # Visible only when NESTAI_DEV_MODE=true.  Shows the env flag is active and
    # which plan values are currently effective so the dev preview is easy to
    # verify at a glance.  Remove or gate behind is_dev_mode() before release.
    if is_dev_mode() or is_owner_mode_env():
        effective = get_effective_plan()
        preview = get_plan()
        st.error(
            f"🛠 **DEV MODE ENABLED**  \n"
            f"Effective plan: `{effective}`  \n"
            f"Preview plan:   `{preview}`"
        )

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
    if is_dev_mode() or is_owner_mode_env():
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

    Visible only when NESTAI_DEV_MODE=true or NESTAI_OWNER_MODE=true.
    OWNER_TEST is included so all plans can be tested end-to-end.
    """
    _PLAN_OPTS = [PLAN_FREE, PLAN_PREMIUM, PLAN_PREMIUM_PLUS, PLAN_BETA, PLAN_OWNER_TEST]
    _PLAN_DISP = {
        PLAN_FREE: "Free",
        PLAN_PREMIUM: "Premium",
        PLAN_PREMIUM_PLUS: "Premium Plus",
        PLAN_BETA: "Beta",
        PLAN_OWNER_TEST: "Owner Test (Unlimited)",
    }

    with st.expander("🛠 Development Plan Preview", expanded=True):
        st.warning("Development Plan Preview — no payment or subscription changes are being made.")
        current = get_plan()
        current_idx = _PLAN_OPTS.index(current) if current in _PLAN_OPTS else 0
        selected = st.selectbox(
            "Active plan",
            options=_PLAN_OPTS,
            format_func=lambda p: _PLAN_DISP[p],
            index=current_idx,
            key="dev_plan_selector",
        )
        if selected != current:
            _prev = current
            set_plan(selected)
            # Show the PP unlock banner when upgrading to Premium Plus
            if selected == PLAN_PREMIUM_PLUS and _prev in (PLAN_FREE, PLAN_PREMIUM, PLAN_BETA):
                st.session_state["nestai_pp_unlock_banner"] = True
            else:
                st.session_state.pop("nestai_pp_unlock_banner", None)
            st.rerun()


# ── Pricing cards ─────────────────────────────────────────────────────────────

def render_pricing_cards() -> None:
    """Render the public plan cards.

    Reads ``st.session_state["nestai_highlight_plan"]`` to visually emphasise
    a recommended plan (set by navigate_to_plans(highlight_plan=...)).
    """
    plan = get_plan()
    highlight = st.session_state.get("nestai_highlight_plan")

    st.markdown(
        """
        <div class="nestai-hero">
            <div class="nestai-eyebrow">Pricing</div>
            <h2>Decision intelligence for every stage of your search</h2>
            <p class="nestai-subtle">
                Every tier stays polished. Paid tiers add richer analysis, cleaner reporting,
                and more advanced decision support without making the product loud.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Show billing notice if the user just clicked an upgrade CTA
    intent = st.session_state.get("nestai_upgrade_intent")
    if intent and intent in (PLAN_PREMIUM, PLAN_PREMIUM_PLUS):
        intent_label = _PLAN_LABELS.get(intent, intent)
        st.info(
            f"💳 **Billing setup is coming soon.**  \n"
            f"Your selected plan (**{intent_label}**) has been saved for checkout."
        )

    cols = st.columns(4)
    for col, card in zip(cols, PRICING_PLANS):
        with col:
            is_highlighted = highlight == card["id"] and not (plan == card["id"])
            _render_plan_card(card, is_current=(plan == card["id"]), highlighted=is_highlighted)


def _render_plan_card(card: dict, is_current: bool, highlighted: bool = False) -> None:
    """Render a single plan card."""
    plan_id = card["id"]
    visual_plan = PLAN_PREMIUM_PLUS if plan_id == PLAN_OWNER_TEST else plan_id
    classes = ["nestai-tier-card", tier_class(visual_plan)]
    if card.get("highlight") or highlighted:
        classes.append("recommended")

    eyebrow = escape(card.get("eyebrow", plan_meta(visual_plan)["accent"]))
    current_label = "<div class='nestai-badge tier-beta'>Current plan</div>" if is_current else ""
    recommended = (
        "<div class='nestai-badge tier-premium'>Recommended for most renters</div>"
        if card.get("highlight")
        else ""
    )
    highlight_label = (
        "<div class='nestai-badge tier-premium-plus'>Best fit for this unlock</div>"
        if highlighted
        else ""
    )

    st.markdown(
        (
            f"<div class='{' '.join(classes)}'>"
            f"<div class='nestai-eyebrow'>{eyebrow}</div>"
            f"{recommended}{highlight_label}{current_label}"
            f"<h3>{escape(card['name'])}</h3>"
            f"<div><span class='price'>{escape(card['price'])}</span>"
            f"<span class='period'>{escape(card['period'])}</span></div>"
            f"<p class='nestai-subtle'>{escape(card.get('description', ''))}</p>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    if plan_id == PLAN_PREMIUM_PLUS:
        st.markdown("**Everything in Premium, plus:**")
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
        with st.expander("Unavailable or limited", expanded=False):
            for feat in card["not_included"]:
                st.markdown(f"🔒 {feat}")

    if card.get("coming_soon"):
        st.caption(f"Coming Soon: {card['coming_soon']}")

    # CTA button
    if is_current:
        st.button(
            "✓ Current Plan",
            disabled=True,
            use_container_width=True,
            key=f"plan_cta_{plan_id}",
        )
    elif plan_id == PLAN_FREE:
        if st.button(
            card.get("cta_label", "Create Free Account"),
            use_container_width=True,
            key=f"plan_cta_{plan_id}",
        ):
            st.session_state.signup_account_type = "free"
            st.session_state.main_nav = "Create Account"
            st.rerun()
    elif plan_id == PLAN_BETA:
        if st.button(
            card.get("cta_label", "Join with Invite Code"),
            use_container_width=True,
            key=f"plan_cta_{plan_id}",
        ):
            st.session_state.signup_account_type = "beta"
            st.session_state.main_nav = "Create Account"
            st.rerun()
    elif plan_id == PLAN_PREMIUM:
        if st.button(
            card.get("cta_label", "Choose Premium"),
            use_container_width=True,
            key=f"plan_cta_{plan_id}",
            type="primary",
        ):
            st.session_state.nestai_upgrade_intent = PLAN_PREMIUM
            st.session_state.nestai_highlight_plan = None
            st.rerun()
    elif plan_id == PLAN_PREMIUM_PLUS:
        if st.button(
            card.get("cta_label", "Choose Premium Plus"),
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
    feature_copy = {
        "can_use_commute_analysis": (
            "Unlock commute-aware rankings and see how each property affects your daily routine.",
            "Commute context changes which option actually feels livable, not just affordable.",
        ),
        "can_compare_multiple_properties": (
            "Unlock side-by-side comparisons so you can weigh tradeoffs without losing context.",
            "Comparison view turns scattered notes into a confident shortlist.",
        ),
        "can_generate_ai_reports": (
            "Unlock the Decision Report to get a structured recommendation brief instead of raw notes.",
            "Reports help you revisit the shortlist later and explain the choice clearly.",
        ),
        "can_use_ai_explanations": (
            "Unlock AI insight panels that explain why a property fits your priorities.",
            "The extra context makes the ranking easier to trust and act on.",
        ),
        "can_use_walk_score_api": (
            "Unlock neighborhood intelligence with Walk Score, transit context, and nearby essentials.",
            "Location quality is easier to compare when the same metrics appear across every option.",
        ),
        "can_export": (
            "Unlock polished exports so you can share or save your shortlist cleanly.",
            "Exports make the work reusable instead of trapped in a session.",
        ),
        "can_save_property": (
            "Unlock more saved properties so you can compare a serious shortlist instead of one option at a time.",
            "Saving more homes lets NestAI surface better patterns and recommendations.",
        ),
        "can_use_ai_negotiation": (
            "Unlock tailored negotiation support for the units worth pursuing.",
            "It helps you turn analysis into action when you are ready to move.",
        ),
        "default": (
            f"Unlock {label.lower()} with {required_label}.",
            "Upgrading adds richer analysis and a more advanced decision workflow.",
        ),
    }
    headline, why_value = feature_copy.get(feature, feature_copy["default"])

    st.markdown(
        (
            "<div class='nestai-upgrade-card tier-premium-plus'>"
            f"<div class='nestai-eyebrow'>Locked on {escape(current_label)}</div>"
            f"<h3>{escape(label)}</h3>"
            f"<p class='nestai-section-note'>{escape(headline)}</p>"
            f"<p class='nestai-subtle'><strong>Why it matters:</strong> {escape(why_value)}</p>"
            f"<p class='nestai-subtle'><strong>Unlocks on:</strong> {escape(required_label)}</p>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    up_col1, up_col2 = st.columns(2)
    with up_col1:
        st.markdown("**Premium adds**")
        for feat in PREMIUM_FEATURE_LABELS[:4]:
            st.caption(f"✓ {feat}")
    with up_col2:
        st.markdown("**Premium Plus adds**")
        for feat in PREMIUM_PLUS_EXTRA_LABELS[:4]:
            st.caption(f"✓ {feat}")

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button(
            "View Premium",
            use_container_width=True,
            key=f"upgrade_prompt_{feature}_premium",
            type="primary",
        ):
            navigate_to_plans(highlight_plan=PLAN_PREMIUM)
    with btn_col2:
        if st.button(
            "View Premium Plus",
            use_container_width=True,
            key=f"upgrade_prompt_{feature}_plus",
        ):
            navigate_to_plans(highlight_plan=PLAN_PREMIUM_PLUS)
