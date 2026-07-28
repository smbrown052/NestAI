"""
Regret Analyzer: "Would I Regret This Apartment?"
Identifies potential pain points and lifestyle mismatches grounded in actual property data.
"""

import pandas as pd
from typing import Dict, List, Optional


class RegretAnalyzer:
    """
    Analyzes apartments to identify potential regrets and lifestyle mismatches.
    Uses actual property data (prices, sqft, commute) to surface concrete concerns.
    """

    def __init__(self, ranked_df: pd.DataFrame, user_weights: Dict[str, float] = None):
        """Initialize with ranked apartments and user priorities."""
        self.ranked_df = ranked_df
        self.user_weights = user_weights or {}
        # Pre-compute price stats per bedroom count for meaningful comparisons
        self._price_stats: Dict = self._compute_price_stats()

    def _compute_price_stats(self) -> Dict:
        """Compute median/mean price per bedroom count across all ranked units."""
        stats: Dict = {}
        if self.ranked_df.empty or "price_num" not in self.ranked_df.columns:
            return stats
        for beds, group in self.ranked_df.groupby("beds_num", dropna=True):
            prices = group["price_num"].dropna()
            if len(prices) >= 1:
                stats[beds] = {
                    "median": round(prices.median()),
                    "mean": round(prices.mean()),
                    "min": round(prices.min()),
                    "max": round(prices.max()),
                    "count": len(prices),
                }
        return stats

    def analyze_apartment(self, apt_rank: int) -> Dict:
        """
        Deep-analyze an apartment for potential regrets.
        Returns a dict with concerns and severity levels.
        """
        if apt_rank >= len(self.ranked_df):
            return {"error": "Invalid apartment rank"}

        apt = self.ranked_df.iloc[apt_rank]
        concerns: List[Dict] = []
        severity_scores: List[float] = []

        for checker in (
            self._check_commute_regret,
            self._check_budget_regret,
            self._check_location_regret,
        ):
            concern = checker(apt)
            if concern:
                concerns.append(concern)
                severity_scores.append(concern["severity"])

        amenity_concerns = self._check_amenity_mismatch(apt)
        concerns.extend(amenity_concerns)
        severity_scores.extend(c["severity"] for c in amenity_concerns)

        regret_risk = max(severity_scores) if severity_scores else 0

        return {
            "apartment": apt.get("unit", "Unknown"),
            "rank": apt_rank + 1,
            "regret_risk": regret_risk,
            "concerns": concerns,
            "recommendation": self._generate_recommendation(concerns, regret_risk),
        }

    def _check_commute_regret(self, apt: pd.Series) -> Optional[Dict]:
        """Flag long or unusually slow commutes relative to other units."""
        commute_min = apt.get("commute_transit_min") or apt.get("commute_driving_min")
        metro_min = apt.get("metro_min")

        # Prefer actual commute over metro walk time
        best_min = None
        for val in (commute_min, metro_min):
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                try:
                    best_min = int(val)
                    break
                except (ValueError, TypeError):
                    pass

        if best_min is None:
            return None

        # Compare against median commute of other units in the set
        commute_col = None
        for col in ("commute_transit_min", "commute_driving_min", "metro_min"):
            if col in self.ranked_df.columns:
                vals = self.ranked_df[col].dropna()
                if len(vals) > 1:
                    commute_col = col
                    break

        peer_median: Optional[float] = None
        if commute_col:
            peer_median = self.ranked_df[commute_col].dropna().median()

        if best_min >= 45:
            extra = f" — {best_min - int(peer_median)} min longer than the median option" if peer_median and best_min > peer_median else ""
            return {
                "type": "commute",
                "title": "Long Daily Commute",
                "message": (
                    f"At {best_min} min each way, that's roughly "
                    f"{best_min * 2 * 22:,} hours per year commuting{extra}. "
                    "Over time this erodes work-life balance more than most renters expect."
                ),
                "severity": min(85, (best_min / 60) * 100),
                "icon": "⏱️",
            }

        if peer_median and best_min >= 30 and best_min >= peer_median * 1.4:
            return {
                "type": "commute",
                "title": "Commute Longer Than Your Other Options",
                "message": (
                    f"This unit's {best_min}-min commute is notably longer than the "
                    f"{int(peer_median)}-min median across your saved apartments."
                ),
                "severity": 50,
                "icon": "⏱️",
            }

        return None

    def _check_budget_regret(self, apt: pd.Series) -> Optional[Dict]:
        """Flag units that are materially above the median for their bedroom count."""
        price = apt.get("price_num")
        if price is None or (isinstance(price, float) and pd.isna(price)):
            return None

        price = float(price)
        beds = apt.get("beds_num")
        stats = self._price_stats.get(beds) if beds is not None else None

        if stats and stats["count"] >= 2:
            median_price = stats["median"]
            pct_above = (price - median_price) / median_price * 100 if median_price else 0

            if pct_above >= 20:
                return {
                    "type": "budget",
                    "title": "Priced Well Above Comparable Units",
                    "message": (
                        f"At ${price:,.0f}/mo this unit is ${price - median_price:,.0f} "
                        f"({pct_above:.0f}%) above the ${median_price:,}/mo median for "
                        f"{'studio' if beds == 0 else f'{int(beds)}-bed'} units in your search. "
                        "Make sure the premium is justified by location or amenities."
                    ),
                    "severity": min(75, 40 + pct_above * 0.8),
                    "icon": "💸",
                }

        # Fallback: absolute price feels high with low budget score
        budget_score = apt.get("lifestyle_budget_score", 50)
        if budget_score is not None and float(budget_score) < 35:
            return {
                "type": "budget",
                "title": "Low Budget Score",
                "message": (
                    f"At ${price:,.0f}/mo the budget score is low relative to your priorities. "
                    "Consider whether the value-to-cost ratio justifies the spend."
                ),
                "severity": 55,
                "icon": "💸",
            }

        return None

    def _check_location_regret(self, apt: pd.Series) -> Optional[Dict]:
        """Flag car-dependent, isolated locations using actual walk score data."""
        walk_score = apt.get("official_walk_score")
        if walk_score is None or (isinstance(walk_score, float) and pd.isna(walk_score)):
            walk_score = apt.get("walk_score")
        if walk_score is None or (isinstance(walk_score, float) and pd.isna(walk_score)):
            return None

        walk_score = float(walk_score)
        nearby_restaurants = apt.get("restaurants_count") or apt.get("nearby_restaurants") or 0

        if walk_score < 40:
            car_note = " and few walkable restaurants" if nearby_restaurants < 5 else ""
            return {
                "type": "location",
                "title": "Car-Dependent Neighborhood",
                "message": (
                    f"Walk Score {int(walk_score)}/100 indicates this area is car-dependent"
                    f"{car_note}. Daily errands will require driving, which adds hidden time and cost."
                ),
                "severity": 65,
                "icon": "🏜️",
            }

        return None

    def _check_amenity_mismatch(self, apt: pd.Series) -> List[Dict]:
        """
        Flag missing amenities the user explicitly values.
        Only fires when BOTH user priority is high AND the amenity is absent.
        """
        concerns: List[Dict] = []
        gym_priority = float(self.user_weights.get("gym", 0))
        has_gym = bool(apt.get("has_gym", False))
        has_fitness = bool(apt.get("has_fitness", False))

        if gym_priority > 0.35 and not has_gym and not has_fitness:
            concerns.append({
                "type": "amenity",
                "title": "No On-Site Fitness Facility",
                "message": (
                    "Gym is a high priority for you, but this building has no in-unit gym "
                    "or fitness center. You'll need a gym membership, which adds $30–$80/mo."
                ),
                "severity": 55,
                "icon": "💪",
            })

        return concerns

    def _generate_recommendation(self, concerns: List[Dict], regret_risk: float) -> str:
        if regret_risk >= 70:
            return "⚠️ High risk of regret — consider other options before committing."
        if regret_risk >= 50:
            return "⚡ Moderate concerns — review the points below before deciding."
        return "✅ Looks solid. No major red flags based on the available data."

    def get_all_concerns(self) -> List[Dict]:
        """Analyze top 5 apartments and surface concerns for each."""
        return [
            self.analyze_apartment(rank)
            for rank in range(min(5, len(self.ranked_df)))
            if "concerns" in self.analyze_apartment(rank)
        ]

    def generate_warning_report(self) -> str:
        """Generate a report highlighting apartments to avoid."""
        report = "🚨 **Potential Regret Warnings**\n\n"
        has_warnings = False

        for apt_analysis in self.get_all_concerns():
            if apt_analysis.get("regret_risk", 0) >= 50:
                has_warnings = True
                report += (
                    f"**Unit {apt_analysis['apartment']} (Rank #{apt_analysis['rank']})** — "
                    f"Risk Score: {apt_analysis['regret_risk']:.0f}/100\n"
                )
                for concern in apt_analysis.get("concerns", []):
                    report += f"  {concern['icon']} {concern['title']}\n"
                report += f"  → {apt_analysis['recommendation']}\n\n"

        if not has_warnings:
            report = "✅ **No Major Red Flags** — Your top recommendations look solid!"

        return report
