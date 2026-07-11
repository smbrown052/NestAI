import os
import streamlit as st
import pandas as pd
from text_parser import parse_apartment_text, filter_units_by_request
import json


def make_streamlit_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Convert nested or inconsistent object values into display-safe scalars."""
    if df is None or df.empty:
        return pd.DataFrame()

    safe_df = df.copy()

    for column in safe_df.columns:
        if safe_df[column].dtype == "object":
            safe_df[column] = safe_df[column].map(
                lambda value: json.dumps(value, default=str)
                if isinstance(value, (dict, list, tuple, set))
                else value
            )

    return safe_df

st.title("🏠 NestAI")
st.markdown("### Find *your* nest.")

st.markdown(
    """
    <style>
    .summary-card {
        min-height: 112px;
        padding: 16px;
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 12px;
        background: rgba(128, 128, 128, 0.05);
    }

    .summary-label {
        font-size: 0.82rem;
        color: #6b7280;
        margin-bottom: 8px;
        font-weight: 600;
    }

    .summary-value {
        font-size: 1.15rem;
        font-weight: 700;
        line-height: 1.3;
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: normal;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

def format_travel(mode, minutes):
    if mode and minutes:
        return f"{mode.title()} · {minutes} min"
    return "—"

def summary_card(label, value):
    safe_value = value if value not in (None, "") else "—"

    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-label">{label}</div>
            <div class="summary-value">{safe_value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
for key, default in {
    "listing_text": "",
    "filtered_df": pd.DataFrame(),
    "comparison_df": pd.DataFrame(),
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

    example_1, example_2, clear = st.columns(3)

    with example_1:
        if st.button(
            "🏢 Example 1",
            help="Load the first sample apartment listing",
            use_container_width=True,
        ):
            with open("data/app_listing_1.txt", "r", encoding="utf-8") as f:
                st.session_state.listing_text = f.read()
    
            st.session_state.last_result = None
            st.session_state.parsed_df = pd.DataFrame()
            st.rerun()
    
    with example_2:
        if st.button(
            "🏙️ Example 2",
            help="Load a sample Arlington apartment listing",
            use_container_width=True,
        ):
            with open("data/app_listing_2.txt", "r", encoding="utf-8") as f:
                st.session_state.listing_text = f.read()
    
            st.session_state.last_result = None
            st.session_state.parsed_df = pd.DataFrame()
            st.rerun()

with clear:
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
    else:
        st.warning("Paste listing text first.")

if st.session_state.last_result:
    result = st.session_state.last_result
    building = result.get("building_nearby", {})

    st.markdown("### 🏠 Property Summary")

    m1, m2, m3, m4 = st.columns(4)

    with m1:
        summary_card(
            "Property",
            result.get("property_title") or "Unknown",
        )
    
    with m2:
        summary_card(
            "Units Parsed",
            str(result.get("unit_count", 0)),
        )
    
    with m3:
        summary_card(
            "Nearest Metro",
            format_travel(
                building.get("metro_travel_mode"),
                building.get("metro_min"),
            ),
        )
    
    with m4:
        summary_card(
            "Nearest Hospital",
            format_travel(
                building.get("hospital_travel_mode"),
                building.get("hospital_min"),
            ),
        )

    if result.get("address"):
        st.caption(result.get("address"))

    if result.get("nearby_places"):
        with st.expander("View nearby building-level places"):
            st.dataframe(pd.DataFrame(result["nearby_places"]), use_container_width=True)

if not st.session_state.comparison_df.empty:
    comp_df = st.session_state.comparison_df.copy()

    comp_df["price_num"] = pd.to_numeric(
        comp_df.get("price_num"),
        errors="coerce",
    )

    comp_df["sqft_num"] = pd.to_numeric(
        comp_df.get("sqft_num"),
        errors="coerce",
    )

    comp_df = comp_df.dropna(subset=["price_num", "sqft_num"])

    if comp_df.empty:
        st.warning("Saved units do not contain valid price and square-footage values.")
        st.stop()

    min_price = int(comp_df["price_num"].min())
    max_price = int(comp_df["price_num"].max())

    price_range = st.slider(
        "Monthly price range",
        min_value=min_price,
        max_value=max_price,
        value=(min_price, max_price),
        step=50,
    )

    min_sqft = int(comp_df["sqft_num"].min())
    max_sqft = int(comp_df["sqft_num"].max())

    sqft_range = st.slider(
        "Square footage",
        min_value=min_sqft,
        max_value=max_sqft,
        value=(min_sqft, max_sqft),
        step=50,
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

        st.dataframe(
            make_streamlit_safe(clean_ranked_df),
            use_container_width=True,
        )
else:
    st.info("Add units to compare first.")
