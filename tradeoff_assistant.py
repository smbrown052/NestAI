"""
AI Tradeoff Assistant
Showcase the incremental value of upgrading to a better apartment.
"""

import pandas as pd
from typing import Dict, List, Tuple


class TradeoffAnalyzer:
    """
    Compares adjacent ranked apartments and identifies key tradeoffs.
    Shows users what they gain/lose by choosing apartment B over apartment A.
    """
    
    def __init__(self, ranked_df: pd.DataFrame):
        """Initialize with a ranked DataFrame."""
        self.ranked_df = ranked_df
    
    def get_difference_metrics(self, apt1: pd.Series, apt2: pd.Series) -> Dict:
        """
        Calculate differences between two apartments.
        Returns a dict of gains/losses.
        """
        differences = {}
        
        # Price difference
        price1 = apt1.get("price_num", 0)
        price2 = apt2.get("price_num", 0)
        price_diff = price2 - price1
        differences["price_diff"] = price_diff
        
        # Sqft difference
        sqft1 = apt1.get("sqft_num", 0)
        sqft2 = apt2.get("sqft_num", 0)
        sqft_diff = sqft2 - sqft1
        differences["sqft_diff"] = sqft_diff
        
        # Commute difference
        commute1 = apt1.get("metro_min", 0)
        commute2 = apt2.get("metro_min", 0)
        commute_diff = commute1 - commute2  # Negative = better
        differences["commute_diff"] = commute_diff
        
        # Amenity differences
        differences["apt1_amenities"] = self._extract_amenities(apt1)
        differences["apt2_amenities"] = self._extract_amenities(apt2)
        differences["new_amenities"] = [
            a for a in differences["apt2_amenities"] 
            if a not in differences["apt1_amenities"]
        ]
        differences["lost_amenities"] = [
            a for a in differences["apt1_amenities"] 
            if a not in differences["apt2_amenities"]
        ]
        
        return differences
    
    def _extract_amenities(self, row: pd.Series) -> List[str]:
        """Extract amenity list from apartment row."""
        amenities = []
        
        if row.get("has_gym"):
            amenities.append("in-unit gym")
        if row.get("has_fitness"):
            amenities.append("fitness center")
        if row.get("has_laundry"):
            amenities.append("in-unit laundry")
        if row.get("has_parking"):
            amenities.append("parking")
        if row.get("has_balcony"):
            amenities.append("balcony")
        if row.get("has_den"):
            amenities.append("den")
        if row.get("has_pool"):
            amenities.append("pool")
        
        return amenities
    
    def generate_tradeoff_explanation(self, apt1_rank: int, apt2_rank: int) -> str:
        """
        Generate a comparison between ranked apartments.
        
        Example output:
        "If you spend $120 more/month, you'll gain:
        - 240 sq ft
        - in-unit laundry
        - 12 minutes less commuting
        - garage parking"
        """
        
        if apt1_rank >= len(self.ranked_df) or apt2_rank >= len(self.ranked_df):
            return "Invalid apartment ranks."
        
        apt1 = self.ranked_df.iloc[apt1_rank]
        apt2 = self.ranked_df.iloc[apt2_rank]
        
        diffs = self.get_difference_metrics(apt1, apt2)
        
        unit1 = apt1.get("unit", "A")
        unit2 = apt2.get("unit", "B")
        
        explanation = f"**Comparing Unit {unit1} (Rank #{apt1_rank + 1}) vs Unit {unit2} (Rank #{apt2_rank + 1})**\n\n"
        
        price_diff = diffs["price_diff"]
        
        if price_diff > 0:
            explanation += f"💰 **If you spend ${abs(price_diff)}/month more**, you'll gain:\n\n"
        elif price_diff < 0:
            explanation += f"💰 **If you spend ${abs(price_diff)}/month less**, you'll give up:\n\n"
        else:
            explanation += f"💰 **Same price**, but you'll gain:\n\n"
        
        gains = []
        
        # Space gain
        sqft_diff = diffs["sqft_diff"]
        if sqft_diff > 0:
            gains.append(f"📐 {abs(sqft_diff):.0f} sq ft more space")
        elif sqft_diff < 0:
            gains.append(f"📐 {abs(sqft_diff):.0f} sq ft less space")
        
        # Commute improvement
        commute_diff = diffs["commute_diff"]
        if commute_diff > 0:
            gains.append(f"🚇 {abs(commute_diff):.0f} minutes less commuting")
        elif commute_diff < 0:
            gains.append(f"🚇 {abs(commute_diff):.0f} minutes more commuting")
        
        # New amenities
        for amenity in diffs["new_amenities"]:
            gains.append(f"✨ {amenity}")
        
        # Lost amenities
        for amenity in diffs["lost_amenities"]:
            gains.append(f"❌ loses {amenity}")
        
        for gain in gains:
            explanation += f"• {gain}\n"
        
        return explanation
    
    def compare_vs_best(self, apt_rank: int) -> str:
        """
        Compare any apartment vs the #1 ranked apartment.
        """
        if apt_rank == 0:
            return "This is already your top recommendation!"
        
        return self.generate_tradeoff_explanation(apt_rank, 0)
