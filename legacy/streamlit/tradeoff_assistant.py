"""
AI Tradeoff Assistant
Showcase the incremental value of upgrading to a better apartment.
"""

import pandas as pd
from typing import Dict, List, Tuple
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from shared.decision import comparison

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
        
        verified = comparison(apt1.to_dict(), apt2.to_dict())
        differences["price_diff"] = verified["deltas"]["price"]
        differences["sqft_diff"] = verified["deltas"]["space"]
        differences["comparison"] = verified
        
        # Commute difference
        commute1 = self._to_number(apt1.get("commute_minutes"), None)
        commute2 = self._to_number(apt2.get("commute_minutes"), None)
        differences["commute_diff"] = None if commute1 is None or commute2 is None else commute1 - commute2
        
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
        
        if row.get("has_gym") is True:
            amenities.append("building gym")
        if row.get("has_fitness") is True:
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
        
        if min(apt1_rank, apt2_rank) < 0 or apt1_rank >= len(self.ranked_df) or apt2_rank >= len(self.ranked_df):
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
        
        if price_diff is None:
            explanation += "**Rent comparison unavailable.**\n\n"
        elif price_diff > 0:
            explanation += f"💰 **{label2} costs ${abs(price_diff):,.0f}/month more and gives you:**\n\n"
        elif price_diff < 0:
            explanation += f"💰 **{label2} costs ${abs(price_diff):,.0f}/month less, but you trade off:**\n\n"
        else:
            explanation += f"💰 **At the same monthly price, the main differences are:**\n\n"
        
        gains = []
        
        # Space gain
        sqft_diff = diffs["sqft_diff"]
        if sqft_diff is not None and sqft_diff > 0:
            gains.append(f"📐 {abs(sqft_diff):.0f} sq ft more space")
        elif sqft_diff is not None and sqft_diff < 0:
            gains.append(f"📐 {abs(sqft_diff):.0f} sq ft less space")
        
        # Commute improvement
        commute_diff = diffs["commute_diff"]
        if commute_diff is not None and commute_diff > 0:
            gains.append(f"🚇 {abs(commute_diff):.0f} minutes less commuting")
        elif commute_diff is not None and commute_diff < 0:
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

        verified = comparison(winner.to_dict(), runner_up.to_dict())
        advantages = list(verified["advantages"])

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
            advantages = ["No individual factual advantage identified; ordering follows your priorities and the stable tie-breaker"]

        for adv in advantages:
            explanation += f"• {adv}\n"

        # Compromise: what winner gives up
        explanation += "\n**Key compromise:**\n"
        for item in verified["compromises"] or [verified["compromise_summary"]]:
            explanation += f"• {item}\n"
        for item in verified["unknowns"]:
            explanation += f"• {item}\n"

        return explanation

    def compare_vs_best(self, apt_rank: int) -> str:
        """
        Compare any apartment vs the #1 ranked apartment.
        """
        if apt_rank == 0:
            return "This is already your top recommendation!"

        return self.generate_tradeoff_explanation(apt_rank, 0)
