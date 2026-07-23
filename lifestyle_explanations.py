"""
Generate human-readable explanations for lifestyle scores.
"""

from typing import Dict, Callable
import pandas as pd


def generate_lifestyle_explanation(
    rank: int,
    row: pd.Series,
    scores: Dict[str, float],
    weights: Dict[str, float],
    all_apartments: pd.DataFrame = None,
    priority_rank_fn: Callable = None
) -> str:
    """
    Generate a personalized explanation for why this apartment scores well.
    
    Example:
    "Apartment A scored 92 because it saves 18 minutes of commuting while 
    only costing $75/month more. Your commute is your 1st priority, 
    and this location is 8 min from the metro."
    """
    
    unit = row.get("unit", "Unknown")
    price = int(row.get("price_num", 0))
    sqft = int(row.get("sqft_num", 0))
    beds = row.get("beds", "—")
    baths = row.get("baths", "—")
    lifestyle_score = row.get("lifestyle_score", 0)
    
    # Find top 2 scoring factors
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_factors = sorted_scores[:2]
    
    explanation_parts = []
    
    # Header
    explanation_parts.append(
        f"**Unit {unit} · {beds}B/{baths}B · ${price:,} · {sqft} sqft**"
    )
    explanation_parts.append(f"\n**Lifestyle Score: {lifestyle_score:.0f}/100**\n")
    
    # Primary factor
    factor1_name, factor1_score = top_factors[0]
    
    # Get priority rank if function provided
    priority_rank = ""
    if priority_rank_fn:
        priority_rank = priority_rank_fn(factor1_name)
        explanation_parts.append(f"✨ **{factor1_name.title()}** (your {priority_rank} priority):\n")
    else:
        factor1_weight = weights.get(factor1_name, 0)
        explanation_parts.append(f"✨ **{factor1_name.title()}** ({factor1_weight*100:.0f}% of your priorities):\n")
    
    if factor1_name == "commute":
        commute_min = row.get("commute_transit_min")
        if pd.isna(commute_min):
            commute_min = row.get("metro_min")
        explanation_parts.append(f"   • {factor1_score:.0f}/100: About {commute_min} min to transit")
    elif factor1_name == "budget":
        price_per_sqft = price / sqft if sqft > 0 else 0
        explanation_parts.append(f"   • {factor1_score:.0f}/100: Excellent value at ${price_per_sqft:.2f}/sqft")
    elif factor1_name == "safety":
        walk_score = row.get("official_walk_score", row.get("walk_score"))
        explanation_parts.append(f"   • {factor1_score:.0f}/100: Highly walkable area (Walk Score {walk_score})")
    elif factor1_name == "nightlife":
        nearby_venues = row.get("restaurants_count", row.get("nearby_restaurants", 0)) + row.get("nearby_bars", 0)
        explanation_parts.append(f"   • {factor1_score:.0f}/100: {nearby_venues}+ entertainment venues nearby")
    elif factor1_name == "gym":
        has_gym = row.get("has_gym", False)
        explanation_parts.append(f"   • {factor1_score:.0f}/100: {'In-unit gym' if has_gym else 'Gyms nearby'}")
    
    # Secondary factor
    if len(top_factors) > 1:
        factor2_name, factor2_score = top_factors[1]
        
        if priority_rank_fn:
            priority_rank_2 = priority_rank_fn(factor2_name)
            explanation_parts.append(f"\n✨ **{factor2_name.title()}** (your {priority_rank_2} priority):\n")
        else:
            factor2_weight = weights.get(factor2_name, 0)
            explanation_parts.append(f"\n✨ **{factor2_name.title()}** ({factor2_weight*100:.0f}% of your priorities):\n")
        
        if factor2_name == "commute":
            commute_min = row.get("commute_transit_min")
            if pd.isna(commute_min):
                commute_min = row.get("metro_min")
            explanation_parts.append(f"   • {factor2_score:.0f}/100: {commute_min} min to transit")
        elif factor2_name == "budget":
            price_per_sqft = price / sqft if sqft > 0 else 0
            explanation_parts.append(f"   • {factor2_score:.0f}/100: ${price_per_sqft:.2f}/sqft")
        elif factor2_name == "safety":
            explanation_parts.append(f"   • {factor2_score:.0f}/100: Safe, walkable neighborhood")
        elif factor2_name == "nightlife":
            explanation_parts.append(f"   • {factor2_score:.0f}/100: Great dining and entertainment scene")
        elif factor2_name == "gym":
            explanation_parts.append(f"   • {factor2_score:.0f}/100: Fitness options available")
    
    return "\n".join(explanation_parts)


def generate_amenities_list(row: pd.Series) -> str:
    """
    Generate a clean, readable amenities list for an apartment.
    """
    amenities = []
    
    if row.get("has_laundry"):
        amenities.append("✓ In-unit Washer/Dryer")
    if row.get("has_gym"):
        amenities.append("✓ In-unit Gym")
    if row.get("has_fitness"):
        amenities.append("✓ Fitness Center")
    if row.get("has_pool"):
        amenities.append("✓ Pool")
    if row.get("has_parking"):
        amenities.append("✓ Parking")
    if row.get("has_balcony"):
        amenities.append("✓ Balcony")
    if row.get("has_patio"):
        amenities.append("✓ Patio")
    if row.get("has_security"):
        amenities.append("✓ 24hr Security")
    if row.get("has_concierge"):
        amenities.append("✓ Concierge")
    
    if not amenities:
        return "No major amenities listed"
    
    return "\n".join(amenities)


def compare_two_apartments(
    apt1: pd.Series,
    apt2: pd.Series,
    scores1: Dict[str, float],
    scores2: Dict[str, float],
    weights: Dict[str, float]
) -> str:
    """
    Compare two apartments side-by-side.
    """
    unit1 = apt1.get("unit", "A")
    unit2 = apt2.get("unit", "B")
    score1 = apt1.get("lifestyle_score", 0)
    score2 = apt2.get("lifestyle_score", 0)
    
    comparison = f"**Unit {unit1} ({score1:.0f}) vs Unit {unit2} ({score2:.0f})**\n\n"
    
    # Find biggest differentiators
    for factor in ["commute", "budget", "safety", "nightlife", "gym"]:
        s1 = scores1.get(factor, 0)
        s2 = scores2.get(factor, 0)
        diff = abs(s1 - s2)
        
        if diff > 15:
            if s1 > s2:
                comparison += f"✅ Unit {unit1} wins on **{factor.title()}** ({s1:.0f} vs {s2:.0f})\n"
            else:
                comparison += f"✅ Unit {unit2} wins on **{factor.title()}** ({s2:.0f} vs {s1:.0f})\n"
    
    return comparison
