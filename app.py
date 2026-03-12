import pandas as pd
import streamlit as st
from parser.apartment_listing import parse_apartment_listing
from datetime import datetime, timedelta
from llm_helpers import parse_preferences_with_llm, generate_rationale_with_llm
from ranking import rank_listings_with_ai


st.set_page_config(page_title="Apartment Compare AI", layout="wide")


def load_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    except Exception as e:
        return f"Error loading file: {e}"


def money_to_int(value):
    if not value:
        return None
    try:
        return int(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def sqft_to_int(value):
    if not value:
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except Exception:
        return None


def build_comparison_rows(parsed_listing: dict):
    property_title = parsed_listing.get("property_title")
    floorplan_name = parsed_listing.get("floorplan_name")
    beds = parsed_listing.get("beds")
    baths = parsed_listing.get("baths")
    units = parsed_listing.get("units", [])

    rows = []
    for unit in units:
        rent = money_to_int(unit.get("unit_price"))
        sqft = sqft_to_int(unit.get("unit_sqft"))

        rows.append(
            {
                "property_title": property_title,
                "floorplan_name": floorplan_name,
                "beds": beds,
                "baths": baths,
                "unit_label": unit.get("unit_label"),
                "unit_price": rent,
                "unit_sqft": sqft,
                "available_date": unit.get("available_date"),
                "row_text": unit.get("row_text"),
                "rent_per_sqft": round(rent / sqft, 2) if rent and sqft else None,
            }
        )
    return rows


def parse_availability_date(value):
    """
    Convert availability text like:
    - Now
    - Immediately
    - Mar 26
    - Apr 3
    into a sortable datetime.
    """
    if not value:
        return None

    value = str(value).strip()

    if value.lower() in {"now", "immediately"}:
        return datetime.today()

    try:
        return datetime.strptime(f"{value} {datetime.today().year}", "%b %d %Y")
    except ValueError:
        return None

def compute_best_deal_score(row):
    """
    Higher score = better deal.
    Simple MVP logic:
    - lower rent is better
    - higher square footage is better
    - sooner availability is better
    """
    rent = row.get("unit_price")
    sqft = row.get("unit_sqft")
    availability_dt = row.get("availability_dt")

    if pd.isna(rent) or pd.isna(sqft) or rent == 0:
        return None

    score = 0

    # Value from space relative to price
    score += (sqft / rent) * 10000

    # Bonus for sooner availability
    if pd.notna(availability_dt):
        days_until_available = (availability_dt - datetime.today()).days
        if days_until_available <= 0:
            score += 15
        elif days_until_available <= 7:
            score += 10
        elif days_until_available <= 30:
            score += 5

    return round(score, 2)

if "raw_text" not in st.session_state:
    st.session_state.raw_text = ""

if "parsed_listing" not in st.session_state:
    st.session_state.parsed_listing = None

if "comparison_rows" not in st.session_state:
    st.session_state.comparison_rows = []

if "ai_prefs" not in st.session_state:
    st.session_state.ai_prefs = None

if "ai_rationale" not in st.session_state:
    st.session_state.ai_rationale = ""


st.title("Apartment Compare AI")
st.write("Turn copied apartment listing text into structured comparison data.")
st.caption("Built for comparing apartment listings copied from restricted websites.")


left_col, right_col = st.columns([1, 1])

with left_col:
    st.subheader("Paste Listing Text")

    btn1, btn2, btn3 = st.columns(3)

    with btn1:
        if st.button("Load Sample 1"):
            st.session_state.raw_text = load_text_file("data/app_listing_1.txt")
            st.session_state.parsed_listing = None

    with btn2:
        if st.button("Load Sample 2"):
            st.session_state.raw_text = load_text_file("data/app_listing_2.txt")
            st.session_state.parsed_listing = None

    with btn3:
        if st.button("Clear Text"):
            st.session_state.raw_text = ""
            st.session_state.parsed_listing = None

    raw_text = st.text_area(
        "Paste apartment listing text here",
        value=st.session_state.raw_text,
        height=320,
        placeholder="Paste copied apartment listing text here...",
    )

    if st.button("Extract Data", type="primary"):
        if raw_text.strip():
            parsed = parse_apartment_listing(raw_text)
            st.session_state.parsed_listing = parsed
            st.session_state.raw_text = raw_text
        else:
            st.warning("Please paste text or load a sample listing first.")


with right_col:
    st.subheader("Extracted Listing Details")

    parsed_listing = st.session_state.parsed_listing

    if parsed_listing:
        st.write(f"**Property Title:** {parsed_listing.get('property_title') or 'N/A'}")
        st.write(f"**Floorplan Name:** {parsed_listing.get('floorplan_name') or 'N/A'}")
        st.write(f"**Beds:** {parsed_listing.get('beds') or 'N/A'}")
        st.write(f"**Baths:** {parsed_listing.get('baths') or 'N/A'}")
        st.write(
            f"**Floorplan Price Range:** {parsed_listing.get('floorplan_price_range') or 'N/A'}"
        )
        st.write(
            f"**Floorplan Sq Ft Range:** {parsed_listing.get('floorplan_sqft_range') or 'N/A'}"
        )
        st.write(
            f"**Has Den:** {'Yes' if parsed_listing.get('floorplan_has_den') else 'No'}"
        )

        units = parsed_listing.get("units", [])
        st.write(f"**Units Parsed:** {len(units)}")

        if units:
            unit_df = pd.DataFrame(units)
            st.dataframe(unit_df, use_container_width=True)

            if st.button("Add Units to Comparison Table"):
                rows = build_comparison_rows(parsed_listing)
                st.session_state.comparison_rows.extend(rows)
                st.success(f"Added {len(rows)} unit rows to comparison table.")
        else:
            st.warning("No unit rows were parsed from this listing.")

        with st.expander("Show parsed JSON"):
            st.json(parsed_listing)
    else:
        st.info("No listing parsed yet.")


st.subheader("Comparison Table")

if st.session_state.comparison_rows:
    comparison_df = pd.DataFrame(st.session_state.comparison_rows)

    # Convert availability text into a sortable date
    comparison_df["availability_dt"] = comparison_df["available_date"].apply(parse_availability_date)
    comparison_df["best_deal_score"] = comparison_df.apply(compute_best_deal_score, axis=1)

    st.markdown("---")
    st.subheader("AI Best Match")

    ai_query = st.text_area(
        "Describe what you want",
        placeholder="Example: I want the best value studio under $2400 with as much space as possible and available soon",
        height=100,
    )

    if st.button("Find Best Matches with AI"):
        if not ai_query.strip():
            st.warning("Please describe what you're looking for.")
        else:
            try:
                prefs = parse_preferences_with_llm(ai_query)
                st.session_state.ai_prefs = prefs

                ai_ranked_df = rank_listings_with_ai(comparison_df, prefs)

                if ai_ranked_df.empty:
                    st.warning("No listings matched your AI search.")
                    st.session_state.ai_rationale = ""
                else:
                    top_results = ai_ranked_df[
                        [
                            "property_title",
                            "floorplan_name",
                            "unit_label",
                            "beds",
                            "baths",
                            "unit_price",
                            "unit_sqft",
                            "available_date",
                            "rent_per_sqft",
                            "best_deal_score",
                            "ai_match_score",
                        ]
                    ].head(3).to_dict(orient="records")

                    rationale = generate_rationale_with_llm(ai_query, prefs, top_results)
                    st.session_state.ai_rationale = rationale

            except Exception as e:
                st.error(f"AI matching failed: {e}")

    if st.session_state.ai_prefs:
        with st.expander("Show parsed AI preferences"):
            st.json(st.session_state.ai_prefs)

        ai_ranked_df = rank_listings_with_ai(comparison_df, st.session_state.ai_prefs)

        if not ai_ranked_df.empty:
            ai_display_cols = [
                "property_title",
                "floorplan_name",
                "unit_label",
                "beds",
                "baths",
                "unit_price",
                "unit_sqft",
                "available_date",
                "rent_per_sqft",
                "best_deal_score",
                "ai_match_score",
            ]

            ai_display_df = ai_ranked_df[ai_display_cols].copy()

            ai_display_df["unit_price"] = ai_display_df["unit_price"].apply(
                lambda x: f"${int(x):,}" if pd.notnull(x) else ""
            )
            ai_display_df["rent_per_sqft"] = ai_display_df["rent_per_sqft"].apply(
                lambda x: f"${x:.2f}" if pd.notnull(x) else ""
            )
            ai_display_df["best_deal_score"] = ai_display_df["best_deal_score"].apply(
                lambda x: f"{x:.1f}" if pd.notnull(x) else ""
            )
            ai_display_df["ai_match_score"] = ai_display_df["ai_match_score"].apply(
                lambda x: f"{x:.1f}" if pd.notnull(x) else ""
            )

            st.markdown("### AI Top Matches")
            st.dataframe(ai_display_df.head(10), use_container_width=True)

            if st.session_state.ai_rationale:
                st.markdown("### Why these ranked highly")
                st.write(st.session_state.ai_rationale)
    
    st.markdown("### Filter Listings")

    f1, f2, f3, f4 = st.columns(4)

    with f1:
            availability_filter = st.selectbox(
                "Availability",
                [
                    "All",
                    "Now / Immediately",
                    "Within 7 Days",
                    "Within 30 Days",
                ],
            )

    with f2:
            max_budget = st.slider(
                "Max Budget ($)",
                min_value=1000,
                max_value=6000,
                value=4000,
                step=50,
            )

    with f3:
            min_sqft = st.slider(
                "Minimum Sq Ft",
                min_value=300,
                max_value=1500,
                value=500,
                step=25,
            )

    with f4:
            sort_option = st.selectbox(
                "Sort By",
                [
                    "Best Deal Score",
                    "Price per Sq Ft",
                    "Lowest Price",
                    "Largest Unit",
                    "Soonest Available",
                ],
            )
    
    filtered_df = comparison_df.copy()

    today = datetime.today()
    seven_days = today + timedelta(days=7)
    thirty_days = today + timedelta(days=30)

    # Budget filter
    filtered_df = filtered_df[
            filtered_df["unit_price"].isna() | (filtered_df["unit_price"] <= max_budget)
        ]

    # Square footage filter
    filtered_df = filtered_df[
            filtered_df["unit_sqft"].isna() | (filtered_df["unit_sqft"] >= min_sqft)
        ]

     # -----------------------
        # Availability filters
        # -----------------------
    if availability_filter == "Now / Immediately":
            filtered_df = filtered_df[
                filtered_df["available_date"].astype(str).str.lower().isin(["now", "immediately"])
            ]

    elif availability_filter == "Within 7 Days":
            filtered_df = filtered_df[
                filtered_df["availability_dt"].notna()
                & (filtered_df["availability_dt"] <= seven_days)
            ]

    elif availability_filter == "Within 30 Days":
            filtered_df = filtered_df[
                filtered_df["availability_dt"].notna()
                & (filtered_df["availability_dt"] <= thirty_days)
            ]





       
        # -----------------------
        # Sorting
        # -----------------------
    if sort_option == "Best Deal Score":
            filtered_df = filtered_df.sort_values("best_deal_score", ascending=False)

    elif sort_option == "Price per Sq Ft":
            filtered_df = filtered_df.sort_values("rent_per_sqft", ascending=True)

    elif sort_option == "Lowest Price":
            filtered_df = filtered_df.sort_values("unit_price", ascending=True)

    elif sort_option == "Largest Unit":
            filtered_df = filtered_df.sort_values("unit_sqft", ascending=False)

    elif sort_option == "Soonest Available":
            filtered_df = filtered_df.sort_values("availability_dt", ascending=True)
        

    display_cols = [
        "property_title",
        "floorplan_name",
        "unit_label",
        "unit_price",
        "unit_sqft",
        "available_date",
        "rent_per_sqft",
        "best_deal_score",
        ]

    display_df = filtered_df[display_cols].copy()

    if "unit_price" in display_df.columns:
            display_df["unit_price"] = display_df["unit_price"].apply(
                lambda x: f"${int(x):,}" if pd.notnull(x) else ""
            )

    if "rent_per_sqft" in display_df.columns:
            display_df["rent_per_sqft"] = display_df["rent_per_sqft"].apply(
                lambda x: f"${x:.2f}" if pd.notnull(x) else ""
            )

    if "best_deal_score" in display_df.columns:
            display_df["best_deal_score"] = display_df["best_deal_score"].apply(
                lambda x: f"{x:.1f}" if pd.notnull(x) else ""
            )

    st.dataframe(display_df, use_container_width=True)

        # -----------------------
        # Insights
        # -----------------------




    c1, c2, c3 = st.columns(3)

    valid_rent = filtered_df.dropna(subset=["unit_price"])
    valid_sqft = filtered_df.dropna(subset=["unit_sqft"])
    valid_value = filtered_df.dropna(subset=["rent_per_sqft"])

    with c1:
        if not valid_rent.empty:
            lowest = valid_rent.loc[valid_rent["unit_price"].idxmin()]
            st.metric("Lowest Rent", f"${int(lowest['unit_price']):,}")
        else:
            st.metric("Lowest Rent", "N/A")

    with c2:
        if not valid_sqft.empty:
            largest = valid_sqft.loc[valid_sqft["unit_sqft"].idxmax()]
            st.metric("Largest Unit", f"{int(largest['unit_sqft'])} sq ft")
        else:
            st.metric("Largest Unit", "N/A")

    with c3:
        if not valid_value.empty:
            best_value = valid_value.loc[valid_value["rent_per_sqft"].idxmin()]
            st.metric("Best Value", f"${best_value['rent_per_sqft']}/sq ft")
        else:
            st.metric("Best Value", "N/A")

    clear1, clear2 = st.columns(2)

    with clear1:
        if st.button("Remove Last Added Row"):
            if st.session_state.comparison_rows:
                st.session_state.comparison_rows.pop()
                st.rerun()

    with clear2:
        if st.button("Clear Comparison Table"):
            st.session_state.comparison_rows = []
            st.rerun()

else:
        st.info("No saved comparison rows yet.")