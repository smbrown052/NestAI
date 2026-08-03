"""
AI Tradeoff Assistant
Showcase the incremental value of upgrading to a better apartment.
"""

import pandas as pd
from typing import Dict, List, Tuple

from availability import availability_label, parse_availability_date


class TradeoffAnalyzer:
    """
    Compares adjacent ranked apartments and identifies key tradeoffs.
    Shows users what they gain/lose by choosing apartment B over apartment A.
    """
    
    def __init__(self, ranked_df: pd.DataFrame):
        """Initialize with a ranked DataFrame."""
        self.ranked_df = ranked_df

    @staticmethod
    def _label(row: pd.Series) -> str:
        prop = row.get("property", "Unknown Property")
        unit = row.get("unit", "N/A")
        return f"{prop} · Unit {unit}"

    @staticmethod
    def _to_number(value, default: float = 0.0) -> float:
        if value is None or pd.isna(value):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    
    def get_difference_metrics(self, apt1: pd.Series, apt2: pd.Series) -> Dict:
        """
        Calculate differences between two apartments.
        Returns a dict of gains/losses.
        """
        differences = {}
        
        # Price difference
        price1 = self._to_number(apt1.get("price_num", 0))
        price2 = self._to_number(apt2.get("price_num", 0))
        price_diff = price2 - price1
        differences["price_diff"] = price_diff
        
        # Sqft difference
        sqft1 = self._to_number(apt1.get("sqft_num", 0))
        sqft2 = self._to_number(apt2.get("sqft_num", 0))
        sqft_diff = sqft2 - sqft1
        differences["sqft_diff"] = sqft_diff
        
        # Commute difference
        commute1 = self._to_number(apt1.get("metro_min", 0))
        commute2 = self._to_number(apt2.get("metro_min", 0))
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
        differences["availability_1"] = availability_label(
            apt1.get("available_date") or apt1.get("availability")
        )
        differences["availability_2"] = availability_label(
            apt2.get("available_date") or apt2.get("availability")
        )
        
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
        
        label1 = self._label(apt1)
        label2 = self._label(apt2)

        explanation = (
            f"**Comparing {label1} (Rank #{apt1_rank + 1})**\n"
            f"**vs {label2} (Rank #{apt2_rank + 1})**\n\n"
        )
        
        price_diff = diffs["price_diff"]
        
        if price_diff > 0:
            explanation += f"💰 **{label2} costs ${abs(price_diff):,.0f}/month more and gives you:**\n\n"
        elif price_diff < 0:
            explanation += f"💰 **{label2} costs ${abs(price_diff):,.0f}/month less, but you trade off:**\n\n"
        else:
            explanation += f"💰 **At the same monthly price, the main differences are:**\n\n"
        
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

        availability_1 = parse_availability_date(diffs["availability_1"])
        availability_2 = parse_availability_date(diffs["availability_2"])
        if availability_1 and availability_2 and availability_1.date() != availability_2.date():
            if availability_2 < availability_1:
                gains.append(f"📅 available sooner ({diffs['availability_2']} vs {diffs['availability_1']})")
            else:
                gains.append(f"📅 available later ({diffs['availability_2']} vs {diffs['availability_1']})")
        elif diffs["availability_2"] != diffs["availability_1"]:
            gains.append(f"📅 availability: {diffs['availability_2']} vs {diffs['availability_1']}")
        
        # New amenities
        for amenity in diffs["new_amenities"]:
            gains.append(f"✨ {amenity}")
        
        # Lost amenities
        for amenity in diffs["lost_amenities"]:
            gains.append(f"❌ loses {amenity}")
        
        if not gains:
            explanation += "• Price, space, commute, and listing details are very similar.\n"
            return explanation

        for gain in gains:
            explanation += f"• {gain}\n"
        
        return explanation
    
    def explain_why_winner(self) -> str:
        """
        Explain why rank #1 beat rank #2, from the winner's perspective.
        """
        if len(self.ranked_df) < 2:
            return "Only one option saved — add another to see a comparison."

        winner = self.ranked_df.iloc[0]
        runner_up = self.ranked_df.iloc[1]

        winner_label = self._label(winner)
        runner_label = self._label(runner_up)

        explanation = (
            f"**Why {winner_label} (Rank #1) beat {runner_label} (Rank #2):**\n\n"
        )

        price_w = self._to_number(winner.get("price_num", 0))
        price_r = self._to_number(runner_up.get("price_num", 0))
        price_advantage = price_r - price_w  # positive = winner is cheaper

        sqft_w = self._to_number(winner.get("sqft_num", 0))
        sqft_r = self._to_number(runner_up.get("sqft_num", 0))
        sqft_advantage = sqft_w - sqft_r  # positive = winner has more space

        commute_w = self._to_number(winner.get("metro_min") or winner.get("commute_transit_min"), 999)
        commute_r = self._to_number(runner_up.get("metro_min") or runner_up.get("commute_transit_min"), 999)
        commute_advantage = commute_r - commute_w  # positive = winner has shorter commute

        advantages = []

        if price_advantage > 0:
            advantages.append(f"💰 ${price_advantage:,.0f}/mo less expensive")
        if sqft_advantage > 50:
            advantages.append(f"📐 {sqft_advantage:.0f} sq ft more space")
        if 0 < commute_advantage < 999:
            advantages.append(f"🚇 {commute_advantage:.0f} min shorter commute")

        winner_available = availability_label(winner.get("available_date") or winner.get("availability"))
        runner_available = availability_label(runner_up.get("available_date") or runner_up.get("availability"))
        winner_available_dt = parse_availability_date(winner_available)
        runner_available_dt = parse_availability_date(runner_available)
        if winner_available_dt and runner_available_dt and winner_available_dt.date() != runner_available_dt.date():
            if winner_available_dt < runner_available_dt:
                advantages.append(f"📅 available sooner ({winner_available} vs {runner_available})")
        elif winner_available != runner_available and winner_available != "Unknown":
            advantages.append(f"📅 clearer availability ({winner_available})")

        winner_amenities = self._extract_amenities(winner)
        runner_amenities = self._extract_amenities(runner_up)
        exclusive = [a for a in winner_amenities if a not in runner_amenities]
        for amenity in exclusive[:2]:
            advantages.append(f"✨ Has {amenity}")

        if not advantages:
            advantages = ["A better overall balance of price, commute, space, and listing details"]

        for adv in advantages:
            explanation += f"• {adv}\n"

        # Compromise: what winner gives up
        given_up = [a for a in runner_amenities if a not in winner_amenities]
        if given_up or price_advantage < 0:
            explanation += "\n**Key compromise:**\n"
            if price_advantage < 0:
                explanation += f"• Costs ${abs(price_advantage):,.0f}/mo more\n"
            for item in given_up[:2]:
                explanation += f"• No {item} (runner-up has it)\n"

        return explanation

    def compare_vs_best(self, apt_rank: int) -> str:
        """
        Compare any apartment vs the #1 ranked apartment.
        """
        if apt_rank == 0:
            return "This is already your top recommendation!"

        return self.generate_tradeoff_explanation(apt_rank, 0)
