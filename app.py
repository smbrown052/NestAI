import time as _time

import streamlit as st
import pandas as pd

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

st.info("""
🚀 **Try an example or get your own.**

Go to an Apartments.com listing, press **Ctrl + A**, then **Ctrl + C**, paste everything below.
""")

# ── Paste & Analyze ───────────────────────────────────────────────────────────

left, right = st.columns([1.15, 0.85], gap="large")

with left:
    st.markdown("### 1. Paste Listing Text")

    c1, c2, c3 = st.columns(3)

    with c1:
        if st.button("🏢 Load Example 1", use_container_width=True):
            with open("data/app_listing_1.txt", "r", encoding="utf-8") as f:
                st.session_state.listing_text = f.read()
            st.rerun()

    with c2:
        if st.button("🏢 Load Example 2", use_container_width=True):
            with open("data/app_listing_2.txt", "r", encoding="utf-8") as f:
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

with right:
    st.markdown("### How to use it")
    st.write("""
    1. Open an apartment listing on Apartments.com.
    2. Expand all floor plans and click **Show More** so all units are visible.
    3. Press **Ctrl + A** then **Ctrl + C**.
    4. Paste the text here and click **Analyze Apartment**.
    5. Save units into your comparison table (or load Example 1/2).
    6. Optionally enable paid APIs/models for AI + official Walk/Transit/Bike scores.
    7. Filter, rank, and review tradeoffs.
    """)

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
    m3.metric(
        "Nearest Metro",
        format_travel(building.get("metro_travel_mode"), building.get("metro_min")),
    )
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
        st.warning("No unit rows were parsed from this listing.")

# ── Filter & Rank ─────────────────────────────────────────────────────────────

st.markdown("### <a id='lifestyle-priorities'>🎯 Lifestyle Priorities</a>", unsafe_allow_html=True)

if not st.session_state.comparison_df.empty:
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

        ranked_df = ranked_df.sort_values(
            ["lifestyle_score", "nest_score"],
            ascending=[False, False],
        )
        top3 = ranked_df.head(3)

        # ── Top-3 badges ───────────────────────────────────────────────────
        for i, (_, row) in enumerate(top3.iterrows(), start=1):
            price_num = row.get("price_num")
            sqft_num = row.get("sqft_num")
            price_display = int(price_num) if pd.notna(price_num) else 0
            sqft_display = int(sqft_num) if pd.notna(sqft_num) else 0

            # Match %
            profile = st.session_state.user_profile
            match_pct = compute_match_score(row, profile) if any(profile.values()) else None
            match_badge = f"  |  {match_pct:.0f}% match" if match_pct else ""

            # Price position vs same-bed-count average
            diff, avg = price_position(row, ranked_df)
            if diff is not None:
                sign = "+" if diff >= 0 else ""
                price_badge = f"  |  {sign}${diff:,} vs avg"
            else:
                price_badge = ""

            # Commute display
            commute_display = row.get("commute_display", "")
            commute_line = f"\n🗺 Morning commute: {commute_display}" if commute_display and commute_display != "—" else ""

            st.success(
                f"#{i} • {row.get('property', 'Unknown')} • Unit {row.get('unit', 'N/A')}"
                f"{match_badge}  |  Lifestyle {row.get('lifestyle_score', 0):.0f}/100  \n"
                f"${price_display:,}/mo{price_badge} • {sqft_display} sqft • "
                f"{row.get('beds', '')} • {row.get('baths', '')}"
                f"{commute_line}"
            )

        st.markdown("#### 🎯 Lifestyle Breakdown")
        st.caption(
            "Lifestyle Score uses 5 weighted categories. Match % is profile-fit only, so the two can differ."
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
                    score_cols = st.columns(4)
                    score_cols[0].metric("Lifestyle Score", f"{row.get('lifestyle_score', 0):.0f}/100")
                    score_cols[1].metric("Nest Score", f"{row.get('nest_score', 0):.2f}")
                    score_cols[2].metric(
                        "Price",
                        f"${int(overview_price) if pd.notna(overview_price) else 0:,}/mo",
                    )
                    score_cols[3].metric(
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
                            priority_rank_fn=lambda name: get_priority_rank(name, weights),
                        )
                    )

                with tab2:
                    st.markdown("**Building Amenities**")
                    st.markdown(generate_amenities_list(row))
                    amenity_col1, amenity_col2 = st.columns(2)
                    with amenity_col1:
                        st.write(f"🚇 **Metro:** {row.get('metro_min', '—')} min")
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

        # ── Apartment Match % section ──────────────────────────────────────
        if any(st.session_state.user_profile.values()):
            st.markdown("#### 🎯 Your Match Breakdown")
            for i, (_, row) in enumerate(top3.iterrows(), start=1):
                match_pct = compute_match_score(row, st.session_state.user_profile)
                reasons = explain_match(row, st.session_state.user_profile, match_pct)
                color = "green" if match_pct >= 70 else "orange" if match_pct >= 50 else "red"
                st.markdown(
                    f"**#{i} Unit {row.get('unit', 'N/A')}** — "
                    f":{color}[**{match_pct:.0f}% match**]"
                )
                for reason in reasons:
                    st.write(f"  - {reason}")

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

        # ── Tradeoffs ──────────────────────────────────────────────────────
        if len(top3) > 1:
            st.markdown("#### 📊 Tradeoffs")
            st.caption(
                "Major differences are shown first; if units are similar, tie-breakers show specific amenities."
            )

            top3_rows = list(top3.iterrows())

            def apt_label(r):
                return f"{r.get('property', 'Unknown')} · Unit {r.get('unit', 'N/A')}"

            major_metric_rules = [
                ("price_num", 150.0, "price"),
                ("sqft_num", 100.0, "space"),
                ("metro_min", 4.0, "metro time"),
                ("walk_score", 8.0, "walk score"),
                ("official_walk_score", 8.0, "walk score"),
                ("safety_score", 8.0, "safety score"),
            ]

            amenity_fields = [
                ("has_gym", "gym"),
                ("has_fitness", "fitness center"),
                ("has_pool", "pool"),
                ("has_laundry", "in-unit laundry"),
                ("has_parking", "parking"),
                ("has_balcony", "balcony"),
                ("has_den", "den"),
                ("has_security", "24hr security"),
                ("has_concierge", "concierge"),
            ]

            for rank, (idx, row) in enumerate(top3_rows, start=1):
                label = apt_label(row)
                with st.expander(f"{label} — Tradeoffs", expanded=(rank == 1)):
                    for other_idx, other_row in top3_rows:
                        if other_idx == idx:
                            continue

                        other_label = apt_label(other_row)
                        major_diffs = []

                        for col, threshold, name in major_metric_rules:
                            if col not in ranked_df.columns:
                                continue
                            v1 = row.get(col)
                            v2 = other_row.get(col)
                            if pd.isna(v1) or pd.isna(v2):
                                continue
                            diff = float(v1) - float(v2)
                            if abs(diff) < threshold:
                                continue

                            if name == "price":
                                direction = "higher" if diff > 0 else "lower"
                                major_diffs.append(f"{abs(diff):.0f} {direction} monthly rent")
                            elif name == "space":
                                direction = "more" if diff > 0 else "less"
                                major_diffs.append(f"{abs(diff):.0f} sq ft {direction} space")
                            else:
                                direction = "higher" if diff > 0 else "lower"
                                major_diffs.append(f"{abs(diff):.0f} points {direction} {name}")

                        if major_diffs:
                            st.write(f"- vs **{other_label}**: " + "; ".join(major_diffs))
                            continue

                        amenity_diffs = []
                        for field, name in amenity_fields:
                            has_current = bool(row.get(field, False))
                            has_other = bool(other_row.get(field, False))
                            if has_current and not has_other:
                                amenity_diffs.append(f"has {name}")
                            elif has_other and not has_current:
                                amenity_diffs.append(f"missing {name}")

                        if amenity_diffs:
                            st.write(f"- vs **{other_label}**: " + ", ".join(amenity_diffs))
                        else:
                            st.write(f"- vs **{other_label}**: very similar on major metrics and amenities.")

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
            "lifestyle_score",
            "lifestyle_commute_score",
            "lifestyle_safety_score",
            "lifestyle_nightlife_score",
            "lifestyle_budget_score",
            "lifestyle_gym_score",
            "nest_score",
        ]

        display_cols = [c for c in display_cols if c in ranked_df.columns]
        clean_ranked_df = ranked_df[display_cols].copy()

        for score_col in (
            "nest_score",
            "lifestyle_score",
            "lifestyle_commute_score",
            "lifestyle_safety_score",
            "lifestyle_nightlife_score",
            "lifestyle_budget_score",
            "lifestyle_gym_score",
        ):
            if score_col in clean_ranked_df.columns:
                clean_ranked_df[score_col] = clean_ranked_df[score_col].round(2)

        st.dataframe(clean_ranked_df, use_container_width=True)

else:
    st.info("Add units to compare first. Paste a listing above and click **Save Units**.")
