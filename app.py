import os
import streamlit as st
import pandas as pd
from text_parser import parse_apartment_text, filter_units_by_request

st.title("🏠 NestAI")
st.markdown("### Find *your* nest.")

def format_travel(mode, minutes):
    if mode and minutes:
        return f"{mode.title()} · {minutes} min"
    return "—"

for key, default in {
    "listing_text": "",
    "filtered_df": pd.DataFrame(),
    "comparison_df": pd.DataFrame(),
    "parsed_df": pd.DataFrame(),
    "last_result": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown("""
<div class="hero">
    <p>
    Find your next apartment in seconds. Compare floor plans, pricing,
    square footage, metro access, and amenities without building spreadsheets.
    </p>
</div>
""", unsafe_allow_html=True)

with st.expander("Why Nest AI?", expanded=True):
    st.write("""
Apartment hunting often means comparing dozens of tabs, prices, floor plans, fees, locations, and availability dates manually.

Nest AI turns unstructured Apartments.com listing text into structured, filterable, ranked recommendations — helping renters make faster, clearer decisions.
""")

st.info("""
🚀 **Try an example or get your own.**

Go to an Apartments.com listing, press **Ctrl + A**, then **Ctrl + C**, paste everything below, and let the magic happen.
""")

st.markdown("### What it does")
st.write("""
- Extracts units from copied apartment listing text
- Pulls rent, square footage, availability, beds, baths, floor, and nearby transit
- Saves units into a comparison table
- Lets you filter by natural language preferences
- Ranks apartments based on price, space, metro access, and floor
""")

left, right = st.columns([1.15, 0.85], gap="large")

with left:
    st.markdown("### 1. Paste Listing Text")

    c1, c2 = st.columns(2)

    with c1:
        if st.button("🏢 Load Example Listing", use_container_width=True):
            with open("data/app_listing_1.txt", "r", encoding="utf-8") as f:
                st.session_state.listing_text = f.read()
            st.rerun()

    with c2:
        if st.button("🧹 Clear Text", use_container_width=True):
            st.session_state.listing_text = ""
            st.session_state.last_result = None
            st.session_state.parsed_df = pd.DataFrame()
            st.rerun()

    listing_text = st.text_area(
        "Apartment listing text",
        key="listing_text",
        height=420,
        placeholder="Paste copied Apartments.com listing text here..."
    )

analyze = st.button("✨ Analyze Apartment", use_container_width=True)

with right:
    st.markdown("### How to use it")
    st.write("""
    1. Open an apartment listing.
    2. Press **Ctrl + A**.
    3. Press **Ctrl + C**.
    4. Paste the copied text here.
    5. Click **Analyze Apartment**.
    6. Save units into your comparison table.
    """)

if analyze:
    if st.session_state.listing_text.strip():
        result = parse_apartment_text(st.session_state.listing_text)
        st.session_state.last_result = result
        st.session_state.parsed_df = pd.DataFrame(result.get("units", []))
    else:
        st.warning("Paste listing text first.")

if st.session_state.last_result:
    result = st.session_state.last_result
    building = result.get("building_nearby", {})

    st.markdown("### 🏠 Property Summary")

    m1, m2, m3, m4 = st.columns(4)

    m1.metric("Property", result.get("property_title") or "Unknown")
    m2.metric("Units Parsed", result.get("unit_count", 0))
    m3.metric(
        "Nearest Metro",
        format_travel(building.get("metro_travel_mode"), building.get("metro_min"))
    )
    m4.metric(
        "Nearest Hospital",
        format_travel(building.get("hospital_travel_mode"), building.get("hospital_min"))
    )

    if result.get("address"):
        st.caption(result.get("address"))

    if result.get("nearby_places"):
        with st.expander("View nearby building-level places"):
            st.dataframe(pd.DataFrame(result["nearby_places"]), use_container_width=True)

    if not st.session_state.parsed_df.empty:
        st.markdown("### 📋 Parsed Units")
        st.caption("Units extracted from the current building. Save them, then filter and rank below.")
        st.dataframe(st.session_state.parsed_df, use_container_width=True)

        if st.button("➕ Save Units", use_container_width=True):
            st.session_state.comparison_df = pd.concat(
                [st.session_state.comparison_df, st.session_state.parsed_df],
                ignore_index=True
            )
            st.success("Units added!")
            st.rerun()
    else:
        st.warning("No unit rows were parsed from this listing.")

st.markdown("### 🔎 Filter & Rank Your Apartments")

if not st.session_state.comparison_df.empty:
    comp_df = st.session_state.comparison_df.copy()

    min_price = int(comp_df["price_num"].min())
    max_price = int(comp_df["price_num"].max())

    price_range = st.slider(
        "Monthly price range",
        min_value=min_price,
        max_value=max_price,
        value=(min_price, max_price),
        step=50
    )

    min_sqft = int(comp_df["sqft_num"].min())
    max_sqft = int(comp_df["sqft_num"].max())

    sqft_range = st.slider(
        "Square footage range",
        min_value=min_sqft,
        max_value=max_sqft,
        value=(min_sqft, max_sqft),
        step=25
    )

    llm_request = st.text_input(
        "Ask Nest AI to filter your saved units",
        value="1 bed not on the first floor within 10 min walk of metro"
    )

    filtered_comp_df = comp_df[
        (comp_df["price_num"] >= price_range[0]) &
        (comp_df["price_num"] <= price_range[1]) &
        (comp_df["sqft_num"] >= sqft_range[0]) &
        (comp_df["sqft_num"] <= sqft_range[1])
    ]

    filtered_comp_df = filter_units_by_request(filtered_comp_df, llm_request)

    st.markdown("### 🏆 Nest AI Recommendations")
    st.caption("Compare all your saved units to see what fits your personalized needs.")

    if filtered_comp_df.empty:
        st.warning("No saved units match your filters.")
    else:
        ranked_df = filtered_comp_df.copy()

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

        ranked_df["nest_score"] = (
            ranked_df["price_score"] * 0.35 +
            ranked_df["space_score"] * 0.30 +
            ranked_df["metro_score"] * 0.25 +
            ranked_df["floor_score"] * 0.10
        )

        ranked_df = ranked_df.sort_values("nest_score", ascending=False)

        top3 = ranked_df.head(3)

        for i, (_, row) in enumerate(top3.iterrows(), start=1):
            st.success(
                f"#{i} • {row.get('property', 'Unknown')} • Unit {row.get('unit', 'N/A')}  \n"
                f"${int(row.get('price_num', 0)):,} • {int(row.get('sqft_num', 0))} sqft • "
                f"{row.get('beds', '')} • {row.get('baths', '')}"
            )

        display_cols = [
            "property",
            "floorplan",
            "unit",
            "floor",
            "price",
            "beds",
            "baths",
            "sqft",
            "has_den",
            "availability",
            "nearest_metro",
            "metro_travel_mode",
            "metro_min",
            "nearest_hospital",
            "hospital_travel_mode",
            "hospital_min",
            "nest_score",
        ]

        display_cols = [col for col in display_cols if col in ranked_df.columns]
        clean_ranked_df = ranked_df[display_cols].copy()

        if "nest_score" in clean_ranked_df.columns:
            clean_ranked_df["nest_score"] = clean_ranked_df["nest_score"].round(2)

        st.dataframe(clean_ranked_df, use_container_width=True)
else:
    st.info("Add units to compare first.")
