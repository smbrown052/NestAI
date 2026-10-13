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
import uuid

import streamlit as st
from auth_service import NestAIAPIClient

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

PREMIUM_FEATURE_LABELS: list[str] = [
    "Compare multiple properties side by side",
    "Richer recommendation cards and decision briefs",
    "Natural-language filtering and priority weighting",
    "Lifestyle Score with deeper tradeoff summaries",
    "AI recommendations, explanations, and reports",
    "Commute analysis and neighborhood intelligence",
    "Exports, saved preferences, and negotiation help",
    "100 analyses per month and up to 50 saved properties",
]

PREMIUM_PLUS_EXTRA_LABELS: list[str] = [
    "Advanced analytics panels and deeper comparison views",
    "Exclusive report styling and highest-limit indicators",
    "Higher AI, map, and commute limits (500 analyses/month)",
    "Up to 200 saved properties and more report generations",
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
    PLAN_FREE: (
        "Explore and organize your options."
    ),
    PLAN_BETA: (
        "Help shape the future of NestAI."
    ),
    PLAN_PREMIUM: (
        "Make confident property decisions."
    ),
    PLAN_PREMIUM_PLUS: (
        "Unlock the most advanced decision intelligence."
    ),
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
        "features": [
            "5 property analyses per month",
            "2 active saved properties across apartments and houses",
            "Apartment and home listing parsing",
            "Basic filters, ranking, and saved preferences",
            "Basic side-by-side comparison",
        ],
        "not_included": [
            "Commute-aware rankings and neighborhood enrichment",
            "Decision briefs, AI reports, and exports",
            "Advanced AI insights and negotiation tools",
        ],
        "cta_label": "Create Free Account",
    },
    {
        "id": PLAN_BETA,
        "name": "Beta",
        "price": "$0",
        "period": "/month",
        "badge": "Beta",
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
        "cta_label": "Start 7-day free trial",
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
        "cta_label": "Start 7-day free trial",
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

    # Plan badge
    badge_map = {
        PLAN_FREE: "🆓 **Free**",
        PLAN_PREMIUM: "⭐ **Premium**",
        PLAN_PREMIUM_PLUS: "🌟 **Premium Plus**",
        PLAN_BETA: "🔬 **Beta**",
    }
    st.markdown(f"**Current plan:** {badge_map.get(plan, plan)}")

    st.caption("Account data is restored after sign-in. Browser sessions may require reauthentication.")
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
    if is_dev_mode() or is_owner_mode_env():
        st.caption("Development previews do not change account entitlements.")


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
            set_plan(selected)
            st.rerun()


# ── Pricing cards ─────────────────────────────────────────────────────────────

def render_pricing_cards(api_client) -> None:
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


    cols = st.columns(4)

    for col, card in zip(cols, PRICING_PLANS):
        with col:
            is_highlighted = (
                highlight == card["id"]
                and not (plan == card["id"])
            )

            _render_plan_card(
                card,
                is_current=(plan == card["id"]),
                highlighted=is_highlighted,
                api_client=api_client,
            )


def _render_plan_card(
    card: dict,
    is_current: bool,
    highlighted: bool = False,
    api_client=None,
) -> None:
    """Render a single plan card."""
    plan_id = card["id"]
    user = st.session_state.get("auth_user") or {}
    existing_subscription = bool(
        st.session_state.get("auth_token")
        and user.get("active_plan") in {"premium", "premium_plus"}
        and user.get("subscription_status") in {"active", "trialing"}
    )
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
    if plan_id == PLAN_PREMIUM and not existing_subscription:
        st.success(
            "🎉 7-day free trial • Then $12/month • Cancel anytime before the trial ends."
        )

    elif plan_id == PLAN_PREMIUM_PLUS and not existing_subscription:
        st.success(
            "🎉 7-day free trial • Then $25/month • Cancel anytime before the trial ends."
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
    elif plan_id in {PLAN_PREMIUM, PLAN_PREMIUM_PLUS}:
        consent = payment = False
        if existing_subscription:
            st.caption("Review the plan change and any prorated charges in your secure billing portal. Access changes only after provider confirmation.")
        else:
            consent = st.checkbox("I consent to trial and recurring billing terms shown at checkout.", key=f"consent_{plan_id}")
            payment = st.checkbox("I will supply a payment method at secure checkout.", key=f"payment_{plan_id}")
        label = "Change subscription securely" if existing_subscription else "Continue to secure checkout"
        if st.button(label, use_container_width=True, key=f"plan_cta_{plan_id}", type="primary"):
            if not st.session_state.get("auth_token"):
                st.session_state.signup_account_type = plan_id.lower()
                st.session_state.main_nav = "Create Account"
                st.rerun()
            elif not existing_subscription and (not consent or not payment):
                st.warning("Please review and accept the billing terms before continuing.")
            else:
                key_name = f"checkout_intent_{plan_id}"
                if existing_subscription:
                    response = api_client.request("POST", "/billing/portal", json={"plan": plan_id.lower()})
                else:
                    intent_key = st.session_state.setdefault(key_name, str(uuid.uuid4()))
                    response = api_client.create_checkout_session(plan_id.lower(), trial_consent=consent, payment_method_confirmed=payment, idempotency_key=intent_key)
                if response.status_code == 200:
                    payload = response.json()
                    st.session_state.pop(key_name, None)
                    st.session_state[f"checkout_url_{plan_id}"] = payload.get("portal_url") if existing_subscription else payload.get("checkout_url")
                    provider_price = payload.get("price", {})
                    if provider_price.get("amount_cents") is not None:
                        st.caption(f"Configured checkout price: {provider_price['amount_cents'] / 100:g} {provider_price.get('currency', '').upper()}. Review the provider's terms; advertised prices above are unchanged.")
                else:
                    st.session_state.pop(f"checkout_url_{plan_id}", None)
                    action = "Subscription management" if existing_subscription else "Checkout"
                    st.error(f"{action} is unavailable. Your current access and balance are unchanged.")
        if st.session_state.get(f"checkout_url_{plan_id}"):
            st.link_button("Continue to Stripe →", st.session_state[f"checkout_url_{plan_id}"], use_container_width=True)


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
