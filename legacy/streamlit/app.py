import time as _time
from html import escape as html_escape
from pathlib import Path
from homes_tab import render_homes_tab

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
from availability import availability_label, availability_matches
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
from credits import get_tier, has_feature, can_enrich_building, consume_analysis, analyses_remaining
from cache import get_geocode, _address_key
from feedback import submit_feedback, send_feedback_email
from feature_access import get_effective_plan, get_quota, get_plan
from plan_ui import render_plan_sidebar, render_pricing_cards, render_upgrade_prompt
from ui_state import get_account_type_options, get_navigation_options, plan_display_name
from ui_theme import feature_pill, inject_global_styles, metric_card_html, normalize_plan, render_badge, tier_class
from auth_service import (
    NestAIAPIClient,
    StreamlitAuthManager,
    login_error_message,
    registration_error_message,
    payment_required_message,
    SERVICE_UNAVAILABLE_MESSAGE,
)

st.set_page_config(page_title="NestAI", page_icon="🏠", layout="wide")
inject_global_styles()
st.markdown(
    """
    <div class="nestai-hero">
        <div class="nestai-eyebrow">NestAI</div>
        <h2>Upgrade your apartment search from raw listings to decision intelligence.</h2>
        <p class="nestai-subtle">
            Cleaner comparisons, stronger recommendations, and tier-aware insights that feel
            like a premium SaaS product instead of a default listing tool.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

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


def get_priority_rank(priority_name: str, weights: dict) -> str:
    sorted_priorities = sorted(weights.items(), key=lambda item: item[1], reverse=True)
    position = next(
        (idx for idx, (name, _) in enumerate(sorted_priorities) if name == priority_name),
        None,
    )

    if position is None:
        return "low priority"

    current_weight = weights[priority_name]
    tied = [name for name, weight in weights.items() if weight == current_weight and name != priority_name]
    ordinal = ["1st", "2nd", "3rd", "4th", "5th"]
    rank_str = ordinal[position] if position < len(ordinal) else f"{position + 1}th"
    return f"tied for {rank_str}" if tied else rank_str


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


def current_visual_tier(user: dict | None = None) -> str:
    if user:
        effective_plan = get_effective_plan(
            user.get("active_plan") or user.get("tier"),
            beta_access=bool(user.get("beta_access") and not user.get("active_plan")),
        )
        return normalize_plan(effective_plan)
    if st.session_state.get("beta_tester") and normalize_plan(get_plan()) == "free":
        return "beta"
    return normalize_plan(get_plan() or get_tier())


def current_effective_plan_key(user: dict | None = None) -> str:
    if user:
        return get_effective_plan(
            user.get("active_plan") or user.get("tier"),
            beta_access=bool(user.get("beta_access") and not user.get("active_plan")),
        )
    return get_effective_plan()


def compact_recommendation(row: pd.Series, ranked_df: pd.DataFrame) -> tuple[list[str], str]:
    reasons = explain_match(row, st.session_state.user_profile, compute_match_score(row, st.session_state.user_profile))
    strength_indicators: list[str] = []

    diff, avg = price_position(row, ranked_df)
    if diff is not None:
        strength_indicators.append("Below peer avg" if diff < 0 else "Premium priced")
    walk_score = row.get("official_walk_score") or row.get("walk_score")
    if walk_score and pd.notna(walk_score):
        strength_indicators.append("High walkability" if float(walk_score) >= 70 else "Balanced location")
    commute = row.get("commute_transit_min") or row.get("commute_driving_min") or row.get("metro_min")
    if commute and pd.notna(commute):
        strength_indicators.append("Commute-friendly" if float(commute) <= 30 else "Longer commute")
    sqft_value = row.get("sqft_num")
    if sqft_value and pd.notna(sqft_value) and sqft_value >= ranked_df["sqft_num"].fillna(0).median():
        strength_indicators.append("Above-average space")
    if row.get("has_den"):
        strength_indicators.append("Extra flex space")
    if row.get("has_laundry"):
        strength_indicators.append("In-unit laundry")
    available = availability_label(row.get("available_date") or row.get("availability"))
    if available != "Unknown":
        strength_indicators.append(f"Available {available}")

    strength_indicators = strength_indicators[:4] or ["Balanced overall fit"]
    summary = reasons[0] if reasons else "Strong overall balance across budget, space, and neighborhood fit."
    return strength_indicators, summary


def _apt_pref_score_boost(row: pd.Series, prefs: dict) -> float:
    """Return a ±15 point adjustment to nestai_score based on apartment preference matches."""
    boost = 0.0

    def _match(has_feature: bool, pref: str, weight: float = 4.0) -> float:
        if pref == "Yes":
            return weight if has_feature else -weight
        if pref == "No":
            return weight if not has_feature else -weight
        return 0.0

    boost += _match(bool(row.get("has_laundry")), prefs.get("laundry", "No preference"))
    boost += _match(bool(row.get("has_pool")), prefs.get("pool", "No preference"))
    boost += _match(bool(row.get("has_gym") or row.get("has_fitness")), prefs.get("gym", "No preference"))

    # Pets
    pets_text = str(row.get("pets_policy") or "").lower()
    has_pets = any(k in pets_text for k in ("yes", "allowed", "ok", "welcome", "friendly"))
    boost += _match(has_pets, prefs.get("pets", "No preference"))

    # Short-term: furnished / month-to-month / <12 months
    short_term_pref = prefs.get("short_term", "No preference")
    if short_term_pref != "No preference":
        lease_text = str(row.get("availability") or row.get("lease_terms") or "").lower()
        has_short = (
            "month-to-month" in lease_text
            or "month to month" in lease_text
            or "furnished" in lease_text
            or bool(row.get("has_short_term"))
        )
        boost += _match(has_short, short_term_pref)

    # Parking
    parking_pref = prefs.get("parking", "No preference")
    has_parking = bool(row.get("has_parking"))
    parking_text = str(row.get("parking_fee") or row.get("parking_type") or "").lower()
    free_parking = has_parking and (
        parking_text in ("", "included", "free") or "free" in parking_text
    )
    if parking_pref == "Free required":
        boost += 5.0 if free_parking else -5.0
    elif parking_pref == "Paid or free":
        boost += 3.0 if has_parking else -3.0
    # "No parking needed" → no adjustment

    # Building access
    access_pref = prefs.get("access", "No preference")
    if access_pref == "Doorman/concierge preferred":
        has_doorman = bool(row.get("has_doorman") or row.get("has_concierge"))
        boost += 5.0 if has_doorman else -2.0

    return max(-15.0, min(15.0, boost))


def render_decision_brief(top3: pd.DataFrame, ranked_df: pd.DataFrame, weights: dict, regret_analyzer: RegretAnalyzer, tradeoff: TradeoffAnalyzer | None, tier: str) -> None:
    best = top3.iloc[0]
    alternative = top3.iloc[1] if len(top3) > 1 else None
    best_match = explain_match(best, st.session_state.user_profile, compute_match_score(best, st.session_state.user_profile))
    best_reasons = best_match[:2] or ["Strong overall balance across price, space, commute, and listing details"]
    regret = regret_analyzer.analyze_apartment(0)
    concerns = regret.get("concerns") or []
    concern = concerns[0] if concerns else None

    if alternative is not None and tradeoff:
        # Why the winner beat the runner-up
        why_wins = tradeoff.explain_why_winner()
        why_wins_lines = [l.replace("• ", "").strip() for l in why_wins.split("\n") if l.strip().startswith("•")]
        why_wins_summary = " · ".join(why_wins_lines[:2]) if why_wins_lines else " · ".join(best_reasons)

        # Key compromise: what the winner gives up
        diffs = tradeoff.get_difference_metrics(tradeoff.ranked_df.iloc[0], tradeoff.ranked_df.iloc[1])
        compromise_parts = []
        if diffs["price_diff"] > 0:
            compromise_parts.append(f"${diffs['price_diff']:,.0f}/mo more expensive")
        for item in diffs.get("lost_amenities", [])[:2]:
            compromise_parts.append(f"no {item}")
        main_compromise = "; ".join(compromise_parts) if compromise_parts else "Minor tradeoffs only"

        alternative_label = f"{alternative.get('property', 'Unknown')} · Unit {alternative.get('unit', 'N/A')}"
    elif alternative is not None:
        why_wins_summary = " · ".join(best_reasons)
        main_compromise = "Closest alternative if you want a different balance of price, commute, or space."
        alternative_label = f"{alternative.get('property', 'Unknown')} · Unit {alternative.get('unit', 'N/A')}"
    else:
        why_wins_summary = " · ".join(best_reasons)
        main_compromise = "Add another saved unit to reveal key compromises."
        alternative_label = "No alternative yet"

    cards = [
        ("Best Overall Choice", f"{best.get('property', 'Unknown')} · Unit {best.get('unit', 'N/A')}"),
        ("Why It Wins", why_wins_summary),
        ("Key Compromise", main_compromise),
        ("Potential Regret", concern["title"] if concern else regret.get("recommendation", "No major red flags.")),
        ("Best Alternative", alternative_label),
    ]

    st.markdown("### Executive Decision Brief")
    st.caption("Explains why the top choice won, what it gives up, and what to watch for.")
    cols = st.columns(len(cards))
    for col, (label, value) in zip(cols, cards):
        with col:
            st.markdown(metric_card_html(label, value, tier=tier), unsafe_allow_html=True)

    if tier == "premium_plus":
        st.markdown(
            "<div class='nestai-upgrade-card tier-premium-plus'><div class='nestai-eyebrow'>Premium Plus insight</div><h3>Everything in Premium, plus deeper context</h3><p class='nestai-section-note'>Advanced analytics stay visible here so your highest-limit plan feels clearly more complete.</p></div>",
            unsafe_allow_html=True,
        )


def render_rank_card(rank: int, row: pd.Series, ranked_df: pd.DataFrame, tier: str) -> None:
    strengths, summary = compact_recommendation(row, ranked_df)
    diff, avg = price_position(row, ranked_df)
    if diff is None:
        price_compare = "Peer average unavailable"
    elif diff < 0:
        price_compare = f"${abs(diff):,} below peer average"
    elif diff > 0:
        price_compare = f"${abs(diff):,} above peer average"
    else:
        price_compare = "At peer average"

    pills = []
    for item in strengths:
        tone = "premium" if tier in {"premium", "premium_plus"} else "default"
        if "longer" in item.lower() or "premium priced" in item.lower():
            tone = "warning"
        elif "below" in item.lower() or "high" in item.lower() or "friendly" in item.lower():
            tone = "positive"
        pills.append(feature_pill(item, tone))

    price_num = row.get("price_num")
    sqft_num = row.get("sqft_num")
    beds = row.get("beds") or row.get("beds_num") or "—"
    baths = row.get("baths") or "—"
    class_names = f"nestai-ranking-card {tier_class(tier)} {'top-ranked' if rank == 1 else ''}"

    st.markdown(
        (
            f"<div class='{class_names}'>"
            "<div class='nestai-ranking-header'>"
            f"<div><div class='nestai-rank-number'>Rank #{rank}</div>"
            f"<h3>{html_escape(str(row.get('property', 'Unknown')))}</h3>"
            f"<div class='nestai-ranking-subtitle'>Unit {html_escape(str(row.get('unit', 'N/A')))}</div></div>"
            "</div>"
            f"<p class='nestai-ranking-meta'>${int(price_num) if pd.notna(price_num) else 0:,}/mo · {price_compare}"
            f" · {int(sqft_num) if pd.notna(sqft_num) else 0} sqft · {html_escape(str(beds))} bed · {html_escape(str(baths))} bath</p>"
            f"<div>{''.join(pills)}</div>"
            f"<p class='nestai-section-note'>{html_escape(summary)}</p>"
            f"<p class='nestai-section-note'>{html_escape(f'{compute_match_score(row, st.session_state.user_profile):.0f}% match based on your profile' if any(st.session_state.user_profile.values()) else 'Set up your profile for a personalized match percentage.')}</p>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


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
    "main_nav": "Home",
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

try:
    _query_screen = st.query_params.get("screen")
    _reset_token = st.query_params.get("reset_token")
except Exception:
    _query_screen = None
    _reset_token = None
if _reset_token:
    st.session_state["reset_password_token"] = _reset_token
    st.session_state.main_nav = "Reset Password"
elif _query_screen in {"Forgot Password", "Reset Password"}:
    st.session_state.main_nav = _query_screen

_current_user = auth.user() or {}
_is_admin = bool(_current_user.get("is_admin"))
nav_options = get_navigation_options(auth.is_authenticated(), is_admin=_is_admin)
hidden_screens = {"Login", "Create Account", "Pricing", "Forgot Password", "Reset Password"}
if st.session_state.main_nav not in {*nav_options, *hidden_screens}:
    st.session_state.main_nav = "Apartment Search" if auth.is_authenticated() else "Home"
active_screen = st.session_state.main_nav

if auth.is_authenticated():
    top_cols = st.columns([6, 1.2, 1.5, 1.0])
    with top_cols[1]:
        if st.button("Report a bug", use_container_width=True):
            st.session_state.show_feedback_form = True
            st.session_state.feedback_submitted_ref = None
            st.rerun()
    with top_cols[2]:
        if st.button("Make a suggestion", use_container_width=True):
            st.session_state.show_feedback_form = True
            st.session_state.feedback_submitted_ref = None
            st.rerun()
    with top_cols[3]:
        if st.button("Log out", use_container_width=True):
            auth.logout()
            st.session_state.auth_notice = "Signed out successfully."
            st.session_state.main_nav = "Home"
            st.rerun()


# ── Sidebar — AI Apartment Advisor ────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🧭 Navigation")
    nav_choice = st.radio(
        "Go to",
        options=nav_options,
        index=nav_options.index(active_screen) if active_screen in nav_options else 0,
        label_visibility="collapsed",
    )
    if active_screen in nav_options and nav_choice != active_screen:
        st.session_state.main_nav = nav_choice
        st.rerun()

    st.divider()
    st.markdown("## 👤 Account")
    if auth.is_authenticated():
        user_preview = _current_user
        effective_plan = current_effective_plan_key(user_preview)
        plan_slug = normalize_plan(effective_plan)
        st.caption(user_preview.get("display_name") or user_preview.get("email"))
        st.caption(f"Tier: {plan_display_name(plan_slug)}")
        st.caption(f"Saved units: {len(st.session_state.comparison_df)}")
        if plan_slug == "free":
            st.info("Want AI to make your search even easier? Upgrade to Premium.")
        if user_preview.get("subscription_status") == "pending_payment":
            st.warning(payment_required_message(user_preview.get("requested_plan") or user_preview.get("active_plan", "premium")))
    else:
        st.caption("You are signed out.")
    render_plan_sidebar()

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
        render_upgrade_prompt("can_use_ai_chat", "AI Apartment Advisor")
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

    if active_screen == "Apartment Search":
        st.divider()
        st.markdown("## 📑 Navigation")
        if not st.session_state.comparison_df.empty:
            st.markdown(
                """
- [Lifestyle Priorities](#lifestyle-priorities)
- [Filter Apartments](#filter-apartments)
- [Ranked Shortlist and Breakdown](#rankings)
- [Executive Decision Brief](#executive-decision-brief)
- [Neighborhood Enrichment](#neighborhood-enrichment)
- [Full Ranking Table](#full-table)
                """
            )
            stat_col1, stat_col2 = st.columns(2)
            with stat_col1:
                st.metric("Total Units", len(st.session_state.comparison_df))
            with stat_col2:
                st.metric("Buildings", st.session_state.comparison_df["property"].nunique())
        else:
            st.caption("Paste an apartment listing to get started.")


if active_screen == "Profile":
    if auth.is_authenticated():
        user = auth.user() or {}
        effective_plan = current_effective_plan_key(user)
        effective_plan_slug = normalize_plan(effective_plan)
        visual_tier = current_visual_tier(user)
        st.markdown("### Account Dashboard")
        render_badge(visual_tier, icon="✦")
        account_tab, subscription_tab, referrals_tab, preferences_tab = st.tabs(
            ["Account", "Subscription & Pricing", "Referrals", "Preferences"]
        )

        with account_tab:
            st.markdown(
                (
                    f"<div class='nestai-profile-card {tier_class(visual_tier)}'>"
                    "<div class='nestai-eyebrow'>Profile</div>"
                    f"<h3>{html_escape(user.get('display_name') or 'NestAI Member')}</h3>"
                    f"<p class='nestai-section-note'>{html_escape(user.get('email') or '—')}</p>"
                    f"<p class='nestai-subtle'>Your active tier is <strong>{html_escape(plan_display_name(effective_plan_slug))}</strong>.</p>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

            quota = get_quota("monthly_analyses_limit")
            saved_limit = get_quota("saved_property_limit")
            payment_status = "Pending" if user.get("subscription_status") == "pending_payment" else ("Paid" if effective_plan_slug in {"premium", "premium_plus"} else "Not required")
            saved_buildings = st.session_state.comparison_df["property"].nunique() if not st.session_state.comparison_df.empty and "property" in st.session_state.comparison_df.columns else 0
            usage_cards = [
                ("Active Tier", plan_display_name(effective_plan_slug), user.get("subscription_status") or "active"),
                ("Usage Summary", f"{analyses_remaining() if analyses_remaining() is not None else 'Unlimited'} analyses left", f"Limit: {quota if quota is not None else 'Unlimited'}"),
                ("Saved Properties", str(len(st.session_state.comparison_df)), f"Buildings tracked: {saved_buildings}"),
                ("Current Limits", f"{saved_limit if saved_limit is not None else 'Unlimited'} saved", "Tier-aware limits and insights"),
            ]
            usage_cols = st.columns(4)
            for col, (label, value, helper) in zip(usage_cols, usage_cards):
                with col:
                    st.markdown(metric_card_html(label, value, helper, tier=visual_tier), unsafe_allow_html=True)

            status_cols = st.columns(3)
            with status_cols[0]:
                st.markdown(metric_card_html("Subscription Status", user.get("subscription_status") or "active", "Billing state", tier=visual_tier), unsafe_allow_html=True)
            with status_cols[1]:
                st.markdown(metric_card_html("Payment Status", payment_status, "Commercial plan readiness", tier=visual_tier), unsafe_allow_html=True)
            with status_cols[2]:
                st.markdown(metric_card_html("Beta Status", "Enabled" if user.get("beta_access") else "Standard", "Early-access visibility", tier=visual_tier), unsafe_allow_html=True)

            unlocked = []
            if has_feature("walk_score"):
                unlocked.append("Neighborhood intelligence")
            if has_feature("ai_chat"):
                unlocked.append("AI advisor")
            if has_feature("decision_reports"):
                unlocked.append("Decision reports")
            if has_feature("exports"):
                unlocked.append("Exports")
            if has_feature("negotiation"):
                unlocked.append("Negotiation help")
            unlocked = unlocked or ["Core parsing and ranking"]
            st.markdown(
                (
                    f"<div class='nestai-profile-card {tier_class(visual_tier)}'>"
                    "<div class='nestai-eyebrow'>Unlocked features</div>"
                    f"<h3>{html_escape(plan_display_name(effective_plan_slug))}</h3>"
                    f"<p class='nestai-section-note'>{' '.join(feature_pill(item, 'premium' if visual_tier in {'premium', 'premium_plus'} else 'default') for item in unlocked)}</p>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            if user.get("beta_approved_at"):
                st.caption(f"Beta approved at {user.get('beta_approved_at')}")
            if user.get("is_admin"):
                st.info("Admin account")

        with subscription_tab:
            if user.get("subscription_status") == "pending_payment":
                requested_plan = user.get("requested_plan") or st.session_state.get("signup_account_type", "premium")
                st.warning(payment_required_message(requested_plan))
                billing_status_payload = auth.refresh_billing_status() or {}
                if billing_status_payload.get("trial_days"):
                    st.caption(f"Free trial: {billing_status_payload.get('trial_days')} days")
                if billing_status_payload.get("future_monthly_price"):
                    st.caption(f"Future price after trial: {billing_status_payload.get('future_monthly_price')}")
                if billing_status_payload.get("cancellation_terms"):
                    st.caption(billing_status_payload.get("cancellation_terms"))
                if billing_status_payload.get("billing_reminder"):
                    st.caption(billing_status_payload.get("billing_reminder"))
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
            render_pricing_cards()

        with referrals_tab:
            summary_response = auth.api_client.request("GET", "/auth/referrals/summary")
            if summary_response.status_code == 200:
                summary_payload = summary_response.json()
                st.text_input("Your referral code", value=summary_payload.get("referral_code") or "", disabled=True)
                st.text_input("Your referral link", value=summary_payload.get("referral_link") or "", disabled=True)
                credits_dollars = (summary_payload.get("earned_credit_cents") or 0) / 100
                st.metric("Earned referral credits", f"${credits_dollars:,.2f}")
                invitations = summary_payload.get("referrals") or []
                if invitations:
                    st.dataframe(pd.DataFrame(invitations), use_container_width=True)
            else:
                st.info("Referral details are unavailable right now.")

            with st.form("referral_invite_form"):
                invite_email = st.text_input("Invite by email")
                invite_submit = st.form_submit_button("Send referral invite", use_container_width=True, disabled=not api_available)
            if invite_submit and invite_email.strip():
                invite_response = auth.api_client.request("POST", "/auth/referrals/invite", json={"email": invite_email.strip()})
                if invite_response.status_code in {200, 201}:
                    st.success("Referral invitation saved.")
                    st.rerun()
                else:
                    st.error("Could not send referral invitation.")

        with preferences_tab:
            render_lifestyle_profile_controls()
    else:
        st.info("You must be signed in to view Profile.")
        if st.button("Go to Sign in", use_container_width=True):
            st.session_state.main_nav = "Login"
            st.rerun()
        if st.button("Go to Sign up", use_container_width=True):
            st.session_state.main_nav = "Create Account"
            st.rerun()
    st.stop()

if active_screen == "Login":
    st.markdown("### 🔐 Sign In")
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
                    st.session_state.main_nav = "Apartment Search"
                    st.rerun()
                else:
                    st.session_state.auth_error = "Could not load your profile after signing in."
            else:
                st.session_state.auth_error = login_error_message(response.status_code)
            st.rerun()
    nav_col1, nav_col2 = st.columns(2)
    with nav_col1:
        if st.button("Create an account", use_container_width=True):
            st.session_state.main_nav = "Create Account"
            st.rerun()
    with nav_col2:
        if st.button("Forgot password?", use_container_width=True):
            st.session_state.main_nav = "Forgot Password"
            st.rerun()
    st.stop()

if active_screen == "Create Account":
    st.markdown("### ✨ Sign Up")
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
        st.info("Premium starts with a free trial and requires explicit checkout consent.")
    elif selected_account_type == "premium_plus":
        st.info("Premium Plus starts with a free trial and requires explicit checkout consent.")

    with st.form("register_form"):
        register_name = st.text_input("Display name", key="register_name")
        register_email = st.text_input("Email", key="register_email")
        register_password = st.text_input("Password", type="password", key="register_password")
        referral_code = st.text_input("Referral code (optional)", key="register_referral_code")
        beta_invite_code = None
        trial_consent = False
        payment_method_confirmed = False
        if selected_account_type == "beta":
            beta_invite_code = st.text_input("Beta invite code", type="password", key="beta_invite_code")
        if selected_account_type in {"premium", "premium_plus"}:
            st.caption("Free trial ends in 7 days. Then monthly billing starts unless you cancel before the end date.")
            st.caption("You will receive a reminder before billing.")
            trial_consent = st.checkbox(
                "I explicitly agree to automatic conversion after trial ends using my payment method on file.",
                key="trial_consent_checkbox",
            )
            payment_method_confirmed = st.checkbox(
                "I have provided and confirmed a payment method.",
                key="payment_method_confirmed_checkbox",
            )
        register_submit = st.form_submit_button("Create Account", use_container_width=True, disabled=not api_available)

    if register_submit:
        with st.spinner("Creating your account..."):
            response = auth.register(
                register_email,
                register_password,
                register_name,
                account_type=selected_account_type,
                beta_invite_code=beta_invite_code,
                referral_code=referral_code.strip() or None,
                trial_consent=trial_consent,
                payment_method_confirmed=payment_method_confirmed,
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
                    st.session_state.main_nav = "Apartment Search"
                else:
                    st.session_state.auth_notice = "Account created and signed in."
                    st.session_state.main_nav = "Apartment Search"
                st.rerun()
            else:
                if selected_account_type == "beta" and response.status_code == 401:
                    st.session_state.auth_error = "Invalid beta invite code."
                else:
                    st.session_state.auth_error = registration_error_message(response.status_code)
                st.rerun()
    if st.button("Already have an account? Sign in", use_container_width=True):
        st.session_state.main_nav = "Login"
        st.rerun()
    st.stop()

if active_screen == "Forgot Password":
    st.markdown("### 🔑 Forgot Password")
    if not api_available:
        st.info(SERVICE_UNAVAILABLE_MESSAGE)
    with st.form("forgot_password_form"):
        forgot_email = st.text_input("Email", key="forgot_email")
        forgot_submit = st.form_submit_button("Send reset instructions", use_container_width=True, disabled=not api_available)
    if forgot_submit:
        response = auth.forgot_password(forgot_email)
        payload = response.json()
        st.session_state.auth_notice = payload.get("message") or "If an account exists for that email, a password reset link has been sent."
        reset_link = payload.get("reset_link")
        if reset_link:
            st.session_state.auth_notice = f"{st.session_state.auth_notice} Development reset link generated below."
            st.session_state["dev_reset_link"] = reset_link
        st.rerun()
    if st.session_state.get("dev_reset_link"):
        st.code(st.session_state["dev_reset_link"])
    if st.button("Back to Sign In", use_container_width=True):
        st.session_state.main_nav = "Login"
        st.rerun()
    st.stop()

if active_screen == "Reset Password":
    st.markdown("### 🔒 Reset Password")
    if not api_available:
        st.info(SERVICE_UNAVAILABLE_MESSAGE)
    with st.form("reset_password_form"):
        reset_token = st.text_input("Reset token", key="reset_password_token")
        new_password = st.text_input("New password", type="password", key="reset_password_new")
        reset_submit = st.form_submit_button("Reset password", use_container_width=True, disabled=not api_available)
    if reset_submit:
        response = auth.reset_password(reset_token, new_password)
        if response.status_code == 200:
            st.session_state.auth_notice = "Password reset successfully. Please sign in."
            st.session_state["dev_reset_link"] = None
            st.session_state.main_nav = "Login"
        else:
            st.session_state.auth_error = response.json().get("detail", "Could not reset password.")
        st.rerun()
    if st.button("Back to Sign In", key="reset_back_to_sign_in", use_container_width=True):
        st.session_state.main_nav = "Login"
        st.rerun()
    st.stop()

if active_screen == "Pricing":
    render_pricing_cards()
    st.caption("Premium and Premium Plus require payment setup before activation. Accounts are created as Free with your selected plan recorded.")
    st.stop()

if active_screen == "Home":
    if auth.is_authenticated():
        st.session_state.main_nav = "Apartment Search"
        st.rerun()
    st.markdown("### Welcome to NestAI")
    st.write(
        "NestAI helps you compare real monthly costs, floor plans, hidden fees, concessions, "
        "reviews, tour notes, and decision risk so you can choose with confidence."
    )
    home_actions = st.columns(2)
    with home_actions[0]:
        if st.button("Sign in", use_container_width=True):
            st.session_state.main_nav = "Login"
            st.rerun()
    with home_actions[1]:
        if st.button("Sign up", use_container_width=True, type="primary"):
            st.session_state.main_nav = "Create Account"
            st.rerun()
    st.stop()

if active_screen == "Why NestAI":
    st.markdown("### Why NestAI")
    st.write(
        "NestAI helps anyone compare apartments and homes for short- or long-term living by turning "
        "listing details, costs, priorities, and tradeoffs into a personalized ranking and decision brief."
    )
    st.stop()

if active_screen == "How to Use NestAI":
    st.markdown("### How to Use NestAI")
    st.write(
        "Paste listing text, parse units, save the best options, apply your filters and priorities, "
        "then review the ranked shortlist, decision brief, enrichment context, and full ranking table."
    )
    st.stop()

if active_screen == "Admin":
    if not auth.is_authenticated() or not _is_admin:
        st.error("Admin access required.")
        st.stop()

    st.markdown("### 🛡 Admin Panel")
    (
        admin_overview_tab,
        admin_users_tab,
        admin_beta_tab,
        admin_codes_tab,
        admin_feedback_tab,
    ) = st.tabs(["Analytics", "User Management", "Beta Users", "Invite Codes", "Feedback & Bug Reports"])

    with admin_overview_tab:
        ov = auth.api_client.request("GET", "/admin/")
        if ov.status_code == 200:
            data = ov.json()
            users_data = data.get("users", {})
            cols = st.columns(4)
            cols[0].metric("Total Users", users_data.get("total", 0))
            cols[1].metric("Beta Testers", users_data.get("beta_testers", 0))
            cols[2].metric("Premium Users", users_data.get("premium", 0))
            cols[3].metric("Open Feedback", data.get("feedback", {}).get("open", 0))
            cost_data = auth.api_client.request("GET", "/admin/ai-costs")
            if cost_data.status_code == 200:
                cd = cost_data.json()
                cost_cols = st.columns(4)
                cost_cols[0].metric("AI Calls (30d)", cd.get("total_calls", 0))
                cost_cols[1].metric("Cache Hits", cd.get("cache_hits", 0))
                cost_cols[2].metric("Est. Cost (USD)", f"${cd.get('estimated_cost_usd', 0):.4f}")
                cost_cols[3].metric("Total Tokens", cd.get("total_tokens", 0))
        else:
            st.error("Could not load overview.")

    with admin_users_tab:
        users_resp = auth.api_client.request("GET", "/admin/users")
        if users_resp.status_code == 200:
            users_list = users_resp.json()
            if users_list:
                df_users = pd.DataFrame(users_list)
                st.dataframe(df_users, use_container_width=True)
            else:
                st.info("No users found.")
        else:
            st.error("Could not load users.")

    with admin_beta_tab:
        beta_users_resp = auth.api_client.request("GET", "/admin/users")
        if beta_users_resp.status_code == 200:
            all_users = beta_users_resp.json()
            beta_users = [u for u in all_users if u.get("beta_tester")]
            st.markdown(f"**{len(beta_users)} beta testers**")
            if beta_users:
                st.dataframe(pd.DataFrame(beta_users), use_container_width=True)
            st.markdown("#### Promote a user to beta")
            user_id_input = st.number_input("User ID to promote", min_value=1, step=1, key="promote_beta_id")
            if st.button("Promote to Beta", use_container_width=True):
                promo_resp = auth.api_client.request("POST", f"/admin/users/{int(user_id_input)}/promote-beta")
                if promo_resp.status_code == 200:
                    st.success(promo_resp.json().get("message", "Done."))
                    st.rerun()
                else:
                    st.error("Could not promote user.")
        else:
            st.error("Could not load users.")

    with admin_codes_tab:
        codes_resp = auth.api_client.request("GET", "/admin/beta-codes")
        if codes_resp.status_code == 200:
            codes_list = codes_resp.json()
            if codes_list:
                st.dataframe(pd.DataFrame(codes_list), use_container_width=True)
            else:
                st.info("No invite codes yet.")
        else:
            st.error("Could not load invite codes.")

        st.markdown("#### Generate new invite code")
        with st.form("generate_code_form"):
            code_email = st.text_input("Restrict to email (optional)")
            code_max_uses = st.number_input("Max uses", min_value=1, max_value=1000, value=1)
            code_expires = st.date_input("Expires at (optional)", value=None)
            gen_submit = st.form_submit_button("Generate Code", use_container_width=True)
        if gen_submit:
            expires_payload = code_expires.isoformat() if code_expires else None
            gen_resp = auth.api_client.request(
                "POST",
                "/admin/beta-codes",
                json={
                    "email_restriction": code_email.strip() or None,
                    "max_uses": int(code_max_uses),
                    "expires_at": expires_payload,
                },
            )
            if gen_resp.status_code == 200:
                result = gen_resp.json()
                invite_code = result.get("invite_code", "")
                st.success(f"Code generated: `{invite_code}`")
                st.code(invite_code)
                st.text_input("Invite link", value=f"/signup?invite={invite_code}", disabled=True)
                st.rerun()
            else:
                st.error("Could not generate invite code.")

        st.markdown("#### Deactivate a code")
        deact_id = st.number_input("Code ID to deactivate", min_value=1, step=1, key="deact_code_id")
        if st.button("Deactivate", use_container_width=True, type="secondary"):
            deact_resp = auth.api_client.request("POST", f"/admin/beta-codes/{int(deact_id)}/deactivate")
            if deact_resp.status_code == 200:
                st.success("Code deactivated.")
                st.rerun()
            else:
                st.error("Could not deactivate code.")

    with admin_feedback_tab:
        fb_status_filter = st.selectbox("Filter by status", ["all", "new", "triaged", "in_progress", "resolved"], key="fb_status")
        fb_params = f"?status={fb_status_filter}" if fb_status_filter != "all" else ""
        fb_resp = auth.api_client.request("GET", f"/admin/feedback{fb_params}")
        if fb_resp.status_code == 200:
            fb_list = fb_resp.json()
            if fb_list:
                st.dataframe(pd.DataFrame(fb_list), use_container_width=True)
            else:
                st.info("No feedback reports found.")
        else:
            st.error("Could not load feedback reports.")
    st.stop()

if active_screen == "Houses":
    render_homes_tab()
    st.stop()

if active_screen == "Apartment Search":
    pass

if active_screen not in {"Apartment Search", "Houses", "Pricing", "Profile", "Login", "Create Account", "Forgot Password", "Reset Password"}:
    st.stop()


# ── Hero / Intro ──────────────────────────────────────────────────────────────

landing_tier = current_visual_tier(auth.user() if auth.is_authenticated() else None)
st.markdown(
    (
        f"<div class='nestai-surface {tier_class(landing_tier)}' style='padding:1.25rem 1.35rem; margin-bottom:1rem;'>"
        "<div class='nestai-eyebrow'>Apartment workflow</div>"
        "<h3>Rank homes with more clarity and less spreadsheet work.</h3>"
        "<p class='nestai-subtle'>Compare floor plans, pricing, lifestyle fit, and neighborhood quality in one professional decision workspace.</p>"
        "</div>"
    ),
    unsafe_allow_html=True,
)

# ── Paste & Analyze ───────────────────────────────────────────────────────────

st.markdown(
    "🏠 Source: <a href='https://www.apartments.com' target='_blank'>Apartments.com</a>",
    unsafe_allow_html=True,
)
st.info(
    "Expand all units before pressing Ctrl+A. "
    "Listings are not synced, so refresh the source page and paste again to update results."
)

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
        "Subway / Transportation",
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
                st.session_state.parsed_df = pd.DataFrame()
                st.success("Units added!")
                st.rerun()
        else:
            st.info("You must be signed in to save units.")
            if st.button("Go to Sign in", key="goto_signin_save_units"):
                st.session_state.main_nav = "Login"
                st.rerun()
    else:
        st.warning("No unit rows were parsed from this listing.")

# ── Filter & Rank ─────────────────────────────────────────────────────────────

st.markdown("### <a id='lifestyle-priorities'>🎯 Apartment Priorities</a>", unsafe_allow_html=True)

if auth.is_authenticated() and not st.session_state.comparison_df.empty:
    comp_df = st.session_state.comparison_df.copy()

    st.info("Set your preferences to personalize the ranking. Yes/No filters affect the score; No preference is neutral.")
    pref_col1, pref_col2, pref_col3 = st.columns(3)
    with pref_col1:
        apt_pref_pets = st.selectbox("🐾 Pets", ["Yes", "No", "No preference"], key="apt_pref_pets", index=2)
        apt_pref_laundry = st.selectbox("🧺 In-unit laundry", ["Yes", "No", "No preference"], key="apt_pref_laundry", index=0)
        apt_pref_pool = st.selectbox("🏊 Pool", ["Yes", "No", "No preference"], key="apt_pref_pool", index=2)
    with pref_col2:
        apt_pref_gym = st.selectbox("💪 Gym", ["Yes", "No", "No preference"], key="apt_pref_gym", index=2)
        apt_pref_short_term = st.selectbox("📅 Short-term lease", ["Yes", "No", "No preference"], key="apt_pref_short_term", index=2)
        apt_pref_parking = st.selectbox(
            "🚗 Parking",
            ["Free required", "Paid or free", "No parking needed", "No preference"],
            key="apt_pref_parking",
            index=3,
        )
    with pref_col3:
        apt_pref_access = st.selectbox(
            "🏢 Building access",
            ["Doorman/concierge preferred", "Walk-up acceptable", "No preference"],
            key="apt_pref_access",
            index=2,
        )
        apt_pref_min_beds = st.selectbox(
            "🛏 Min bedrooms",
            ["Any", "Studio", "1", "2", "3", "4+"],
            key="apt_pref_min_beds",
            index=0,
        )
        apt_pref_min_baths = st.selectbox(
            "🛁 Min bathrooms",
            ["Any", "1", "1.5", "2", "2.5", "3+"],
            key="apt_pref_min_baths",
            index=0,
        )

    # Keep fixed internal weights for LifestyleScorer (sliders replaced by dropdowns)
    commute_priority = 3
    safety_priority = 3
    nightlife_priority = 2
    budget_priority = 4
    gym_priority = 2

    st.markdown("### <a id='filter-apartments'>🔎 Filter Apartments</a>", unsafe_allow_html=True)

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

    availability_mode = st.selectbox(
        "Availability Date",
        ["Flexible / no preference", "Available now", "Available by selected date"],
        key="apt_availability_mode",
    )
    availability_selected_date = None
    if availability_mode == "Available by selected date":
        availability_selected_date = st.date_input(
            "Available by",
            key="apt_availability_date",
        )

    llm_request = st.text_input(
        "Ask Nest AI to filter your saved units",
        value="1 bed not on the first floor within 10 min walk of subway/public transit",
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
        st.markdown("<a id='neighborhood-enrichment'></a>", unsafe_allow_html=True)
        if not has_feature("walk_score"):
            st.markdown(
                "<div class='nestai-locked-card'><div class='nestai-eyebrow'>Locked intelligence</div><h3>Neighborhood enrichment</h3><p class='nestai-section-note'>Unlock Walk Score, commute context, and nearby essentials to make ranking more trustworthy.</p></div>",
                unsafe_allow_html=True,
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

    if not has_feature("walk_score"):
        render_upgrade_prompt("can_use_walk_score_api", "Neighborhood Enrichment")

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
    if "available_date" not in filtered_comp_df.columns and "availability" in filtered_comp_df.columns:
        filtered_comp_df["available_date"] = filtered_comp_df["availability"]
    filtered_comp_df = filtered_comp_df[
        filtered_comp_df.apply(
            lambda row: availability_matches(
                row.get("available_date") or row.get("availability"),
                availability_mode,
                availability_selected_date,
            ),
            axis=1,
        )
    ]

    filtered_comp_df = filter_units_by_request(filtered_comp_df, llm_request)

    # ── Apply min beds / min baths filters from preferences ───────────────
    _min_beds_map = {"Studio": 0, "1": 1, "2": 2, "3": 3, "4+": 4}
    if apt_pref_min_beds != "Any" and apt_pref_min_beds in _min_beds_map:
        _mb = _min_beds_map[apt_pref_min_beds]
        filtered_comp_df = filtered_comp_df[
            filtered_comp_df["beds_num"].isna() | (filtered_comp_df["beds_num"] >= _mb)
        ]

    _min_baths_map = {"1": 1.0, "1.5": 1.5, "2": 2.0, "2.5": 2.5, "3+": 3.0}
    if apt_pref_min_baths != "Any" and apt_pref_min_baths in _min_baths_map:
        _mbath = _min_baths_map[apt_pref_min_baths]
        filtered_comp_df = filtered_comp_df[
            filtered_comp_df["baths_num"].isna() | (filtered_comp_df["baths_num"] >= _mbath)
        ]

    weights = get_priority_weights_from_sliders(
        commute_priority,
        safety_priority,
        nightlife_priority,
        budget_priority,
        gym_priority,
    )

    # ── Rankings ───────────────────────────────────────────────────────────
    st.markdown("### <a id='rankings'>🏆 Ranked Shortlist and Breakdown</a>", unsafe_allow_html=True)
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

        # ── Apply apartment preference score adjustments ────────────────────
        _apt_prefs = {
            "pets": apt_pref_pets,
            "laundry": apt_pref_laundry,
            "pool": apt_pref_pool,
            "gym": apt_pref_gym,
            "short_term": apt_pref_short_term,
            "parking": apt_pref_parking,
            "access": apt_pref_access,
        }
        ranked_df["nestai_score"] = ranked_df.apply(
            lambda r: float(
                max(0.0, min(100.0, r["nestai_score"] + _apt_pref_score_boost(r, _apt_prefs)))
            ),
            axis=1,
        )

        ranked_df = ranked_df.sort_values(
            ["nestai_score", "lifestyle_score"],
            ascending=[False, False],
        )
        top3 = ranked_df.head(3)
        visual_tier = current_visual_tier(auth.user() if auth.is_authenticated() else None)

        regret_analyzer = RegretAnalyzer(ranked_df, weights)
        tradeoff = TradeoffAnalyzer(ranked_df) if len(ranked_df) > 1 else None

        # ── Top-ranked cards ───────────────────────────────────────────────
        st.markdown("#### Ranked shortlist")
        st.caption("The best option gets a subtle emphasis, while paid tiers surface richer context and clearer tradeoffs.")
        for i, (_, row) in enumerate(top3.iterrows(), start=1):
            render_rank_card(i, row, ranked_df, visual_tier)

        st.markdown("#### 🎯 Breakdown")
        st.caption(
            "Ranked using your saved listing data, profile, and preferences. Tradeoffs explain why each option beat the next."
        )
        for rank, (_, row) in enumerate(top3.iterrows(), start=1):
            unit_id = row.get("unit", f"Unit {rank}")
            with st.expander(
                f"Why this ranks here · #{rank} · {row.get('property', 'Unknown')} · Unit {unit_id}",
                expanded=(rank == 1),
            ):
                tab_amenities, tab_tradeoffs, tab_concerns = st.tabs(
                    ["🏠 Amenities", "💡 Tradeoffs", "⚠️ Concerns"]
                )
                component_scores = {
                    "commute": row.get("lifestyle_commute_score", 0),
                    "safety": row.get("lifestyle_safety_score", 0),
                    "nightlife": row.get("lifestyle_nightlife_score", 0),
                    "budget": row.get("lifestyle_budget_score", 0),
                    "gym": row.get("lifestyle_gym_score", 0),
                }

                with tab_amenities:
                    st.markdown("**Building Amenities**")
                    st.markdown(generate_amenities_list(row))
                    amenity_col1, amenity_col2 = st.columns(2)
                    with amenity_col1:
                        metro_min_val = row.get("metro_min")
                        if metro_min_val is not None and pd.notna(metro_min_val):
                            st.write(f"🚇 **Subway / Transportation:** {metro_min_val} min")
                        else:
                            st.write("🚇 **Subway / Transportation:** Not found")
                            st.caption("No transit stop found within ~30 min or transit data unavailable.")
                        st.write(f"🏥 **Hospital:** {row.get('hospital_min', '—')} min")
                    with amenity_col2:
                        walk_score_value = row.get("official_walk_score") or row.get("walk_score") or "—"
                        st.write(f"🚶 **Walk Score:** {walk_score_value}")
                        st.write(f"💪 **Nearby Gyms:** {row.get('nearby_gyms', '—')}")

                with tab_tradeoffs:
                    if tradeoff:
                        if rank == 1:
                            st.markdown(tradeoff.explain_why_winner())
                        else:
                            st.markdown(tradeoff.generate_tradeoff_explanation(rank - 2, rank - 1))
                    else:
                        st.info("Add another saved unit to see tradeoff analysis.")

                with tab_concerns:
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

        st.markdown("### <a id='executive-decision-brief'>Executive Decision Brief</a>", unsafe_allow_html=True)
        render_decision_brief(top3, ranked_df, weights, regret_analyzer, tradeoff, visual_tier)

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
                    if groceries is not None:
                        details.append(f"🛒 {groceries} grocery stores")
                    if restaurants is not None:
                        details.append(f"🍽 {restaurants} restaurants")
                    if parks is not None:
                        details.append(f"🌳 {parks} parks")
                    if gyms is not None:
                        details.append(f"💪 {gyms} gyms")
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
            render_upgrade_prompt("can_use_ai_negotiation", "AI Rent Negotiator")

        # ── Full ranked table ──────────────────────────────────────────────
        st.markdown("### <a id='full-table'>📊 Full Ranking Table</a>", unsafe_allow_html=True)

        display_cols = [
            "property", "floorplan", "unit", "floor",
            "price", "beds", "baths", "sqft",
            "has_den", "availability", "available_date",
            "nearest_metro", "metro_travel_mode", "metro_min",
            "commute_display",
            "commute_driving_min", "commute_transit_min",
            "nearest_hospital", "hospital_travel_mode", "hospital_min",
            "official_walk_score", "transit_score", "bike_score",
            "walk_score", "safety_score",
            "nearby_groceries", "restaurants_count", "nearby_gyms", "nearby_parks",
            "lifestyle_summary",
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
        st.info("You must be signed in to save units, compare apartments, and unlock personalized rankings.")
        if st.button("Go to Sign in", key="goto_signin_rankings"):
            st.session_state.main_nav = "Login"
            st.rerun()


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
