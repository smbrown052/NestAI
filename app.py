import os
import streamlit as st
import pandas as pd
from text_parser import parse_apartment_text, filter_units_by_request
from lifestyle_scoring import LifestyleScorer, get_priority_weights_from_sliders
from lifestyle_explanations import generate_lifestyle_explanation
from tradeoff_assistant import TradeoffAnalyzer
from regret_analyzer import RegretAnalyzer

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
- Ranks apartments based on your personal lifestyle priorities
- Shows what you gain/lose when upgrading apartments
- Warns about apartments you might regret
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

# ===== PHASE 1: LIFESTYLE PRIORITIES =====
st.markdown("---")
st.markdown("### 🎯 Set Your Lifestyle Priorities")

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
    st.markdown("### 🔎 Filter & Rank Your Apartments")
    
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
    
    st.markdown("### 🏆 Personalized Recommendations")
    st.caption("Ranked by your lifestyle priorities.")
    
    if filtered_comp_df.empty:
        st.warning("No saved units match your filters.")
    else:
        # ===== COMPUTE LIFESTYLE SCORES =====
        weights = get_priority_weights_from_sliders(
            commute_priority, safety_priority, nightlife_priority, budget_priority, gym_priority
        )
        
        scorer = LifestyleScorer(weights)
        ranked_df = scorer.score_apartments(filtered_comp_df.copy())
        
        # ===== DISPLAY TOP 3 WITH EXPLANATIONS =====
        st.markdown("#### 🥇 Top 3 Recommendations")
        top3 = ranked_df.head(3)
        
        for rank, (_, row) in enumerate(top3.iterrows(), start=1):
            # Extract component scores
            component_scores = {
                "commute": row.get("commute_score", 0),
                "safety": row.get("safety_score", 0),
                "nightlife": row.get("nightlife_score", 0),
                "budget": row.get("budget_score", 0),
                "gym": row.get("gym_score", 0),
            }
            
            # Generate lifestyle explanation
            explanation = generate_lifestyle_explanation(
                rank, row, component_scores, weights, ranked_df
            )
            
            st.success(explanation)
            
            # ===== PHASE 1B: TRADEOFF ASSISTANT =====
            if rank > 1:
                with st.expander(f"💡 Compare to Rank #{rank - 1}"):
                    tradeoff = TradeoffAnalyzer(ranked_df)
                    tradeoff_text = tradeoff.generate_tradeoff_explanation(rank - 2, rank - 1)
                    st.markdown(tradeoff_text)
            
            st.divider()
        
        # ===== PHASE 1C: REGRET ANALYZER =====
        st.markdown("#### 🚨 Potential Regret Warnings")
        
        regret_analyzer = RegretAnalyzer(ranked_df, weights)
        warning_report = regret_analyzer.generate_warning_report()
        
        if "High risk" in warning_report or "Moderate concerns" in warning_report:
            st.warning(warning_report)
        else:
            st.info("✅ No major red flags in your top recommendations!")
        
        # ===== DETAILED ANALYSIS PER APARTMENT =====
        st.markdown("#### 🔍 Detailed Analysis by Apartment")
        
        for rank in range(min(3, len(ranked_df))):
            apt = ranked_df.iloc[rank]
            analysis = regret_analyzer.analyze_apartment(rank)
            
            with st.expander(f"Unit {apt.get('unit', 'Unknown')} - Rank #{rank + 1}", expanded=False):
                st.write(f"**Regret Risk Score: {analysis['regret_risk']:.0f}/100**")
                st.write(analysis['recommendation'])
                
                if analysis['concerns']:
                    st.write("**Concerns:**")
                    for concern in analysis['concerns']:
                        st.write(f"{concern['icon']} **{concern['title']}**")
                        st.write(f"_{concern['message']}_")
        
        # ===== FULL RANKED TABLE =====
        st.markdown("### 📊 Full Ranking")
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

else:
    st.info("Add units to compare first.")
