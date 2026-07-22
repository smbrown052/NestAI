import os
import streamlit as st
import pandas as pd
from text_parser import parse_apartment_text, filter_units_by_request
from lifestyle_scoring import LifestyleScorer, get_priority_weights_from_sliders
from lifestyle_explanations import generate_lifestyle_explanation, generate_amenities_list
from tradeoff_assistant import TradeoffAnalyzer
from regret_analyzer import RegretAnalyzer

st.set_page_config(layout="wide")

st.title("🏠 NestAI")
st.markdown("### Find *your* nest.")

def format_travel(mode, minutes):
    if mode and minutes:
        return f"{mode.title()} · {minutes} min"
    return "—"

def get_priority_rank(priority_name: str, weights: dict) -> str:
    """
    Convert priority weight to human-readable rank (1st, 2nd, tied for 2nd, etc.)
    """
    sorted_priorities = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    
    # Find position of this priority
    position = None
    for idx, (name, weight) in enumerate(sorted_priorities):
        if name == priority_name:
            position = idx
            break
    
    if position is None:
        return "low priority"
    
    # Check for ties
    current_weight = weights[priority_name]
    ties = [name for name, w in weights.items() if w == current_weight and name != priority_name]
    
    ordinal = ["1st", "2nd", "3rd", "4th", "5th"]
    rank_str = ordinal[position] if position < len(ordinal) else f"{position + 1}th"
    
    if ties:
        return f"tied for {rank_str}"
    else:
        return rank_str

for key, default in {
    "listing_text": "",
    "filtered_df": pd.DataFrame(),
    "comparison_df": pd.DataFrame(),
    "parsed_df": pd.DataFrame(),
    "last_result": None,
    "show_instructions": True,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ===== SIDEBAR: TABLE OF CONTENTS =====
with st.sidebar:
    st.markdown("## 📑 Navigation")
    
    if not st.session_state.comparison_df.empty:
        st.markdown("### Sections")
        st.markdown("""
- [Parse Listing](#parse-listing)
- [Property Summary](#property-summary)
- [Lifestyle Priorities](#lifestyle-priorities)
- [Rankings](#rankings)
- [Full Table](#full-table)
        """)
        
        st.markdown("---")
        st.markdown("### Quick Stats")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Units", len(st.session_state.comparison_df))
        with col2:
            st.metric("Buildings", st.session_state.comparison_df["property"].nunique())
    else:
        st.markdown("👈 Paste an apartment listing to get started!")

# ===== MAIN CONTENT =====
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

st.markdown("### <a id='parse-listing'>1. Paste Listing Text</a>", unsafe_allow_html=True)

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
        st.session_state.show_instructions = True
        st.rerun()

if st.session_state.show_instructions:
    st.info("""
**How to use it:**
1. Open an Apartments.com listing
2. Press **Ctrl + A** to select all
3. Press **Ctrl + C** to copy
4. Paste the text below
5. Click **Analyze Apartment**
6. Save units and use the filters below to find your perfect home
    """)

listing_text = st.text_area(
    "Apartment listing text",
    key="listing_text",
    height=300,
    placeholder="Paste copied Apartments.com listing text here...",
)

analyze = st.button("✨ Analyze Apartment", use_container_width=True, type="primary")

if analyze:
    if st.session_state.listing_text.strip():
        result = parse_apartment_text(st.session_state.listing_text)
        st.session_state.last_result = result
        st.session_state.parsed_df = pd.DataFrame(result.get("units", []))
        st.session_state.show_instructions = False
        st.rerun()
    else:
        st.warning("Paste listing text first.")

if st.session_state.last_result:
    result = st.session_state.last_result
    building = result.get("building_nearby", {})

    st.markdown("### <a id='property-summary'>🏠 Property Summary</a>", unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)

    with m1:
        st.metric("Property", result.get("property_title") or "Unknown")
    with m2:
        st.metric("Units Parsed", result.get("unit_count", 0))
    with m3:
        metro_display = format_travel(building.get("metro_travel_mode"), building.get("metro_min"))
        st.metric("Nearest Metro", metro_display)
    with m4:
        hospital_display = format_travel(building.get("hospital_travel_mode"), building.get("hospital_min"))
        st.metric("Nearest Hospital", hospital_display)

    if result.get("address"):
        st.caption(f"📍 {result.get('address')}")

    if result.get("nearby_places"):
        with st.expander("View nearby building-level places"):
            st.dataframe(pd.DataFrame(result["nearby_places"]), use_container_width=True)

    if not st.session_state.parsed_df.empty:
        st.markdown("### 📋 Parsed Units")
        st.caption("Units extracted from the current building. Save them, then filter and rank below.")
        st.dataframe(st.session_state.parsed_df, use_container_width=True)

        if st.button("➕ Save Units to Comparison", use_container_width=True):
            st.session_state.comparison_df = pd.concat(
                [st.session_state.comparison_df, st.session_state.parsed_df],
                ignore_index=True
            )
            st.success("Units added!")
            st.rerun()
    else:
        st.warning("No unit rows were parsed from this listing.")

# ===== PHASE 1: LIFESTYLE PRIORITIES =====
st.markdown("---")
st.markdown("### <a id='lifestyle-priorities'>🎯 Set Your Lifestyle Priorities</a>", unsafe_allow_html=True)

if not st.session_state.comparison_df.empty:
    comp_df = st.session_state.comparison_df.copy()
    
    st.info("What matters most to you? Adjust these sliders (1=not important, 5=critical)")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        commute_priority = st.slider("🚇 Commute", 1, 5, 3, key="commute_slider")
        safety_priority = st.slider("🛡️ Safety", 1, 5, 3, key="safety_slider")
    
    with col2:
        nightlife_priority = st.slider("🍻 Nightlife", 1, 5, 2, key="nightlife_slider")
        budget_priority = st.slider("💰 Budget", 1, 5, 4, key="budget_slider")
    
    with col3:
        gym_priority = st.slider("💪 Gym/Fitness", 1, 5, 2, key="gym_slider")
    
    # ===== APPLY FILTERS =====
    st.markdown("### 🔎 Filter Your Apartments")
    
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
    
    apply_filters = st.button("✓ Apply Filters & Rank", use_container_width=True, type="primary")
    
    if apply_filters:
        filtered_comp_df = comp_df[
            (comp_df["price_num"] >= price_range[0]) &
            (comp_df["price_num"] <= price_range[1]) &
            (comp_df["sqft_num"] >= sqft_range[0]) &
            (comp_df["sqft_num"] <= sqft_range[1])
        ]
        
        filtered_comp_df = filter_units_by_request(filtered_comp_df, llm_request)
        
        st.session_state.filtered_df = filtered_comp_df
    
    # Use stored filtered_df if it exists
    filtered_comp_df = st.session_state.filtered_df if not st.session_state.filtered_df.empty else None
    
    if filtered_comp_df is not None and not filtered_comp_df.empty:
        st.markdown("### <a id='rankings'>🏆 Personalized Rankings</a>", unsafe_allow_html=True)
        st.caption("Ranked by your lifestyle priorities.")
        
        # ===== COMPUTE LIFESTYLE SCORES =====
        weights = get_priority_weights_from_sliders(
            commute_priority, safety_priority, nightlife_priority, budget_priority, gym_priority
        )
        
        scorer = LifestyleScorer(weights)
        ranked_df = scorer.score_apartments(filtered_comp_df.copy())
        
        # ===== DISPLAY TOP 3 WITH TAB-BASED UI =====
        st.markdown("#### 🥇 Top 3 Recommendations")
        top3 = ranked_df.head(3)
        
        for rank, (_, row) in enumerate(top3.iterrows(), start=1):
            unit_id = row.get("unit", f"Unit{rank}")
            building_name = row.get("property", "Unknown Building")
            
            # Create tabs for each apartment
            tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "🏠 Amenities", "💡 Tradeoffs", "⚠️ Concerns"])
            
            # Extract component scores
            component_scores = {
                "commute": row.get("commute_score", 0),
                "safety": row.get("safety_score", 0),
                "nightlife": row.get("nightlife_score", 0),
                "budget": row.get("budget_score", 0),
                "gym": row.get("gym_score", 0),
            }
            
            # TAB 1: OVERVIEW
            with tab1:
                st.success(f"**Rank #{rank}: {building_name} · Unit {unit_id}**")
                
                col_a, col_b, col_c, col_d = st.columns(4)
                col_a.metric("Price", f"${int(row.get('price_num', 0)):,}/mo")
                col_b.metric("Sq Ft", f"{int(row.get('sqft_num', 0))}")
                col_c.metric("Beds", row.get("beds", "—"))
                col_d.metric("Baths", row.get("baths", "—"))
                
                st.markdown(f"**Lifestyle Score: {row.get('lifestyle_score', 0):.0f}/100**")
                
                # Generate explanation with priority ranks
                explanation = generate_lifestyle_explanation(
                    rank, row, component_scores, weights, ranked_df,
                    priority_rank_fn=lambda name: get_priority_rank(name, weights)
                )
                st.markdown(explanation)
            
            # TAB 2: AMENITIES
            with tab2:
                st.markdown("**Building Amenities:**")
                amenities_text = generate_amenities_list(row)
                st.markdown(amenities_text)
                
                # Location info
                st.markdown("**Location Info:**")
                loc_col1, loc_col2 = st.columns(2)
                with loc_col1:
                    st.write(f"🚇 **Metro:** {row.get('metro_min', '—')} min walk")
                    st.write(f"🏥 **Hospital:** {row.get('hospital_min', '—')} min")
                with loc_col2:
                    walk_score = row.get("walk_score", "N/A")
                    st.write(f"🚶 **Walk Score:** {walk_score}")
            
            # TAB 3: TRADEOFFS
            with tab3:
                if rank > 1:
                    tradeoff = TradeoffAnalyzer(ranked_df)
                    tradeoff_text = tradeoff.generate_tradeoff_explanation(rank - 2, rank - 1)
                    st.markdown(tradeoff_text)
                else:
                    st.info("This is your top recommendation!")
            
            # TAB 4: CONCERNS
            with tab4:
                regret_analyzer = RegretAnalyzer(ranked_df, weights)
                analysis = regret_analyzer.analyze_apartment(rank - 1)
                
                if analysis.get('concerns'):
                    st.write(f"**Regret Risk: {analysis['regret_risk']:.0f}/100**")
                    st.write(f"{analysis['recommendation']}")
                    
                    st.markdown("**Potential Issues:**")
                    for concern in analysis['concerns']:
                        st.warning(f"{concern['icon']} **{concern['title']}**\n\n{concern['message']}")
                else:
                    st.success("✅ No major concerns!")
            
            st.divider()
        
        # ===== FULL RANKED TABLE =====
        st.markdown("### <a id='full-table'>📊 Full Ranking Table</a>", unsafe_allow_html=True)
        display_cols = [
            "property",
            "unit",
            "price",
            "beds",
            "baths",
            "sqft",
            "metro_min",
            "walk_score",
            "commute_score",
            "budget_score",
            "safety_score",
            "gym_score",
            "lifestyle_score",
        ]
        
        display_cols = [col for col in display_cols if col in ranked_df.columns]
        clean_ranked_df = ranked_df[display_cols].copy()
        
        # Round score columns
        for col in ["commute_score", "budget_score", "safety_score", "gym_score", "lifestyle_score"]:
            if col in clean_ranked_df.columns:
                clean_ranked_df[col] = clean_ranked_df[col].round(1)
        
        st.dataframe(clean_ranked_df, use_container_width=True)
    
    elif apply_filters:
        st.warning("No apartments match your filters. Try adjusting your preferences.")

else:
    st.info("👈 Add units to compare first by pasting an apartment listing above.")
