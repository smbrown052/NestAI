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

    # Show full property name without truncation before the metric columns
    property_title = result.get("property_title") or "Unknown"
    st.markdown(f"**{property_title}**")

    m2, m3, m4, m5 = st.columns(4)

    m2.metric("Units Parsed", result.get("unit_count", 0))
    m3.metric(
        "Nearest Metro",
        format_travel(building.get("metro_travel_mode"), building.get("metro_min"))
    )
    m4.metric(
        "Nearest Hospital",
        format_travel(building.get("hospital_travel_mode"), building.get("hospital_min"))
    )

    # Show walk score and safety score when available
    walk_score = result.get("units", [{}])[0].get("walk_score") if result.get("units") else None
    safety_score = result.get("units", [{}])[0].get("safety_score") if result.get("units") else None
    m5.metric(
        "Walk Score",
        f"{walk_score} / 100" if walk_score is not None else "—"
    )

    if result.get("address"):
        st.caption(result.get("address"))

    if safety_score is not None:
        st.caption(f"Safety Score: {safety_score} / 100 (based on renter rating)")

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

        if "walk_score" in ranked_df.columns:
            ranked_df["walk_score_score"] = ranked_df["walk_score"].fillna(0).rank(ascending=True)
        else:
            ranked_df["walk_score_score"] = 0

        if "safety_score" in ranked_df.columns:
            ranked_df["safety_score_rank"] = ranked_df["safety_score"].fillna(0).rank(ascending=True)
        else:
            ranked_df["safety_score_rank"] = 0

        ranked_df["nest_score"] = (
            ranked_df["price_score"] * 0.30 +
            ranked_df["space_score"] * 0.25 +
            ranked_df["metro_score"] * 0.20 +
            ranked_df["floor_score"] * 0.10 +
            ranked_df["walk_score_score"] * 0.10 +
            ranked_df["safety_score_rank"] * 0.05
        )

        ranked_df = ranked_df.sort_values("nest_score", ascending=False)

        top3 = ranked_df.head(3)

        # Show all top-ranked apartments (up to 3, or fewer if fewer exist)
        for i, (_, row) in enumerate(top3.iterrows(), start=1):
            price_num = row.get("price_num")
            sqft_num = row.get("sqft_num")
            price_display = int(price_num) if pd.notna(price_num) else 0
            sqft_display = int(sqft_num) if pd.notna(sqft_num) else 0
            st.success(
                f"#{i} • {row.get('property', 'Unknown')} • Unit {row.get('unit', 'N/A')}  \n"
                f"${price_display:,} • {sqft_display} sqft • "
                f"{row.get('beds', '')} • {row.get('baths', '')}"
            )

        # Tradeoffs section: compare each top apartment against the others
        if len(top3) > 1:
            st.markdown("### 📊 Tradeoffs")
            st.caption("How each top-ranked apartment compares to the others on key criteria.")

            tradeoff_criteria = [
                ("price_num", "price", False),          # lower is better
                ("sqft_num", "square footage", True),    # higher is better
                ("metro_min", "metro distance", False),  # lower is better
                ("floor", "floor level", True),          # higher is better
                ("walk_score", "walk score", True),      # higher is better
                ("safety_score", "safety score", True),  # higher is better
            ]

            top3_rows = list(top3.iterrows())
            apt_labels = {
                idx: f"#{rank} (Unit {row.get('unit', 'N/A')})"
                for rank, (idx, row) in enumerate(top3_rows, start=1)
            }

            for rank, (idx, row) in enumerate(top3_rows, start=1):
                label = apt_labels[idx]
                bullets = []
                for col, display_name, higher_is_better in tradeoff_criteria:
                    if col not in ranked_df.columns:
                        continue
                    val = row.get(col)
                    try:
                        val = float(val)
                        if pd.isna(val):
                            raise ValueError("missing")
                    except (ValueError, TypeError):
                        bullets.append(f"No data on {display_name}")
                        continue

                    for other_idx, other_row in top3_rows:
                        if other_idx == idx:
                            continue
                        other_label = apt_labels[other_idx]
                        other_val = other_row.get(col)
                        try:
                            other_val = float(other_val)
                            if pd.isna(other_val):
                                raise ValueError("missing")
                        except (ValueError, TypeError):
                            continue

                        if (higher_is_better and val > other_val) or (
                            not higher_is_better and val < other_val
                        ):
                            bullets.append(f"Better than {other_label} on {display_name}")
                        elif val == other_val:
                            bullets.append(f"Equal to {other_label} on {display_name}")
                        else:
                            bullets.append(f"Not better than {other_label} on {display_name}")

                with st.expander(f"{label} — Tradeoffs", expanded=True):
                    for bullet in bullets:
                        st.write(f"- {bullet}")

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
            "walk_score",
            "safety_score",
            "nest_score",
        ]

        display_cols = [col for col in display_cols if col in ranked_df.columns]
        clean_ranked_df = ranked_df[display_cols].copy()

        if "nest_score" in clean_ranked_df.columns:
            clean_ranked_df["nest_score"] = clean_ranked_df["nest_score"].round(2)

        st.dataframe(clean_ranked_df, use_container_width=True)
else:
    st.info("Add units to compare first.")
