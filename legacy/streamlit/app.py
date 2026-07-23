import time as _time
from pathlib import Path

import streamlit as st
import pandas as pd

_DATA_DIR = Path(__file__).parent / "data"
_EXAMPLE_LISTINGS = [
    (_DATA_DIR / "app_listing_1.txt", "Avalon Courthouse Place"),
    (_DATA_DIR / "app_listing_2.txt", "Cortland Bennett Park"),
]
from text_parser import parse_apartment_text, filter_units_by_request
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
from regret_analyzer import RegretAnalyzer
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

st.set_page_config(page_title="NestAI", page_icon="🏠", layout="wide")
st.title("🏠 NestAI")
st.markdown("### Find *your* nest.")


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


# ── Session state ─────────────────────────────────────────────────────────────

for key, default in {
    "listing_text": "",
    "filtered_df": pd.DataFrame(),
    "comparison_df": pd.DataFrame(),
    "parsed_df": pd.DataFrame(),
    "last_result": None,
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
    # Ask NestAI filter state
    "nestai_prompt": "",
    "nestai_last_applied": "",
    # Auth state (requires NESTAI_API_URL in Streamlit secrets)
    "auth_token": None,
    "auth_user": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ── Sidebar — AI Apartment Advisor ────────────────────────────────────────────

with st.sidebar:
    # ── Tier / Credits ───────────────────────────────────────────────────────
    st.markdown("## 💳 Plan & Credits")
    render_tier_badge()

    # Backwards-compat: mirror tier into paid_features_enabled flag
    st.session_state.paid_features_enabled = (get_tier() == "premium")

    st.caption(
        "**Free:** 5 building analyses, basic comparison & ranking.  \n"
        "**Premium ($24.99):** 100 analyses + AI, Walk Score, commute, neighborhood, exports."
    )

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

    st.divider()

    # ── Remove Building ─────────────────────────────────────────────────────
    if not st.session_state.comparison_df.empty:
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
        st.info("Upgrade to Premium to use the AI Advisor.")
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

    # ── User Profile (used for Match %) ─────────────────────────────────────
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

    # ── Account ─────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("## 👤 Account")
    if st.session_state.auth_user:
        user = st.session_state.auth_user
        st.caption(f"Signed in as **{user.get('display_name') or user.get('email', '')}**")
        st.caption(f"Plan: **{user.get('tier', 'free').title()}**")
        if st.button("🚪 Log Out", use_container_width=True, key="logout_btn"):
            st.session_state.auth_token = None
            st.session_state.auth_user = None
            st.rerun()
        if st.page_link("pages/1_Account.py", label="📋 My Account", use_container_width=True):
            pass
        if user.get("is_admin"):
            if st.page_link("pages/2_Admin.py", label="⚙️ Admin Portal", use_container_width=True):
                pass
    else:
        try:
            api_url = st.secrets.get("NESTAI_API_URL", "")
        except Exception:
            api_url = ""
        if api_url:
            if st.page_link("pages/1_Account.py", label="🔑 Sign In / Sign Up", use_container_width=True):
                pass
        else:
            st.caption("Authentication not configured.")


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
    if st.button("🏢 Avalon (Example 1)", use_container_width=True):
        with open(_EXAMPLE_LISTINGS[0][0], "r", encoding="utf-8") as f:
            st.session_state.listing_text = f.read()
        st.rerun()

with c2:
    if st.button("🏢 Cortland (Example 2)", use_container_width=True):
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

        # Cost of living extras for this property (UI hidden; fields retained for internal use)

        if st.button("➕ Save Units", use_container_width=True):
            new_rows = st.session_state.parsed_df.copy()
            for col, val in (st.session_state.cost_extras or {}).items():
                if val is not None:
                    new_rows[f"extra_{col}"] = val
            if "user_notes" not in new_rows.columns:
                new_rows["user_notes"] = ""
            st.session_state.comparison_df = pd.concat(
                [st.session_state.comparison_df, new_rows],
                ignore_index=True,
            )
            if "user_notes" not in st.session_state.comparison_df.columns:
                st.session_state.comparison_df["user_notes"] = ""
            st.session_state.enrichment_done = False
            st.success("Units added!")
            st.rerun()
    else:
        st.warning("No unit rows were parsed from this listing.")

# ── Filter & Rank ─────────────────────────────────────────────────────────────

st.markdown("### <a id='lifestyle-priorities'>🎯 Lifestyle Priorities</a>", unsafe_allow_html=True)

if not st.session_state.comparison_df.empty:
    comp_df = st.session_state.comparison_df.copy()

    st.info("All priorities are optional. Set any slider to 0 to disable it.")
    priority_col1, priority_col2, priority_col3 = st.columns(3)
    with priority_col1:
        commute_priority = st.slider("🚇 Commute", 0, 5, 3, key="commute_slider")
        safety_priority = st.slider("🛡️ Safety", 0, 5, 3, key="safety_slider")
        beds_priority = st.slider("🛏 Bedrooms", 0, 5, 0, key="beds_slider")
    with priority_col2:
        nightlife_priority = st.slider("🍻 Nightlife", 0, 5, 2, key="nightlife_slider")
        budget_priority = st.slider("💰 Budget", 0, 5, 4, key="budget_slider")
        baths_priority = st.slider("🛁 Bathrooms", 0, 5, 0, key="baths_slider")
    with priority_col3:
        gym_priority = st.slider("💪 Gym/Fitness", 0, 5, 2, key="gym_slider")
        amenities_priority = st.slider("🏠 Amenities", 0, 5, 0, key="amenities_slider")
        metro_time_priority = st.slider("🚇 Metro time target", 0, 5, 0, key="metro_time_slider")

    preference_col1, preference_col2 = st.columns(2)
    with preference_col1:
        priority_target_beds = st.selectbox(
            "Preferred beds (for lifestyle priority)",
            options=[None, 0, 1, 2, 3, 4],
            format_func=lambda x: "Any" if x is None else ("Studio" if x == 0 else f"{x} bed"),
            key="priority_target_beds",
        )
        priority_target_baths = st.selectbox(
            "Preferred baths (for lifestyle priority)",
            options=[None, 1.0, 1.5, 2.0, 2.5, 3.0],
            format_func=lambda x: "Any" if x is None else f"{x:g} bath",
            key="priority_target_baths",
        )
        metro_mode_preference = st.selectbox(
            "Metro time mode (for lifestyle priority)",
            options=["walking", "driving"],
            key="priority_metro_mode",
        )
        metro_max_minutes = st.slider(
            "Target max minutes (for metro time priority)",
            min_value=5,
            max_value=90,
            step=5,
            value=30,
            key="priority_metro_max_minutes",
        )
    with preference_col2:
        amenity_options = {
            "In-unit Washer/Dryer": "has_laundry",
            "Gym/Fitness": "has_gym",
            "Pool": "has_pool",
            "Parking": "has_parking",
            "Balcony": "has_balcony",
            "Patio": "has_patio",
            "Security": "has_security",
            "Concierge": "has_concierge",
        }
        selected_amenity_labels = st.multiselect(
            "Preferred amenities (for lifestyle priority)",
            options=list(amenity_options.keys()),
            key="priority_amenities",
        )

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

    with st.form("nestai_filter_form"):
        nestai_input = st.text_area(
            "",
            value=st.session_state.nestai_prompt,
            placeholder="Show me apartments under $2,500 with at least 700 sq ft near a metro station.",
            height=80,
            label_visibility="collapsed",
        )
        apply_col, _ = st.columns([1, 3])
        with apply_col:
            apply_clicked = st.form_submit_button("🔍 Apply", use_container_width=True)

    if apply_clicked:
        prompt_stripped = nestai_input.strip()
        if not prompt_stripped:
            st.warning("Please enter a filter request before clicking Apply.")
        else:
            st.session_state.nestai_prompt = nestai_input
            st.session_state.nestai_last_applied = prompt_stripped
            st.rerun()

    if st.session_state.nestai_last_applied:
        st.caption(f"Active NestAI filter: _{st.session_state.nestai_last_applied}_")

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

    # Ensure user_notes column exists in both comparison_df and working_df
    if "user_notes" not in st.session_state.comparison_df.columns:
        st.session_state.comparison_df["user_notes"] = ""
    if "user_notes" not in working_df.columns:
        working_df = working_df.copy()
        working_df["user_notes"] = ""

    # Propagate user_notes from comparison_df into working_df (keeps notes visible after enrichment)
    if (
        len(working_df) == len(st.session_state.comparison_df)
        and working_df is not st.session_state.comparison_df
    ):
        working_df = working_df.copy()
        working_df["user_notes"] = st.session_state.comparison_df["user_notes"].values

    # ── Unit Notes & Annotations ───────────────────────────────────────────
    st.markdown("### 📝 Unit Notes & Annotations")
    st.caption(
        "Add custom details to any unit (e.g. metro line, noise level, pet policy notes). "
        "Notes are included when NestAI filters your apartments."
    )

    note_display_cols = [c for c in ["property", "unit", "user_notes"] if c in st.session_state.comparison_df.columns]
    edited_notes = st.data_editor(
        st.session_state.comparison_df[note_display_cols].copy(),
        column_config={
            "property": st.column_config.TextColumn("Property", disabled=True, width="medium"),
            "unit": st.column_config.TextColumn("Unit", disabled=True, width="small"),
            "user_notes": st.column_config.TextColumn(
                "Your Notes",
                help="E.g. 'Green line metro', 'loud street noise', 'dog-friendly'. Used by NestAI filter.",
                width="large",
            ),
        },
        use_container_width=True,
        hide_index=True,
        key="unit_notes_editor",
    )

    notes_action_col1, notes_action_col2 = st.columns([2, 1])
    with notes_action_col1:
        apply_to_building = st.checkbox(
            "Apply note to all units in same building",
            help="When checked, a non-empty note on any row will be copied to every other unit in the same building.",
        )
    with notes_action_col2:
        save_notes_clicked = st.button("💾 Save Notes", use_container_width=True)

    if save_notes_clicked:
        updated_notes = edited_notes["user_notes"].fillna("").tolist()

        if apply_to_building and "property" in edited_notes.columns:
            # Build a map: property → first non-empty note
            building_note_map: dict[str, str] = {}
            for prop, note in zip(edited_notes["property"].tolist(), updated_notes):
                if note.strip() and prop not in building_note_map:
                    building_note_map[str(prop)] = note.strip()
            # Apply building-level note to all rows in that building
            updated_notes = [
                building_note_map.get(str(prop), note)
                for prop, note in zip(
                    st.session_state.comparison_df["property"].tolist(),
                    updated_notes,
                )
            ]

        st.session_state.comparison_df["user_notes"] = updated_notes

        # Keep enriched_df in sync so notes survive enrichment
        if (
            st.session_state.enrichment_done
            and not st.session_state.enriched_df.empty
            and len(st.session_state.enriched_df) == len(st.session_state.comparison_df)
        ):
            st.session_state.enriched_df["user_notes"] = updated_notes

        st.success("Notes saved!")
        st.rerun()

    filtered_comp_df = working_df[
        (working_df["price_num"] >= price_range[0])
        & (working_df["price_num"] <= price_range[1])
        & (working_df["sqft_num"] >= sqft_range[0])
        & (working_df["sqft_num"] <= sqft_range[1])
    ]

    last_applied = st.session_state.get("nestai_last_applied", "")
    if last_applied:
        with st.spinner("Applying NestAI filter…"):
            filtered_comp_df = filter_units_by_request(filtered_comp_df, last_applied)

    weights = get_priority_weights_from_sliders(
        {
            "commute": commute_priority,
            "safety": safety_priority,
            "nightlife": nightlife_priority,
            "budget": budget_priority,
            "gym": gym_priority,
            "beds": beds_priority,
            "baths": baths_priority,
            "amenities": amenities_priority,
            "metro_time": metro_time_priority,
        }
    )
    if not weights:
        st.caption("No lifestyle priorities selected; using balanced default priorities.")
        weights = LifestyleScorer.DEFAULT_WEIGHTS.copy()

    lifestyle_preferences = {
        "target_beds": priority_target_beds,
        "target_baths": priority_target_baths,
        "required_amenities": [amenity_options[label] for label in selected_amenity_labels],
        "metro_mode": metro_mode_preference,
        "metro_max_minutes": metro_max_minutes,
    }

    # ── Rankings ───────────────────────────────────────────────────────────
    st.markdown("### <a id='rankings'>🏆 Nest AI Recommendations</a>", unsafe_allow_html=True)
    st.caption("Ranked by your lifestyle priorities, listing data, and your personal profile.")

    if filtered_comp_df.empty:
        if last_applied:
            st.info(
                "🏠 No apartments matched your NestAI request. "
                "Try different criteria or clear the active filter."
            )
        else:
            st.warning("No saved units match your filters.")
    else:
        ranked_df = LifestyleScorer(
            weights,
            user_preferences=lifestyle_preferences,
        ).score_apartments(filtered_comp_df.copy())

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

        # ── Top-3 badges ───────────────────────────────────────────────────
        for i, (_, row) in enumerate(top3.iterrows(), start=1):
            price_num = row.get("price_num")
            sqft_num = row.get("sqft_num")
            price_display = int(price_num) if pd.notna(price_num) else 0
            sqft_display = int(sqft_num) if pd.notna(sqft_num) else 0

            nestai_score = row.get("nestai_score", 0)

            # Price position vs same-bed-count average (no leading minus)
            diff, avg = price_position(row, ranked_df)
            if diff is not None:
                if diff >= 0:
                    price_badge = f"  |  ${abs(diff):,}/mo above avg rent"
                else:
                    price_badge = f"  |  saves ${abs(diff):,}/mo vs avg rent"
            else:
                price_badge = ""

            # Commute display
            commute_display = row.get("commute_display", "")
            commute_line = f"\n🗺 Morning commute: {commute_display}" if commute_display and commute_display != "—" else ""

            st.success(
                f"#{i} • {row.get('property', 'Unknown')} • Unit {row.get('unit', 'N/A')}"
                f"  |  NestAI Score {nestai_score:.0f}/100  \n"
                f"${price_display:,}/mo{price_badge} • {sqft_display} sqft • "
                f"{row.get('beds', '')} • {row.get('baths', '')}"
                f"{commute_line}"
            )

        st.markdown("#### 🎯 Breakdown")
        st.caption(
            "NestAI Score = 60% Lifestyle + 25% Profile Match + 15% Relative Rank (or 85%/15% when no profile is set)."
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
                    "beds": row.get("lifestyle_beds_score", 0),
                    "baths": row.get("lifestyle_baths_score", 0),
                    "amenities": row.get("lifestyle_amenities_score", 0),
                    "metro_time": row.get("lifestyle_metro_time_score", 0),
                }

                with tab1:
                    score_cols = st.columns(3)
                    score_cols[0].metric("NestAI Score", f"{row.get('nestai_score', 0):.0f}/100")
                    score_cols[1].metric(
                        "Price",
                        f"${int(overview_price) if pd.notna(overview_price) else 0:,}/mo",
                    )
                    score_cols[2].metric(
                        "Sq Ft",
                        f"{int(overview_sqft) if pd.notna(overview_sqft) else 0}",
                    )
                    st.markdown(
                        generate_lifestyle_explanation(
                            rank,
                            row,
                            component_scores,
                            weights,
                            ranked_df,
                        )
                    )

                with tab2:
                    st.markdown("**Building Amenities**")
                    st.markdown(generate_amenities_list(row))
                    amenity_col1, amenity_col2 = st.columns(2)
                    with amenity_col1:
                        metro_min_val = row.get("metro_min")
                        if metro_min_val is not None and pd.notna(metro_min_val):
                            st.write(f"🚇 **Metro:** {metro_min_val} min")
                        else:
                            st.write("🚇 **Metro:** Not found")
                            st.caption("No transit stop found within ~30 min or transit data unavailable.")
                        st.write(f"🏥 **Hospital:** {row.get('hospital_min', '—')} min")
                    with amenity_col2:
                        walk_score_value = row.get("official_walk_score") or row.get("walk_score") or "—"
                        st.write(f"🚶 **Walk Score:** {walk_score_value}")
                        st.write(f"💪 **Nearby Gyms:** {row.get('nearby_gyms', '—')}")

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
            "user_notes",
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
    st.info("Add units to compare first. Paste a listing above and click **Save Units**.")


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
