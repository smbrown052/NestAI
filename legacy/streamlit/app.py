import time as _time
from pathlib import Path

import streamlit as st
import pandas as pd

_DATA_DIR = Path(__file__).parent / "data"
_EXAMPLE_LISTINGS = [
    (_DATA_DIR / "app_listing_1.txt", "Avalon Courthouse Place"),
    (_DATA_DIR / "app_listing_2.txt", "Cortland Bennett Park"),
]
_HOUSE_EXAMPLE_LISTINGS = []
from text_parser import parse_apartment_text, parse_house_listing, filter_units_by_request

for house_path in sorted(_DATA_DIR.rglob("home_example_*.txt")):
    try:
        with open(house_path, "r", encoding="utf-8") as file_handle:
            house_preview = parse_house_listing(file_handle.read())
        house_label = house_preview.get("property_title") or house_path.stem.replace("_", " ").title()
    except Exception:
        house_label = house_path.stem.replace("_", " ").title()
    _HOUSE_EXAMPLE_LISTINGS.append((house_path, house_label))
from enrichment import (
    enrich_units_df,
    enrich_building,
    get_commute_cached,
    compute_monthly_total,
    generate_lifestyle_summary,
    walkscore_api_configured,
    maps_api_configured,
    format_commute_display,
)
from ranking import compute_match_score, explain_match, price_position
from llm_helpers import generate_negotiation_script, advisor_chat_response
from lifestyle_scoring import LifestyleScorer, get_priority_weights_from_sliders
from lifestyle_explanations import generate_lifestyle_explanation, generate_amenities_list
from tradeoff_assistant import TradeoffAnalyzer
try:
    from regret_analyzer import RegretAnalyzer
except Exception:
    import importlib.util

    _regret_path = Path(__file__).with_name("regret_analyzer.py")
    _spec = importlib.util.spec_from_file_location("regret_analyzer", _regret_path)
    if _spec and _spec.loader:
        _module = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_module)
        RegretAnalyzer = _module.RegretAnalyzer
    else:
        raise
from credits import (
    render_tier_badge,
    get_tier,
    has_feature,
    can_enrich_building,
    consume_analysis,
    analyses_remaining,
)
from cache import get_geocode, _address_key
from feedback import submit_feedback, send_feedback_email, validate_beta_code
from ui_state import get_account_type_options, get_navigation_options, plan_display_name
from auth_service import (
    NestAIAPIClient,
    StreamlitAuthManager,
    login_error_message,
    registration_error_message,
    payment_required_message,
    SERVICE_UNAVAILABLE_MESSAGE,
)

st.set_page_config(page_title="NestAI", page_icon="🏠", layout="wide")

# ── Premium visual design ──────────────────────────────────────────────────────
st.markdown(
    """
<style>
/* ── Global typography ───────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', sans-serif;
}

/* ── Decision Recommendation banner ─────────────────────── */
.nestai-decision-banner {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
    border-radius: 14px;
    padding: 28px 32px;
    margin: 18px 0 24px 0;
    border-left: 5px solid #e94560;
    box-shadow: 0 4px 20px rgba(233, 69, 96, 0.18);
}
.nestai-decision-banner h2 {
    color: #fff;
    margin-bottom: 4px;
    font-size: 1.45em;
    font-weight: 700;
    letter-spacing: -0.3px;
}
.nestai-decision-banner .subtitle {
    color: #a8b2d8;
    font-size: 0.92em;
    margin-bottom: 18px;
}
.nestai-decision-pick {
    font-size: 1.15em;
    font-weight: 600;
    color: #e2e8f0;
    margin-bottom: 6px;
}
.nestai-decision-reason {
    color: #a8b2d8;
    font-size: 0.9em;
    line-height: 1.6;
}
.nestai-score-pill {
    display: inline-block;
    background: #e94560;
    color: #fff;
    border-radius: 20px;
    padding: 2px 14px;
    font-size: 0.88em;
    font-weight: 700;
    margin-left: 10px;
    vertical-align: middle;
}

/* ── Ranking card row ────────────────────────────────────── */
.nestai-rank-card {
    border-radius: 12px;
    padding: 18px 22px;
    margin-bottom: 12px;
    border: 1.5px solid #e2e8f0;
    background: #fafbff;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    transition: box-shadow .2s;
}
.nestai-rank-card:hover { box-shadow: 0 4px 18px rgba(0,0,0,0.09); }
.nestai-rank-1 { border-left: 4px solid #e94560; background: #fff8f9; }
.nestai-rank-2 { border-left: 4px solid #f6a623; }
.nestai-rank-3 { border-left: 4px solid #4a90d9; }
.nestai-rank-label { font-size: 0.75em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1px; color: #888; margin-bottom: 2px; }
.nestai-rank-title { font-size: 1.08em; font-weight: 700; color: #1a1a2e; }
.nestai-rank-meta { font-size: 0.88em; color: #555; margin-top: 4px; }
.nestai-price-highlight { font-size: 1.12em; font-weight: 700; color: #1a1a2e; }
.nestai-price-vs-avg { font-size: 0.8em; font-weight: 500; padding: 1px 8px;
    border-radius: 10px; margin-left: 8px; display: inline-block; }
.nestai-above-avg { background: #fff3f5; color: #c0392b; }
.nestai-below-avg { background: #f0fff4; color: #27ae60; }
.nestai-at-avg    { background: #f5f5f5; color: #555; }

/* ── Sidebar locked features ─────────────────────────────── */
.nestai-locked-feature { opacity: 0.6; font-size: 0.85em; }

/* ── Premium Plus accent ─────────────────────────────────── */
.nestai-pp-banner {
    background: linear-gradient(135deg, #7B2FBE 0%, #5a23a0 100%);
    color: #fff;
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 0.85em;
    font-weight: 700;
    display: inline-block;
    margin-bottom: 8px;
    letter-spacing: 0.5px;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🏠 NestAI")
st.markdown("### Find *your* nest.")

api_client = NestAIAPIClient()
auth = StreamlitAuthManager(api_client)


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_travel(mode, minutes):
    if mode and minutes:
        return f"{mode.title()} · {minutes} min"
    return "—"


def openai_configured() -> bool:
    try:
        return bool(st.secrets.get("OPENAI_API_KEY", ""))
    except Exception:
        return False


def _commute_descriptor(minutes) -> str:
    """Return a human-readable commute descriptor from a minute value."""
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        return "—"
    if m <= 10:
        return f"{m} min · Excellent"
    if m <= 20:
        return f"{m} min · Great"
    if m <= 30:
        return f"{m} min · Good"
    if m <= 45:
        return f"{m} min · Manageable"
    return f"{m} min · Long"


def _safety_descriptor(score) -> str:
    """Return a human-readable safety descriptor from a 0–100 score."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "—"
    if s >= 80:
        return f"{s:.0f}/100 · Very Safe"
    if s >= 65:
        return f"{s:.0f}/100 · Safe"
    if s >= 45:
        return f"{s:.0f}/100 · Moderate"
    return f"{s:.0f}/100 · Exercise Caution"


def get_priority_rank(priority_name: str, weights: dict) -> str:
    sorted_priorities = sorted(weights.items(), key=lambda item: item[1], reverse=True)
    position = next(
        (idx for idx, (name, _) in enumerate(sorted_priorities) if name == priority_name),
        None,
    )

    if position is None:
        return "low priority"

    ordinal = ["1st", "2nd", "3rd", "4th", "5th"]
    rank_str = ordinal[position] if position < len(ordinal) else f"{position + 1}th"
    return rank_str


def render_lifestyle_profile_controls() -> None:
    st.markdown("## 🎯 Your Profile")
    st.caption("Used to compute your personal Match %. Commute uses listing distance data.")

    max_budget = st.number_input(
        "💰 Max monthly budget ($)", min_value=0, step=50,
        value=int(st.session_state.user_profile.get("max_budget", 0) or 0),
    )
    preferred_beds = st.selectbox(
        "🛏 Preferred bedrooms",
        options=[None, 0, 1, 2, 3],
        format_func=lambda x: "Any" if x is None else ("Studio" if x == 0 else f"{x} bed"),
        index=0,
    )
    min_sqft = st.number_input(
        "📐 Min square footage", min_value=0, step=25,
        value=int(st.session_state.user_profile.get("min_sqft", 0) or 0),
    )
    commute_tolerance = st.slider(
        "⏱ Max commute (min)", min_value=5, max_value=90, step=5,
        value=int(st.session_state.user_profile.get("commute_tolerance", 30) or 30),
    )
    walk_priority = st.slider(
        "🚶 Walkability priority", min_value=0.0, max_value=1.0, step=0.1,
        value=float(st.session_state.user_profile.get("walk_score_priority", 0.5) or 0.5),
    )

    st.session_state.user_profile = {
        "max_budget": max_budget or None,
        "preferred_beds": preferred_beds,
        "min_sqft": min_sqft or None,
        "commute_tolerance": commute_tolerance,
        "walk_score_priority": walk_priority,
    }


# ── Session state ─────────────────────────────────────────────────────────────

for key, default in {
    "listing_text": "",
    "house_listing_text": "",
    "filtered_df": pd.DataFrame(),
    "comparison_df": pd.DataFrame(),
    "parsed_df": pd.DataFrame(),
    "house_parsed_df": pd.DataFrame(),
    "last_result": None,
    "last_house_result": None,
    "advisor_messages": [],
    "user_profile": {},
    "cost_extras": {},       # {parking, utilities, pet_fee, renters_insurance}
    "enriched_df": pd.DataFrame(),
    "enrichment_done": False,
    "commute_destination": "",
    "paid_features_enabled": False,
    "negotiation_outputs": {},  # unit key -> negotiation text
    # V2: per-building enrichment state: {address: building_dict}
    "building_cache": {},
    # V2: last enrichment request time per address (rate limiting)
    "last_enrich_time": {},
    # Feedback & beta
    "show_feedback_form": False,
    "feedback_submitted_ref": None,
    "beta_tester": False,
    "auth_token": None,
    "auth_user": None,
    "auth_notice": None,
    "auth_error": None,
    "main_nav": "Apartments",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

auth.initialize()
auth.restore_from_session()
auth.sync_user_tier()
api_available = auth.is_api_available()

if auth.is_authenticated():
    st.session_state.paid_features_enabled = (get_tier() in {"beta", "premium", "premium_plus"})
else:
    st.session_state.paid_features_enabled = False

if not api_available:
    st.warning(SERVICE_UNAVAILABLE_MESSAGE)

if st.session_state.auth_notice:
    st.success(st.session_state.auth_notice)
    st.session_state.auth_notice = None

if st.session_state.auth_error:
    st.error(st.session_state.auth_error)
    st.session_state.auth_error = None

nav_options = get_navigation_options(auth.is_authenticated())
if st.session_state.main_nav not in nav_options:
    st.session_state.main_nav = "Profile" if auth.is_authenticated() else "Apartments"

active_screen = st.segmented_control(
    "Navigation",
    options=nav_options,
    selection_mode="single",
    default=st.session_state.main_nav,
)
st.session_state.main_nav = active_screen

if active_screen == "Logout":
    if auth.is_authenticated():
        auth.logout()
        st.session_state.auth_notice = "Signed out successfully."
    st.session_state.main_nav = "Apartments"
    st.rerun()


# ── Sidebar — AI Apartment Advisor ────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🧭 Workspace")
    if auth.is_authenticated():
        user_preview = auth.user() or {}
        st.caption(f"Signed in as {user_preview.get('display_name') or user_preview.get('email')}")
        st.caption(f"Plan: {user_preview.get('active_plan') or user_preview.get('tier', 'free')}")
        st.caption(f"Saved units: {len(st.session_state.comparison_df)}")
        if user_preview.get("subscription_status") == "pending_payment":
            st.warning(payment_required_message(user_preview.get("requested_plan") or user_preview.get("active_plan", "premium")))
    else:
        st.caption("Sign in from the Account tab to save comparisons and access private features.")
        st.caption("Use Profile, Login, or Create Account from the top navigation.")

    # ── Beta Access ─────────────────────────────────────────────────────────
    with st.expander("🔬 Beta Access", expanded=False):
        if st.session_state.beta_tester:
            st.success("✅ Beta features unlocked!")
        else:
            beta_code_input = st.text_input(
                "Enter invite code",
                placeholder="e.g. NEST-BETA-2025",
                type="password",
                key="beta_code_input",
            )
            if st.button("Activate Beta Access", use_container_width=True):
                if validate_beta_code(beta_code_input):
                    st.session_state.beta_tester = True
                    st.success("✅ Beta access activated!")
                    st.rerun()
                else:
                    st.error("Invalid invite code.")

    # ── Free plan locked-feature summary ────────────────────────────────────
    _is_free_plan = not (
        auth.is_authenticated()
        and (st.session_state.paid_features_enabled or st.session_state.beta_tester)
    )
    if _is_free_plan:
        with st.expander("🔒 Locked Features (Free Plan)", expanded=False):
            st.caption("Upgrade to Premium to unlock:")
            for _lf in [
                "🔒 Walk Score & neighborhood enrichment",
                "🔒 Commute analysis (Google Maps)",
                "🔒 AI Advisor chat",
                "🔒 AI explanations & reports",
                "🔒 Negotiation tools",
                "🔒 Multi-property comparison (up to 50)",
                "🔒 Natural-language filtering",
            ]:
                st.markdown(f"<span class='nestai-locked-feature'>{_lf}</span>", unsafe_allow_html=True)
            if st.button("⬆️ View Plans", use_container_width=True, key="sidebar_free_upgrade"):
                st.session_state.main_nav = "Pricing"
                st.rerun()

    st.divider()

    # ── Remove Building ─────────────────────────────────────────────────────
    if auth.is_authenticated() and not st.session_state.comparison_df.empty:
        buildings_available = sorted(
            st.session_state.comparison_df["property"].dropna().unique().tolist()
        )
        if buildings_available:
            st.markdown("## 🗑 Remove Building")
            building_to_remove = st.selectbox(
                "Select building to remove",
                options=["— keep all —"] + buildings_available,
                key="remove_building_select",
            )
            if st.button("Remove Building", use_container_width=True, type="secondary"):
                if building_to_remove and building_to_remove != "— keep all —":
                    st.session_state.comparison_df = st.session_state.comparison_df[
                        st.session_state.comparison_df["property"] != building_to_remove
                    ].reset_index(drop=True)
                    if not st.session_state.enriched_df.empty:
                        st.session_state.enriched_df = st.session_state.enriched_df[
                            st.session_state.enriched_df["property"] != building_to_remove
                        ].reset_index(drop=True)
                    # Clear building cache entry for removed building
                    addr_keys = [
                        k for k in st.session_state.building_cache
                        if building_to_remove.lower() in k.lower()
                    ]
                    for k in addr_keys:
                        del st.session_state.building_cache[k]
                    st.success(f"Removed **{building_to_remove}** from your search.")
                    st.rerun()
            st.divider()

    st.markdown("## 🤖 AI Apartment Advisor")
    st.caption(
        "Ask about commutes, tradeoffs, lifestyle fit, or anything else about your saved units."
    )

    if not has_feature("ai_chat"):
        st.info("🔒 Upgrade to Premium to use the AI Advisor.")
    elif not openai_configured():
        st.info("Add `OPENAI_API_KEY` to Streamlit secrets to enable the advisor.")
    else:
        units_ctx = (
            st.session_state.enriched_df.to_dict("records")
            if not st.session_state.enriched_df.empty
            else st.session_state.comparison_df.to_dict("records")
        )

        for msg in st.session_state.advisor_messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        if prompt := st.chat_input("Ask your advisor…"):
            st.session_state.advisor_messages.append(
                {"role": "user", "content": prompt}
            )
            with st.spinner("Thinking…"):
                try:
                    reply = advisor_chat_response(
                        prompt,
                        st.session_state.advisor_messages[:-1],
                        units_ctx,
                    )
                except Exception as e:
                    reply = f"⚠️ Advisor error: {e}"
            st.session_state.advisor_messages.append(
                {"role": "assistant", "content": reply}
            )
            st.rerun()

        if st.session_state.advisor_messages:
            if st.button("🗑 Clear conversation", use_container_width=True):
                st.session_state.advisor_messages = []
                st.rerun()

    st.divider()

    st.divider()
    st.markdown("## 📑 Navigation")
    if not st.session_state.comparison_df.empty:
        st.markdown(
            """
- [Parse Listing](#parse-listing)
- [Property Summary](#property-summary)
- [Lifestyle Priorities](#lifestyle-priorities)
- [Rankings](#rankings)
- [Full Table](#full-table)
            """
        )
        stat_col1, stat_col2 = st.columns(2)
        with stat_col1:
            st.metric("Total Units", len(st.session_state.comparison_df))
        with stat_col2:
            st.metric("Buildings", st.session_state.comparison_df["property"].nunique())
    else:
        st.caption("Paste an apartment listing to get started.")

    st.divider()
    if st.button(
        "🐛 Report a Bug or Suggest an Improvement",
        use_container_width=True,
        key="open_feedback_btn",
    ):
        st.session_state.show_feedback_form = not st.session_state.show_feedback_form
        st.session_state.feedback_submitted_ref = None
        st.rerun()


if active_screen == "Profile":
    if auth.is_authenticated():
        user = auth.user() or {}
        st.markdown("### 👤 Profile")

        metrics = st.columns(4)
        metrics[0].metric("Display Name", user.get("display_name") or "—")
        metrics[1].metric("Email", user.get("email") or "—")
        metrics[2].metric("Selected Account Type", plan_display_name(user.get("selected_account_type") or user.get("active_plan") or "free"))
        metrics[3].metric("Active Plan", plan_display_name(user.get("active_plan") or user.get("tier", "free")))

        status_cols = st.columns(3)
        status_cols[0].metric("Subscription Status", user.get("subscription_status") or "active")
        payment_status = "Pending" if user.get("subscription_status") == "pending_payment" else ("Paid" if user.get("active_plan") in {"premium", "premium_plus"} else "Not required")
        status_cols[1].metric("Payment Status", payment_status)
        status_cols[2].metric("Beta Access", "Enabled" if user.get("beta_access") else "Disabled")

        usage_cols = st.columns(2)
        usage_cols[0].metric("Saved Units", len(st.session_state.comparison_df))
        usage_cols[1].metric("Saved Buildings", st.session_state.comparison_df["property"].nunique() if not st.session_state.comparison_df.empty and "property" in st.session_state.comparison_df.columns else 0)

        if user.get("beta_approved_at"):
            st.caption(f"Beta approved at {user.get('beta_approved_at')}")

        if user.get("subscription_status") == "pending_payment":
            requested_plan = user.get("requested_plan") or st.session_state.get("signup_account_type", "premium")
            st.warning(payment_required_message(requested_plan))
            checkout_session_id = st.session_state.get("pending_checkout_session_id")
            checkout_url = st.session_state.get("pending_checkout_url")
            if checkout_url:
                st.markdown(f"[Open checkout]({checkout_url})")
            if checkout_session_id and st.button(
                "Confirm payment completed",
                use_container_width=True,
                disabled=not api_available,
            ):
                if auth.confirm_pending_payment():
                    st.session_state.auth_notice = "Payment verified. Premium access activated."
                    st.rerun()

        render_lifestyle_profile_controls()

        if user.get("is_admin"):
            st.info("Admin account")

        if st.button("Logout", key="profile_logout", use_container_width=True):
            auth.logout()
            st.session_state.main_nav = "Apartments"
            st.rerun()
    else:
        st.info("Sign in or create an account to see your profile, saved comparisons, and plan status.")
        if st.button("Go to Login", use_container_width=True):
            st.session_state.main_nav = "Login"
            st.rerun()
        if st.button("Go to Create Account", use_container_width=True):
            st.session_state.main_nav = "Create Account"
            st.rerun()
    st.stop()

if active_screen == "Login":
    st.markdown("### 🔐 Login")
    if not api_available:
        st.info(SERVICE_UNAVAILABLE_MESSAGE)
    with st.form("login_form"):
        login_email = st.text_input("Email", key="login_email")
        login_password = st.text_input("Password", type="password", key="login_password")
        login_submit = st.form_submit_button("Sign In", use_container_width=True, disabled=not api_available)

    if login_submit:
        with st.spinner("Signing you in..."):
            response = auth.login(login_email, login_password)
            if response.status_code == 200:
                token = response.json()["access_token"]
                auth.api_client.set_token(token)
                me_response = auth.fetch_current_user()
                if me_response.status_code == 200:
                    auth.set_authenticated(token, me_response.json())
                    st.session_state.auth_notice = "Signed in successfully."
                    st.session_state.main_nav = "Profile"
                    st.rerun()
                else:
                    st.session_state.auth_error = "Could not load your profile after signing in."
            else:
                st.session_state.auth_error = login_error_message(response.status_code)
            st.rerun()
    st.stop()

if active_screen == "Create Account":
    st.markdown("### ✨ Create Account")
    if not api_available:
        st.info(SERVICE_UNAVAILABLE_MESSAGE)
    account_type_options = get_account_type_options()
    selected_account_type = st.selectbox(
        "Account type",
        options=account_type_options,
        format_func=plan_display_name,
        index=account_type_options.index(st.session_state.get("signup_account_type", "free")) if st.session_state.get("signup_account_type", "free") in account_type_options else 0,
        key="create_account_type",
    )
    st.session_state.signup_account_type = selected_account_type

    if selected_account_type == "beta":
        st.info("Beta access is invite-only. A valid invite code is required.")
    elif selected_account_type == "premium":
        st.info("Payment setup is coming soon. Your account will be created as Free with Premium requested.")
    elif selected_account_type == "premium_plus":
        st.info("Payment setup is coming soon. Your account will be created as Free with Premium Plus requested.")

    with st.form("register_form"):
        register_name = st.text_input("Display name", key="register_name")
        register_email = st.text_input("Email", key="register_email")
        register_password = st.text_input("Password", type="password", key="register_password")
        st.caption(
            "Password must be at least 8 characters and include an uppercase letter, "
            "a lowercase letter, and a number."
        )
        beta_invite_code = None
        if selected_account_type == "beta":
            beta_invite_code = st.text_input("Beta invite code", type="password", key="beta_invite_code")
        register_submit = st.form_submit_button("Create Account", use_container_width=True, disabled=not api_available)

    if register_submit:
        with st.spinner("Creating your account..."):
            response = auth.register(
                register_email,
                register_password,
                register_name,
                account_type=selected_account_type,
                beta_invite_code=beta_invite_code,
            )

            if response.status_code in {200, 201}:
                payload = response.json()
                user_payload = payload.get("user") or payload
                token = payload.get("access_token")
                if token:
                    auth.set_authenticated(token, user_payload)
                checkout_session_id = payload.get("checkout_session_id")
                checkout_url = payload.get("checkout_url")
                auth.store_checkout(checkout_session_id, checkout_url)

                if selected_account_type in {"premium", "premium_plus"}:
                    st.session_state.auth_notice = payload.get("payment_required_message") or payment_required_message(selected_account_type)
                    st.session_state.main_nav = "Profile"
                else:
                    st.session_state.auth_notice = "Account created and signed in."
                    st.session_state.main_nav = "Profile"
                st.rerun()
            else:
                if selected_account_type == "beta" and response.status_code == 401:
                    st.session_state.auth_error = "Invalid beta invite code."
                else:
                    st.session_state.auth_error = registration_error_message(response.status_code)
                st.rerun()
    st.stop()

if active_screen == "Pricing":
    from plan_ui import render_pricing_cards
    render_pricing_cards()

    # ── Beta plan (invite-only, shown separately from purchasable plans) ───
    st.divider()
    st.markdown("#### 🔬 Beta — Invite Only")
    _bc1, _bc2 = st.columns([2, 1])
    with _bc1:
        st.markdown(
            "Early access for invited testers. Full Premium feature set with configurable "
            "quotas during the beta period — **no payment required**."
        )
        for _bf in [
            "✅ Everything in Free",
            "✅ Full AI feature set (within beta quotas)",
            "✅ Commute and neighborhood enrichment",
            "✅ Multi-property comparison",
            "✅ Lifestyle Score and AI explanations",
            "✅ Early access to new features",
        ]:
            st.caption(_bf)
    with _bc2:
        if st.button("🔬 Join Beta (invite code)", use_container_width=True, key="pricing_beta"):
            st.session_state.signup_account_type = "beta"
            st.session_state.main_nav = "Create Account"
            st.rerun()

    st.divider()
    st.caption(
        "Premium and Premium Plus require payment setup before activation. "
        "Accounts are created as Free with your selected plan recorded. "
        "Beta is invite-only and free during the beta period."
    )
    # Quick sign-up shortcuts
    st.markdown("#### Ready to get started?")
    _pc1, _pc2, _pc3 = st.columns(3)
    with _pc1:
        if st.button("Create Free Account", key="pricing_free", use_container_width=True):
            st.session_state.signup_account_type = "free"
            st.session_state.main_nav = "Create Account"
            st.rerun()
    with _pc2:
        if st.button("Choose Premium", key="pricing_premium", use_container_width=True):
            st.session_state.signup_account_type = "premium"
            st.session_state.main_nav = "Create Account"
            st.rerun()
    with _pc3:
        if st.button("Choose Premium Plus", key="pricing_premium_plus", use_container_width=True):
            st.session_state.signup_account_type = "premium_plus"
            st.session_state.main_nav = "Create Account"
            st.rerun()
    st.stop()

if active_screen == "Houses":
    st.markdown("### 🏡 Houses")
    st.caption("Analyze house listings with the same parser and comparison workflow.")

    house_buttons = st.columns(3)

    if len(_HOUSE_EXAMPLE_LISTINGS) > 0:
        with house_buttons[0]:
            if st.button(f"🏡 {_HOUSE_EXAMPLE_LISTINGS[0][1]}", use_container_width=True):
                with open(_HOUSE_EXAMPLE_LISTINGS[0][0], "r", encoding="utf-8") as f:
                    st.session_state.house_listing_text = f.read()
                st.rerun()

    if len(_HOUSE_EXAMPLE_LISTINGS) > 1:
        with house_buttons[1]:
            if st.button(f"🏡 {_HOUSE_EXAMPLE_LISTINGS[1][1]}", use_container_width=True):
                with open(_HOUSE_EXAMPLE_LISTINGS[1][0], "r", encoding="utf-8") as f:
                    st.session_state.house_listing_text = f.read()
                st.rerun()

    with house_buttons[2]:
        if st.button("🧹 Clear House Text", use_container_width=True):
            st.session_state.house_listing_text = ""
            st.session_state.last_house_result = None
            st.session_state.house_parsed_df = pd.DataFrame()
            st.rerun()

    if len(_HOUSE_EXAMPLE_LISTINGS) == 0:
        st.info("No house examples found. Add `home_example_*.txt` files in the data folder.")

    house_listing_text = st.text_area(
        "House listing text",
        key="house_listing_text",
        height=380,
        placeholder="Paste copied house listing text here...",
    )

    analyze_house = st.button("✨ Analyze House", use_container_width=True)

    if analyze_house:
        if house_listing_text.strip():
            house_result = parse_house_listing(house_listing_text)
            st.session_state.last_house_result = house_result
            st.session_state.house_parsed_df = pd.DataFrame(house_result.get("units", []))
        else:
            st.warning("Paste house listing text first.")

    if st.session_state.last_house_result:
        house_result = st.session_state.last_house_result
        house_building = house_result.get("building_nearby", {})

        st.markdown("### 🏠 House Summary")
        st.markdown(f"**{house_result.get('property_title') or 'Unknown'}**")

        hm1, hm2, hm3 = st.columns(3)
        hm1.metric("Units Parsed", house_result.get("unit_count", 0))
        hm2.metric(
            "Nearest Metro",
            format_travel(house_building.get("metro_travel_mode"), house_building.get("metro_min")),
        )
        hm3.metric(
            "Nearest Hospital",
            format_travel(house_building.get("hospital_travel_mode"), house_building.get("hospital_min")),
        )

        if house_result.get("address"):
            st.caption(house_result.get("address"))

        if not st.session_state.house_parsed_df.empty:
            st.markdown("### 📋 Parsed House Units")
            st.dataframe(st.session_state.house_parsed_df, use_container_width=True)

            if st.button("➕ Save House Units", use_container_width=True):
                st.session_state.comparison_df = pd.concat(
                    [st.session_state.comparison_df, st.session_state.house_parsed_df],
                    ignore_index=True,
                )
                st.success("House units added!")
                st.rerun()
        else:
            st.warning("No house unit rows were parsed from this listing.")

    st.stop()

if active_screen == "Apartments":
    pass

if active_screen not in {"Apartments", "Houses", "Pricing", "Profile", "Login", "Create Account", "Logout"}:
    st.stop()


# ── Hero / Intro ──────────────────────────────────────────────────────────────

st.markdown("""
<div class="hero">
    <p>
    Find your next apartment in seconds. Compare floor plans, pricing,
    square footage, metro access, and amenities without building spreadsheets.
    </p>
</div>
""", unsafe_allow_html=True)

with st.expander("Why Nest AI?", expanded=False):
    st.write("""
Apartment hunting means comparing dozens of tabs, prices, floor plans, fees, locations, and
availability dates — manually. Nest AI turns raw Apartments.com listing text into ranked,
enriched, personalized recommendations with commute times, neighborhood data, and AI-powered
negotiation tools.
""")

with st.expander("ℹ️ How to use NestAI", expanded=False):
    st.write("""
    **Try an example or paste your own listing:**

    1. Open an apartment listing on Apartments.com.
    2. Expand all floor plans and click **Show More** so all units are visible.
    3. Press **Ctrl + A** then **Ctrl + C** to copy everything on the page.
    4. Paste the text in the box below and click **✨ Analyze Apartment**.
    5. Click **➕ Save Units** to add them to your comparison table.
    6. Repeat for each building you want to compare (or load Example 1/2).
    7. Optionally enable paid APIs for AI + official Walk/Transit/Bike scores.
    8. Adjust Lifestyle Priority sliders, then review Rankings, Tradeoffs, and Concerns.

    **To remove a building** from your search, use the 🗑 Remove Building panel in the sidebar.
    """)

# ── Paste & Analyze ───────────────────────────────────────────────────────────

st.markdown("### 1. Paste Listing Text")

c1, c2, c3 = st.columns(3)

with c1:
    if st.button("🏢 Avalon Courthouse Place", use_container_width=True):
        with open(_EXAMPLE_LISTINGS[0][0], "r", encoding="utf-8") as f:
            st.session_state.listing_text = f.read()
        st.rerun()

with c2:
    if st.button("🏢 Cortland Bennett Park", use_container_width=True):
        with open(_EXAMPLE_LISTINGS[1][0], "r", encoding="utf-8") as f:
            st.session_state.listing_text = f.read()
        st.rerun()

with c3:
    if st.button("🧹 Clear Text", use_container_width=True):
        st.session_state.listing_text = ""
        st.session_state.last_result = None
        st.session_state.parsed_df = pd.DataFrame()
        st.rerun()

listing_text = st.text_area(
    "Apartment listing text",
    key="listing_text",
    height=380,
    placeholder="Paste copied Apartments.com listing text here…",
)

analyze = st.button("✨ Analyze Apartment", use_container_width=True)

if analyze:
    if st.session_state.listing_text.strip():
        result = parse_apartment_text(st.session_state.listing_text)
        st.session_state.last_result = result
        st.session_state.parsed_df = pd.DataFrame(result.get("units", []))
    else:
        st.warning("Paste listing text first.")

# ── Property Summary ──────────────────────────────────────────────────────────

if st.session_state.last_result:
    result = st.session_state.last_result
    building = result.get("building_nearby", {})

    st.markdown("### <a id='property-summary'>🏠 Property Summary</a>", unsafe_allow_html=True)

    property_title = result.get("property_title") or "Unknown"
    st.markdown(f"**{property_title}**")

    m2, m3, m4, m5 = st.columns(4)

    m2.metric("Units Parsed", result.get("unit_count", 0))

    # Use text-parsed metro data; fall back to API-enriched data if not found
    metro_min = building.get("metro_min")
    metro_travel_mode = building.get("metro_travel_mode")
    if metro_min is None:
        address_key = result.get("address", "")
        enriched_building = st.session_state.building_cache.get(address_key, {})
        if enriched_building.get("metro_min") is not None:
            metro_min = enriched_building["metro_min"]
            metro_travel_mode = enriched_building.get("metro_travel_mode")

    metro_val = format_travel(metro_travel_mode, metro_min)
    m3.metric(
        "Nearest Metro",
        metro_val if metro_val != "—" else "Not found",
    )
    if metro_val == "—":
        m3.caption("No transit stop found within ~30 min or transit data unavailable.")
    m4.metric(
        "Nearest Hospital",
        format_travel(building.get("hospital_travel_mode"), building.get("hospital_min")),
    )

    walk_score = (
        result.get("units", [{}])[0].get("walk_score") if result.get("units") else None
    )
    safety_score = (
        result.get("units", [{}])[0].get("safety_score") if result.get("units") else None
    )
    m5.metric(
        "Walk Score",
        f"{walk_score} / 100" if walk_score is not None else "—",
    )

    if result.get("address"):
        st.caption(result.get("address"))
    if safety_score is not None:
        st.caption(f"Safety Score: {safety_score} / 100 (derived from renter rating)")

    if result.get("nearby_places"):
        with st.expander("View nearby building-level places"):
            st.dataframe(pd.DataFrame(result["nearby_places"]), use_container_width=True)

    if not st.session_state.parsed_df.empty:
        st.markdown("### 📋 Parsed Units")
        st.caption("Units extracted from this listing. Save them to add them to your comparison.")
        st.dataframe(st.session_state.parsed_df, use_container_width=True)

        # Cost of living extras for this property
        with st.expander("💵 Set optional monthly fees for this property"):
            cols = st.columns(4)
            parking_fee = cols[0].number_input("Parking ($/mo)", min_value=0, step=25, key="parking_input")
            utilities = cols[1].number_input("Utilities ($/mo)", min_value=0, step=10, key="utilities_input")
            pet_fee = cols[2].number_input("Pet Fee ($/mo)", min_value=0, step=10, key="pet_fee_input")
            insurance = cols[3].number_input("Renter's Insurance ($/mo)", min_value=0, step=5, key="insurance_input")
            st.session_state.cost_extras = {
                "parking": parking_fee or None,
                "utilities": utilities or None,
                "pet_fee": pet_fee or None,
                "renters_insurance": insurance or None,
            }
            if any(st.session_state.cost_extras.values()):
                example_price = st.session_state.parsed_df["price_num"].dropna().median()
                if pd.notna(example_price):
                    breakdown = compute_monthly_total(example_price, st.session_state.cost_extras)
                    st.markdown("**Sample cost breakdown (median unit rent):**")
                    for label, val in breakdown.items():
                        prefix = "**" if label == "Estimated Total" else ""
                        suffix = "**" if label == "Estimated Total" else ""
                        st.write(f"{prefix}{label}: ${int(val):,}{suffix}")

        if auth.is_authenticated():
            if st.button("➕ Save Units", use_container_width=True):
                new_rows = st.session_state.parsed_df.copy()
                for col, val in (st.session_state.cost_extras or {}).items():
                    if val is not None:
                        new_rows[f"extra_{col}"] = val
                st.session_state.comparison_df = pd.concat(
                    [st.session_state.comparison_df, new_rows],
                    ignore_index=True,
                )
                st.session_state.enrichment_done = False
                st.success("Units added!")
                st.rerun()
        else:
            st.info("Sign in to save units to your comparison table.")
    else:
        st.warning("No unit rows were parsed from this listing.")

# ── Filter & Rank ─────────────────────────────────────────────────────────────

st.markdown("### <a id='lifestyle-priorities'>🎯 Lifestyle Priorities</a>", unsafe_allow_html=True)

if auth.is_authenticated() and not st.session_state.comparison_df.empty:
    comp_df = st.session_state.comparison_df.copy()

    st.info("Adjust these sliders to personalize the lifestyle ranking.")
    priority_col1, priority_col2, priority_col3 = st.columns(3)
    with priority_col1:
        commute_priority = st.slider("🚇 Commute", 1, 5, 3, key="commute_slider")
        safety_priority = st.slider("🛡️ Safety", 1, 5, 3, key="safety_slider")
    with priority_col2:
        nightlife_priority = st.slider("🍻 Nightlife", 1, 5, 2, key="nightlife_slider")
        budget_priority = st.slider("💰 Budget", 1, 5, 4, key="budget_slider")
    with priority_col3:
        gym_priority = st.slider("💪 Gym/Fitness", 1, 5, 2, key="gym_slider")

    st.markdown("### 🔎 Filter Your Apartments")

    min_price = int(comp_df["price_num"].min())
    max_price = int(comp_df["price_num"].max())

    price_range = st.slider(
        "Monthly rent range",
        min_value=min_price,
        max_value=max_price,
        value=(min_price, max_price),
        step=50,
    )

    min_sqft = int(comp_df["sqft_num"].min())
    max_sqft = int(comp_df["sqft_num"].max())

    sqft_range = st.slider(
        "Square footage range",
        min_value=min_sqft,
        max_value=max_sqft,
        value=(min_sqft, max_sqft),
        step=25,
    )

    llm_request = st.text_input(
        "Ask Nest AI to filter your saved units",
        value="1 bed not on the first floor within 10 min walk of metro",
    )

    # ── Level 2 Enrichment (cache-first, building-level, credit-gated) ────────

    enrich_col, status_col = st.columns([1, 2])

    # Determine which buildings still need enrichment
    addresses_in_view = (
        comp_df["address"].dropna().unique().tolist()
        if "address" in comp_df.columns
        else []
    )
    already_enriched = {
        addr
        for addr in addresses_in_view
        if addr in st.session_state.building_cache
    }
    needs_enrichment = [a for a in addresses_in_view if a not in already_enriched]

    # Rate-limit: 10-second cooldown per address per session
    _ENRICH_COOLDOWN = 10
    now_ts = _time.time()

    can_enrich = (
        has_feature("walk_score")
        and (maps_api_configured() or walkscore_api_configured())
        and len(needs_enrichment) > 0
        and analyses_remaining() > 0
    )

    with enrich_col:
        enrich_clicked = st.button(
            "🌐 Enrich Neighborhoods",
            use_container_width=True,
            disabled=not can_enrich,
            help=(
                "Fetches Walk Score, neighborhood amenities, and commute data. "
                "Uses 1 credit per unique building. Results are cached for all users."
            ),
        )
    with status_col:
        if not has_feature("walk_score"):
            st.caption(
                f"🔒 Neighborhood enrichment requires Premium. "
                f"Upgrade to unlock Walk Score, commute & amenities."
            )
        elif not maps_api_configured() and not walkscore_api_configured():
            st.caption("Add API keys to Streamlit secrets to enable enrichment.")
        elif analyses_remaining() == 0:
            st.caption("⚠️ No analysis credits remaining. Purchase more to continue.")
        elif st.session_state.enrichment_done and not needs_enrichment:
            st.caption("✅ All buildings enriched — showing cached neighborhood data.")
        elif needs_enrichment:
            st.caption(
                f"Ready to enrich {len(needs_enrichment)} building(s). "
                f"Uses {len(needs_enrichment)} credit(s). "
                f"{analyses_remaining()} remaining."
            )
        else:
            st.caption("✅ Enrichment complete.")

    if enrich_clicked and can_enrich:
        enriched_count = 0
        throttled = []
        with st.spinner("Enriching neighborhoods (cache-first)…"):
            for addr in needs_enrichment:
                # Per-address rate limit
                last_ts = st.session_state.last_enrich_time.get(addr, 0)
                if now_ts - last_ts < _ENRICH_COOLDOWN:
                    throttled.append(addr)
                    continue

                # Determine a stable building_id for credit tracking
                geo = get_geocode(addr)
                building_id = (
                    geo.get("google_place_id") or geo.get("building_id") or _address_key(addr)
                    if geo
                    else _address_key(addr)
                )

                if not can_enrich_building(building_id):
                    st.warning("Credit limit reached during enrichment.")
                    break

                building_data = enrich_building(addr)
                if building_data:
                    consume_analysis(building_id)
                    st.session_state.building_cache[addr] = building_data
                    st.session_state.last_enrich_time[addr] = now_ts
                    enriched_count += 1

        if throttled:
            st.info(f"⏳ {len(throttled)} address(es) throttled (retry in {_ENRICH_COOLDOWN}s).")

        if enriched_count > 0 or already_enriched:
            st.session_state.enriched_df = enrich_units_df(
                st.session_state.comparison_df,
                st.session_state.commute_destination,
            )
            st.session_state.enrichment_done = True
        st.rerun()

    # Use enriched data if available, otherwise fall back to raw comparison data
    working_df = (
        st.session_state.enriched_df
        if st.session_state.enrichment_done and not st.session_state.enriched_df.empty
        else comp_df
    )

    filtered_comp_df = working_df[
        (working_df["price_num"] >= price_range[0])
        & (working_df["price_num"] <= price_range[1])
        & (working_df["sqft_num"] >= sqft_range[0])
        & (working_df["sqft_num"] <= sqft_range[1])
    ]

    filtered_comp_df = filter_units_by_request(filtered_comp_df, llm_request)

    weights = get_priority_weights_from_sliders(
        commute_priority,
        safety_priority,
        nightlife_priority,
        budget_priority,
        gym_priority,
    )

    # ── Rankings ───────────────────────────────────────────────────────────
    st.markdown("### <a id='rankings'>🏆 Nest AI Recommendations</a>", unsafe_allow_html=True)
    st.caption("Ranked by your lifestyle priorities, listing data, and your personal profile.")

    if filtered_comp_df.empty:
        st.warning("No saved units match your filters.")
    else:
        ranked_df = LifestyleScorer(weights).score_apartments(filtered_comp_df.copy())

        ranked_df["price_score"] = ranked_df["price_num"].rank(ascending=False)
        ranked_df["space_score"] = ranked_df["sqft_num"].rank(ascending=True)

        if "metro_min" in ranked_df.columns:
            ranked_df["metro_score"] = ranked_df["metro_min"].fillna(99).rank(ascending=False)
        else:
            ranked_df["metro_score"] = 0

        if "floor" in ranked_df.columns:
            ranked_df["floor_score"] = ranked_df["floor"].fillna(0).rank(ascending=True)
        else:
            ranked_df["floor_score"] = 0

        for ws_col in ("official_walk_score", "walk_score"):
            if ws_col in ranked_df.columns:
                ranked_df["walk_score_score"] = ranked_df[ws_col].fillna(0).rank(ascending=True)
                break
        else:
            ranked_df["walk_score_score"] = 0

        if "safety_score" in ranked_df.columns:
            ranked_df["safety_score_rank"] = ranked_df["safety_score"].fillna(0).rank(ascending=True)
        else:
            ranked_df["safety_score_rank"] = 0

        # Boost score when commute data is available
        if "commute_transit_min" in ranked_df.columns:
            ranked_df["commute_score"] = ranked_df["commute_transit_min"].fillna(99).rank(ascending=False)
            commute_weight = 0.15
            metro_weight = 0.05
        else:
            ranked_df["commute_score"] = 0
            commute_weight = 0.0
            metro_weight = 0.20

        ranked_df["nest_score"] = (
            ranked_df["price_score"] * 0.30
            + ranked_df["space_score"] * 0.25
            + ranked_df["metro_score"] * metro_weight
            + ranked_df["commute_score"] * commute_weight
            + ranked_df["floor_score"] * 0.10
            + ranked_df["walk_score_score"] * 0.10
            + ranked_df["safety_score_rank"] * 0.05
        )

        # ── Compute unified NestAI Score (0–100) ───────────────────────────
        # Normalise raw nest_score rank sum to 0–1 range
        ns_max = ranked_df["nest_score"].max()
        ns_min = ranked_df["nest_score"].min()
        ns_range = ns_max - ns_min if ns_max != ns_min else 1.0
        ranked_df["nest_score_norm"] = (
            (ranked_df["nest_score"] - ns_min) / ns_range
        ) * 100.0

        profile_set = any(st.session_state.user_profile.values())

        def _compute_nestai_score(row_: pd.Series) -> float:
            lifestyle = float(row_.get("lifestyle_score", 0) or 0)
            nest_norm = float(row_.get("nest_score_norm", 0) or 0)
            if profile_set:
                match = compute_match_score(row_, st.session_state.user_profile)
                return round(0.60 * lifestyle + 0.25 * match + 0.15 * nest_norm, 1)
            return round(0.85 * lifestyle + 0.15 * nest_norm, 1)

        ranked_df["nestai_score"] = ranked_df.apply(_compute_nestai_score, axis=1)

        ranked_df = ranked_df.sort_values(
            ["nestai_score", "lifestyle_score"],
            ascending=[False, False],
        )
        top3 = ranked_df.head(3)

        # ── Decision Recommendation banner ─────────────────────────────────
        if not top3.empty:
            top_row = top3.iloc[0]
            top_price = top_row.get("price_num")
            top_sqft = top_row.get("sqft_num")
            top_score = top_row.get("nestai_score", 0)
            top_diff, top_avg = price_position(top_row, ranked_df)

            _price_vs = ""
            if top_diff is not None and top_avg:
                if abs(top_diff) < 30:
                    _price_vs = f"at the comparable average (${top_avg:,.0f}/mo for {int(top_row.get('beds_num', 0))}-bed)"
                elif top_diff < 0:
                    _price_vs = f"${abs(top_diff):,} below the ${top_avg:,.0f}/mo average for {int(top_row.get('beds_num', 0))}-bed units"
                else:
                    _price_vs = f"${abs(top_diff):,} above the ${top_avg:,.0f}/mo average for {int(top_row.get('beds_num', 0))}-bed units"

            _commute_d = ""
            for _cc in ("commute_transit_min", "commute_driving_min", "metro_min"):
                _cv = top_row.get(_cc)
                if _cv is not None and not (isinstance(_cv, float) and pd.isna(_cv)):
                    _commute_d = _commute_descriptor(_cv)
                    break

            _reason_parts = []
            if top_diff is not None and top_diff <= 0:
                _reason_parts.append(f"priced {_price_vs}")
            if _commute_d and "Long" not in _commute_d:
                _reason_parts.append(f"commute is {_commute_d.split(' · ')[0].strip()} min ({_commute_d.split(' · ')[-1] if ' · ' in _commute_d else ''})")
            if not _reason_parts:
                _reason_parts.append(f"highest overall NestAI Score of {top_score:.0f}/100 across your saved units")

            _reason_str = " · ".join(_reason_parts) if _reason_parts else f"NestAI Score {top_score:.0f}/100"

            st.markdown(
                f"""
<div class="nestai-decision-banner">
  <div class="subtitle">🏆 NESTAI DECISION RECOMMENDATION</div>
  <div class="nestai-decision-pick">
    {top_row.get('property', 'Unknown')} &nbsp;·&nbsp; Unit {top_row.get('unit', 'N/A')}
    <span class="nestai-score-pill">{top_score:.0f}/100</span>
  </div>
  <div class="nestai-decision-reason">
    NestAI recommends this unit above your other saved options — {_reason_str}.
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

        # ── Top-3 polished cards ────────────────────────────────────────────
        _rank_colors = ["nestai-rank-1", "nestai-rank-2", "nestai-rank-3"]
        _rank_medals = ["🥇", "🥈", "🥉"]

        for i, (_, row) in enumerate(top3.iterrows(), start=1):
            price_num = row.get("price_num")
            sqft_num = row.get("sqft_num")
            price_display = int(price_num) if pd.notna(price_num) else 0
            sqft_display = int(sqft_num) if pd.notna(sqft_num) else 0
            nestai_score = row.get("nestai_score", 0)

            # Price vs comparable average — explicit dollar + avg shown
            diff, avg = price_position(row, ranked_df)
            if diff is not None and avg:
                beds_label = "studio" if row.get("beds_num") == 0 else f"{int(row.get('beds_num', 1))}-bed"
                avg_note = f"avg ${avg:,.0f}/mo for {beds_label}"
                if abs(diff) < 30:
                    price_badge_cls = "nestai-at-avg"
                    price_badge_text = f"≈ {avg_note}"
                elif diff < 0:
                    price_badge_cls = "nestai-below-avg"
                    price_badge_text = f"${abs(diff):,} below · {avg_note}"
                else:
                    price_badge_cls = "nestai-above-avg"
                    price_badge_text = f"${abs(diff):,} above · {avg_note}"
                price_badge_html = f'<span class="nestai-price-vs-avg {price_badge_cls}">{price_badge_text}</span>'
            else:
                price_badge_html = ""

            # Commute descriptor
            commute_html = ""
            for _cc in ("commute_transit_min", "commute_driving_min", "metro_min"):
                _cv = row.get(_cc)
                if _cv is not None and not (isinstance(_cv, float) and pd.isna(_cv)):
                    commute_html = f'<span style="color:#555;font-size:0.87em;">🚇 {_commute_descriptor(_cv)}</span>'
                    break

            _card_cls = _rank_colors[i - 1] if i <= 3 else ""
            st.markdown(
                f"""
<div class="nestai-rank-card {_card_cls}">
  <div class="nestai-rank-label">{_rank_medals[i-1]} Rank #{i}</div>
  <div class="nestai-rank-title">{row.get('property', 'Unknown')} &nbsp;&middot;&nbsp; Unit {row.get('unit', 'N/A')}</div>
  <div class="nestai-rank-meta">
    <span class="nestai-price-highlight">${price_display:,}/mo</span>
    {price_badge_html}
    &nbsp;&nbsp;·&nbsp;&nbsp;{sqft_display:,} sqft
    &nbsp;&nbsp;·&nbsp;&nbsp;{row.get('beds', '')} {row.get('baths', '')}
    &nbsp;&nbsp;·&nbsp;&nbsp;NestAI Score <strong>{nestai_score:.0f}</strong>/100
  </div>
  {'<div style="margin-top:5px;">' + commute_html + '</div>' if commute_html else ''}
</div>
""",
                unsafe_allow_html=True,
            )

        st.markdown("#### 🎯 Breakdown")
        st.caption(
            "NestAI Score = 60% Lifestyle + 25% Profile Match + 15% Relative Rank "
            "(or 85%/15% when no profile is set)."
        )
        tradeoff = TradeoffAnalyzer(ranked_df) if len(ranked_df) > 1 else None
        regret_analyzer = RegretAnalyzer(ranked_df, weights)
        for rank, (_, row) in enumerate(top3.iterrows(), start=1):
            unit_id = row.get("unit", f"Unit {rank}")
            overview_price = row.get("price_num")
            overview_sqft = row.get("sqft_num")
            with st.expander(
                f"Rank #{rank} · {row.get('property', 'Unknown')} · Unit {unit_id}",
                expanded=(rank == 1),
            ):
                tab1, tab2, tab3, tab4 = st.tabs(
                    ["📊 Overview", "🏠 Amenities", "💡 Tradeoffs", "⚠️ Concerns"]
                )
                component_scores = {
                    "commute": row.get("lifestyle_commute_score", 0),
                    "safety": row.get("lifestyle_safety_score", 0),
                    "nightlife": row.get("lifestyle_nightlife_score", 0),
                    "budget": row.get("lifestyle_budget_score", 0),
                    "gym": row.get("lifestyle_gym_score", 0),
                }

                with tab1:
                    score_cols = st.columns(3)
                    score_cols[0].metric("NestAI Score", f"{row.get('nestai_score', 0):.0f}/100")
                    _op = int(overview_price) if pd.notna(overview_price) else 0
                    _diff_t, _avg_t = price_position(row, ranked_df)
                    _price_delta = f"${abs(_diff_t):,} {'above' if _diff_t and _diff_t >= 0 else 'below'} avg" if _diff_t is not None else None
                    score_cols[1].metric(
                        "Rent",
                        f"${_op:,}/mo",
                        delta=_price_delta,
                        delta_color="inverse",
                    )
                    score_cols[2].metric(
                        "Sq Ft",
                        f"{int(overview_sqft) if pd.notna(overview_sqft) else 0:,}",
                    )
                    st.markdown(
                        generate_lifestyle_explanation(
                            rank,
                            row,
                            component_scores,
                            weights,
                            ranked_df,
                            priority_rank_fn=lambda name: get_priority_rank(name, weights),
                        )
                    )

                with tab2:
                    st.markdown("**Building Amenities**")
                    st.markdown(generate_amenities_list(row))
                    amenity_col1, amenity_col2 = st.columns(2)
                    with amenity_col1:
                        # Commute — descriptor only (no raw score numbers)
                        metro_min_val = row.get("metro_min")
                        if metro_min_val is not None and pd.notna(metro_min_val):
                            st.write(f"🚇 **Metro:** {_commute_descriptor(metro_min_val)}")
                        else:
                            st.write("🚇 **Metro:** Not found")
                            st.caption("No transit stop found within ~30 min or transit data unavailable.")
                        hosp_min = row.get("hospital_min")
                        if hosp_min is not None and pd.notna(hosp_min):
                            st.write(f"🏥 **Hospital:** {_commute_descriptor(hosp_min)}")
                        else:
                            st.write("🏥 **Hospital:** —")
                    with amenity_col2:
                        walk_score_value = row.get("official_walk_score") or row.get("walk_score")
                        if walk_score_value is not None and not (isinstance(walk_score_value, float) and pd.isna(walk_score_value)):
                            st.write(f"🚶 **Walk Score:** {int(walk_score_value)}/100")
                        else:
                            st.write("🚶 **Walk Score:** —")
                        # Safety — descriptor only
                        safety_val = row.get("safety_score")
                        if safety_val is not None and not (isinstance(safety_val, float) and pd.isna(safety_val)):
                            st.write(f"🛡️ **Safety:** {_safety_descriptor(safety_val)}")
                        else:
                            st.write("🛡️ **Safety:** —")
                        # Nearby Gyms — only show when data is present and looks valid
                        gyms_val = row.get("nearby_gyms")
                        if gyms_val is not None and not (isinstance(gyms_val, float) and pd.isna(gyms_val)):
                            try:
                                gyms_int = int(gyms_val)
                                if gyms_int >= 0:
                                    st.write(f"💪 **Nearby Gyms:** {gyms_int}")
                            except (TypeError, ValueError):
                                pass  # hide if not a valid number

                with tab3:
                    if tradeoff and rank > 1:
                        st.markdown(tradeoff.generate_tradeoff_explanation(rank - 2, rank - 1))
                    else:
                        st.info("This is your current top recommendation.")

                with tab4:
                    analysis = regret_analyzer.analyze_apartment(rank - 1)
                    if analysis.get("concerns"):
                        st.write(f"**Regret Risk: {analysis['regret_risk']:.0f}/100**")
                        st.write(analysis["recommendation"])
                        for concern in analysis["concerns"]:
                            st.warning(
                                f"{concern['icon']} **{concern['title']}**\n\n{concern['message']}"
                            )
                    else:
                        st.success("✅ No major concerns!")

        # ── Neighborhood Profiles for top units ────────────────────────────
        if st.session_state.enrichment_done:
            st.markdown("#### 🏘 Neighborhood Profiles")
            nb_cols = st.columns(min(len(top3), 3))
            for col_idx, (_, row) in enumerate(top3.iterrows()):
                with nb_cols[col_idx]:
                    unit_label = f"Unit {row.get('unit', 'N/A')}"
                    st.markdown(f"**{unit_label}**")
                    summary = row.get("lifestyle_summary") or generate_lifestyle_summary(row.to_dict())
                    st.write(summary)
                    ws = row.get("official_walk_score") or row.get("walk_score")
                    ts = row.get("transit_score")
                    bs = row.get("bike_score")
                    if ws:
                        st.metric("Walk", f"{int(ws)}/100")
                    if ts:
                        st.metric("Transit", f"{int(ts)}/100")
                    if bs:
                        st.metric("Bike", f"{int(bs)}/100")
                    groceries = row.get("nearby_groceries")
                    restaurants = row.get("restaurants_count")
                    parks = row.get("nearby_parks")
                    gyms = row.get("nearby_gyms")
                    details = []
                    if groceries is not None and not (isinstance(groceries, float) and pd.isna(groceries)):
                        details.append(f"🛒 {int(groceries)} grocery stores")
                    if restaurants is not None and not (isinstance(restaurants, float) and pd.isna(restaurants)):
                        details.append(f"🍽 {int(restaurants)} restaurants")
                    if parks is not None and not (isinstance(parks, float) and pd.isna(parks)):
                        details.append(f"🌳 {int(parks)} parks")
                    # Only show gyms if the count is a valid non-negative integer
                    if gyms is not None and not (isinstance(gyms, float) and pd.isna(gyms)):
                        try:
                            gyms_int = int(gyms)
                            if gyms_int >= 0:
                                details.append(f"💪 {gyms_int} gyms nearby")
                        except (TypeError, ValueError):
                            pass
                    for d in details:
                        st.caption(d)

        # ── Cost of Living breakdowns ──────────────────────────────────────
        extras = st.session_state.cost_extras
        if any(v for v in extras.values() if v):
            st.markdown("#### 💰 Monthly Cost Breakdown (Top Units)")
            cost_cols = st.columns(min(len(top3), 3))
            for col_idx, (_, row) in enumerate(top3.iterrows()):
                with cost_cols[col_idx]:
                    price_num = row.get("price_num")
                    if pd.notna(price_num):
                        breakdown = compute_monthly_total(price_num, extras)
                        st.markdown(f"**Unit {row.get('unit', 'N/A')}**")
                        for label, val in breakdown.items():
                            if label == "Estimated Total":
                                st.markdown(f"**Total: ${int(val):,}/mo**")
                            else:
                                st.write(f"{label}: ${int(val):,}")

        # ── AI Rent Negotiator ─────────────────────────────────────────────
        if has_feature("negotiation") and openai_configured():
            st.markdown("#### 🤝 AI Rent Negotiator")
            st.caption(
                "Generate a personalized negotiation email and talking points for any unit."
            )
            top3_rows_list = list(top3.iterrows())
            neg_cols = st.columns(min(len(top3_rows_list), 3))
            for col_idx, (_, row) in enumerate(top3_rows_list):
                unit_key = f"{row.get('property', '')}_{row.get('unit', '')}"
                with neg_cols[col_idx]:
                    st.markdown(f"**Unit {row.get('unit', 'N/A')}**  \n{row.get('price', '')}")
                    if st.button(
                        "✍️ Generate Script",
                        key=f"neg_{unit_key}",
                        use_container_width=True,
                    ):
                        comparables = [
                            r.to_dict()
                            for _, r in ranked_df.iterrows()
                            if r.get("unit") != row.get("unit")
                        ][:5]
                        with st.spinner("Generating negotiation script…"):
                            try:
                                script = generate_negotiation_script(row.to_dict(), comparables)
                                st.session_state.negotiation_outputs[unit_key] = script
                            except Exception as e:
                                st.session_state.negotiation_outputs[unit_key] = f"⚠️ Error: {e}"

                if unit_key in st.session_state.negotiation_outputs:
                    with st.expander(f"📋 Negotiation Script — Unit {row.get('unit', 'N/A')}", expanded=True):
                        st.markdown(st.session_state.negotiation_outputs[unit_key])
                        st.button(
                            "📋 Copy to clipboard",
                            key=f"copy_{unit_key}",
                            on_click=lambda k=unit_key: st.write(
                                f"<textarea style='opacity:0;position:absolute'>{st.session_state.negotiation_outputs[k]}</textarea>",
                                unsafe_allow_html=True,
                            ),
                        )
        elif openai_configured():
            st.caption("Upgrade to Premium to use the AI Rent Negotiator.")

        # ── Full ranked table ──────────────────────────────────────────────
        st.markdown("### <a id='full-table'>📊 Full Ranking Table</a>", unsafe_allow_html=True)

        display_cols = [
            "property", "floorplan", "unit", "floor",
            "price", "beds", "baths", "sqft",
            "has_den", "availability",
            "nearest_metro", "metro_travel_mode", "metro_min",
            "commute_display",
            "commute_driving_min", "commute_transit_min",
            "nearest_hospital", "hospital_travel_mode", "hospital_min",
            "official_walk_score", "transit_score", "bike_score",
            "walk_score", "safety_score",
            "nearby_groceries", "restaurants_count", "nearby_gyms", "nearby_parks",
            "lifestyle_summary",
            "nestai_score",
            "lifestyle_score",
            "lifestyle_commute_score",
            "lifestyle_safety_score",
            "lifestyle_nightlife_score",
            "lifestyle_budget_score",
            "lifestyle_gym_score",
        ]

        display_cols = [c for c in display_cols if c in ranked_df.columns]
        clean_ranked_df = ranked_df[display_cols].copy()

        for score_col in (
            "nestai_score",
            "lifestyle_score",
            "lifestyle_commute_score",
            "lifestyle_safety_score",
            "lifestyle_nightlife_score",
            "lifestyle_budget_score",
            "lifestyle_gym_score",
        ):
            if score_col in clean_ranked_df.columns:
                clean_ranked_df[score_col] = clean_ranked_df[score_col].round(1)

        st.dataframe(clean_ranked_df, use_container_width=True)

else:
    if auth.is_authenticated():
        st.info("Add units to compare first. Paste a listing above and click **Save Units**.")
    else:
        st.info("Sign in to save units, compare apartments, and unlock personalized rankings.")


# ── Feedback Form ─────────────────────────────────────────────────────────────

if st.session_state.show_feedback_form:
    st.divider()
    st.markdown("## 🐛 Report a Bug or Suggest an Improvement")

    if st.session_state.feedback_submitted_ref:
        st.success(
            f"✅ Thanks! Your feedback was submitted. Reference: **{st.session_state.feedback_submitted_ref}**"
        )
        if st.button("Submit another", key="feedback_another"):
            st.session_state.feedback_submitted_ref = None
            st.rerun()
    else:
        with st.form("feedback_form", clear_on_submit=False):
            category_options = {
                "Bug": "bug",
                "Feature Request": "feature_request",
                "Improvement Suggestion": "improvement",
                "Something Was Confusing": "confusing_experience",
            }
            category_label = st.selectbox(
                "What would you like to report?",
                options=list(category_options.keys()),
            )
            category = category_options[category_label]

            title = st.text_input("Short title *", max_chars=200, placeholder="e.g. Walk Score not loading")
            description = st.text_area("Description", height=120, placeholder="Tell us more…")

            # Category-specific fields
            actual_behavior = expected_behavior = None
            requested_feature = problem_to_solve = value_rating = None
            what_doing = what_unclear = what_expected_next = None

            if category == "bug":
                actual_behavior = st.text_area(
                    "What happened?",
                    height=80,
                    placeholder="Describe what went wrong",
                )
                expected_behavior = st.text_area(
                    "What did you expect to happen?",
                    height=80,
                )

            elif category in ("feature_request", "improvement"):
                requested_feature = st.text_area(
                    "What would you like NestAI to do?",
                    height=80,
                )
                problem_to_solve = st.text_area(
                    "What problem would this solve?",
                    height=80,
                )
                value_options = {
                    "Nice to have": "nice_to_have",
                    "Would use occasionally": "use_occasionally",
                    "Would use during every apartment search": "use_every_search",
                    "I might not use NestAI without it": "might_not_use_without",
                }
                value_label = st.selectbox(
                    "How valuable would this be to you?",
                    options=list(value_options.keys()),
                )
                value_rating = value_options[value_label]

            elif category == "confusing_experience":
                what_doing = st.text_area(
                    "What were you trying to do?",
                    height=80,
                )
                what_unclear = st.text_area(
                    "What part was unclear?",
                    height=80,
                )
                expected_behavior = st.text_area(
                    "What did you expect to happen next?",
                    height=80,
                )

            contact_email = st.text_input(
                "Contact email (optional)",
                placeholder="you@example.com",
            )
            user_contact_allowed = st.checkbox(
                "NestAI may contact me about this report", value=False
            )
            screenshot = st.file_uploader(
                "Attach a screenshot (optional)",
                type=["png", "jpg", "jpeg", "gif", "webp"],
            )

            submitted = st.form_submit_button("Submit Feedback", use_container_width=True)

        if submitted:
            if not title.strip():
                st.error("Please enter a title for your feedback.")
            else:
                # Auto-captured context
                comparison_df_ctx = st.session_state.comparison_df
                unit_count = len(comparison_df_ctx) if not comparison_df_ctx.empty else 0
                building_count = (
                    comparison_df_ctx["property"].nunique()
                    if not comparison_df_ctx.empty and "property" in comparison_df_ctx.columns
                    else 0
                )

                payload = {
                    "category": category,
                    "title": title,
                    "description": description,
                    "actual_behavior": actual_behavior,
                    "expected_behavior": expected_behavior,
                    "requested_feature": requested_feature,
                    "problem_to_solve": problem_to_solve,
                    "value_rating": value_rating,
                    "what_were_you_doing": what_doing,
                    "what_was_unclear": what_unclear,
                    "contact_email": contact_email,
                    "user_contact_allowed": user_contact_allowed,
                    "user_plan": get_tier(),
                    "beta_tester": st.session_state.beta_tester,
                    "platform": "web",
                    "unit_count": unit_count,
                    "building_count": building_count,
                }

                try:
                    ref = submit_feedback(payload)
                    send_feedback_email(payload, ref)
                    st.session_state.feedback_submitted_ref = ref
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save feedback: {exc}")
