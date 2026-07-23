"""
Regret Analyzer: "Would I Regret This Apartment?"
Identifies potential pain points and lifestyle mismatches.
"""

import pandas as pd
from typing import Dict, List, Tuple


class RegretAnalyzer:
    """
    Analyzes apartments to identify potential regrets and lifestyle mismatches.
    Uses red flags across multiple dimensions to surface concerns.
    """
    
    # Threshold scores that trigger concerns
    COMMUTE_REGRET_THRESHOLD = 35  # High commute score triggers concern
    BUDGET_CONCERN_THRESHOLD = 40  # Low budget score triggers concern
    WALKABILITY_THRESHOLD = 45     # Low walk score in urban area
    
    def __init__(self, ranked_df: pd.DataFrame, user_weights: Dict[str, float] = None):
        """Initialize with ranked apartments and user priorities."""
        self.ranked_df = ranked_df
        self.user_weights = user_weights or {}
    
    def analyze_apartment(self, apt_rank: int) -> Dict:
        """
        Deep analyze an apartment for potential regrets.
        Returns a dict with concerns and severity levels.
        """
        if apt_rank >= len(self.ranked_df):
            return {"error": "Invalid apartment rank"}
        
        apt = self.ranked_df.iloc[apt_rank]
        concerns = []
        severity_scores = []
        
        # Check commute pain
        commute_concern = self._check_commute_regret(apt)
        if commute_concern:
            concerns.append(commute_concern)
            severity_scores.append(commute_concern["severity"])
        
        # Check budget pain
        budget_concern = self._check_budget_regret(apt)
        if budget_concern:
            concerns.append(budget_concern)
            severity_scores.append(budget_concern["severity"])
        
        # Check location pain
        location_concern = self._check_location_regret(apt)
        if location_concern:
            concerns.append(location_concern)
            severity_scores.append(location_concern["severity"])
        
        # Check amenity mismatches (only flag MISSING amenities user cares about)
        amenity_concerns = self._check_amenity_mismatch(apt)
        concerns.extend(amenity_concerns)
        severity_scores.extend([c["severity"] for c in amenity_concerns])
        
        # Calculate overall regret risk
        regret_risk = max(severity_scores) if severity_scores else 0
        
        return {
            "apartment": apt.get("unit", "Unknown"),
            "rank": apt_rank + 1,
            "regret_risk": regret_risk,  # 0-100 scale
            "concerns": concerns,
            "recommendation": self._generate_recommendation(concerns, regret_risk)
        }
    
    def _check_commute_regret(self, apt: pd.Series) -> Dict or None:
        """
        Analyze if commute will become a pain point over time.
        """
        metro_min = apt.get("metro_min")
        commute_score = apt.get("lifestyle_commute_score", 50)
        
        if pd.isna(metro_min):
            return None
        
        # Flag long commutes (40+ min) as potential regrets
        if metro_min >= 40:
            return {
                "type": "commute",
                "title": "Long Commute May Wear On You",
                "message": f"This apartment has a {metro_min} minute commute. After a few months, "
                          f"this could become a significant drain on your energy and free time.",
                "severity": min(80, (metro_min / 60) * 100),
                "icon": "⏱️"
            }
        
        if metro_min >= 25 and commute_score < 50:
            return {
                "type": "commute",
                "title": "Moderate Commute",
                "message": f"At {metro_min} minutes each way, you're looking at ~{metro_min * 2 * 22} "
                          f"hours per year commuting. That adds up.",
                "severity": 50,
                "icon": "⏱️"
            }
        
        return None
    
    def _check_budget_regret(self, apt: pd.Series) -> Dict or None:
        """
        Analyze if budget will create financial stress.
        """
        price = apt.get("price_num", 0)
        budget_score = apt.get("lifestyle_budget_score", 50)
        
        # Check if price is high relative to apparent value
        if budget_score < self.BUDGET_CONCERN_THRESHOLD:
            return {
                "type": "budget",
                "title": "Tight on Value",
                "message": f"At ${price}/month, this apartment feels expensive relative to what you're getting. "
                          f"You might regret the spend after a few months.",
                "severity": min(75, 100 - budget_score),
                "icon": "💸"
            }
        
        return None
    
    def _check_location_regret(self, apt: pd.Series) -> Dict or None:
        """
        Analyze if location will become isolating or inconvenient.
        """
        walk_score = apt.get("official_walk_score")
        if pd.isna(walk_score):
            walk_score = apt.get("walk_score", 50)
        nearby_restaurants = apt.get("restaurants_count", apt.get("nearby_restaurants", 0))
        
        if walk_score < 40 and nearby_restaurants < 5:
            return {
                "type": "location",
                "title": "Isolated Location",
                "message": f"This area has limited walkability ({walk_score} Walk Score) and few nearby restaurants. "
                          f"You'll likely feel isolated or car-dependent.",
                "severity": 70,
                "icon": "🏜️"
            }
        
        return None
    
    def _check_amenity_mismatch(self, apt: pd.Series) -> List[Dict]:
        """
        Check if apartment is MISSING critical amenities the user values.
        Only flag when BOTH user cares AND apartment doesn't have it.
        """
        concerns = []
        
        # Check gym - only flag if user prioritizes gym AND apartment lacks it
        gym_priority = self.user_weights.get("gym", 0)
        has_gym = apt.get("has_gym", False)
        has_fitness = apt.get("has_fitness", False)
        nearby_gyms = apt.get("nearby_gyms", 0)
        
        if gym_priority > 0.3 and not has_gym and not has_fitness and nearby_gyms < 2:
            concerns.append({
                "type": "amenity",
                "title": "No Fitness Options",
                "message": f"You prioritize fitness, but this apartment lacks in-unit gym and few gyms nearby. "
                          f"This could limit your workout routine.",
                "severity": 60,
                "icon": "💪"
            })
        
        # Check laundry - only flag if apartment lacks it (don't flag if it HAS it!)
        has_laundry = apt.get("has_laundry", False)
        if not has_laundry:
            concerns.append({
                "type": "amenity",
                "title": "No In-Unit Laundry",
                "message": f"No in-unit laundry means trips to a laundromat. Over time, this becomes a real friction point.",
                "severity": 40,
                "icon": "🧺"
            })
        
        return concerns
    
    def _generate_recommendation(self, concerns: List[Dict], regret_risk: float) -> str:
        """
        Generate overall recommendation based on concerns.
        """
        if regret_risk >= 70:
            return "⚠️ High risk of regret. Consider other options."
        elif regret_risk >= 50:
            return "⚡ Moderate concerns. Worth a closer look at dealbreakers."
        else:
            return "✅ Looks solid. No major red flags."
    
    def get_all_concerns(self) -> List[Dict]:
        """
        Analyze top 5 apartments and surface concerns for each.
        """
        all_concerns = []
        
        for rank in range(min(5, len(self.ranked_df))):
            analysis = self.analyze_apartment(rank)
            if "concerns" in analysis:
                all_concerns.append(analysis)
        
        return all_concerns
    
    def generate_warning_report(self) -> str:
        """
        Generate a report highlighting apartments to avoid.
        """
        report = "🚨 **Potential Regret Warnings**\n\n"
        
        concerns = self.get_all_concerns()
        
        has_warnings = False
        for apt_analysis in concerns:
            if apt_analysis["regret_risk"] >= 50:
                has_warnings = True
                report += f"**Unit {apt_analysis['apartment']} (Rank #{apt_analysis['rank']})** - "
                report += f"Risk Score: {apt_analysis['regret_risk']:.0f}/100\n"
                
                for concern in apt_analysis["concerns"]:
                    report += f"  {concern['icon']} {concern['title']}\n"
                
                report += f"  → {apt_analysis['recommendation']}\n\n"
        
        if not has_warnings:
            report = "✅ **No Major Red Flags** - Your top recommendations look solid!"
        
        return report
