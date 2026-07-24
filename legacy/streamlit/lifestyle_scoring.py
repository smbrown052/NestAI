"""
Lifestyle Score Engine
Reweights apartment scores based on user priorities across key life domains.
"""

import pandas as pd
from typing import Dict, Tuple, Any


class LifestyleScorer:
    """
    Computes personalized apartment scores based on user-defined lifestyle priorities.
    
    Priorities:
    - Commute: Metro proximity and travel time
    - Safety: Building amenities and walkability
    - Nightlife: Nearby restaurants, bars, entertainment
    - Budget: Rent and value per sqft
    - Gym: Fitness amenities and nearby gyms
    """
    
    # Default priority weights (used when user disables every optional priority)
    DEFAULT_WEIGHTS = {
        "commute": 0.20,
        "safety": 0.20,
        "nightlife": 0.20,
        "budget": 0.20,
        "gym": 0.20,
    }
    
    def __init__(self, user_weights: Dict[str, float] = None, user_preferences: Dict[str, Any] = None):
        """Initialize scorer with user priority weights."""
        self.preferences = user_preferences or {}
        self.weights = user_weights or self.DEFAULT_WEIGHTS

        # Normalize only enabled weights; if all disabled, use defaults.
        positive_weights = {
            k: float(v) for k, v in self.weights.items()
            if v is not None and float(v) > 0
        }
        if not positive_weights:
            positive_weights = self.DEFAULT_WEIGHTS.copy()
        weight_sum = sum(positive_weights.values())
        self.weights = {k: v / weight_sum for k, v in positive_weights.items()}
    
    def compute_commute_score(self, row: pd.Series) -> float:
        """
        Score based on commute time when available, otherwise metro proximity.
        - Perfect: ≤5 min walk
        - Great: 5-10 min
        - Good: 10-20 min
        - Poor: >20 min
        """
        commute_min = row.get("commute_transit_min")
        if pd.isna(commute_min):
            commute_min = row.get("metro_min")

        if pd.isna(commute_min):
            return 50.0  # Neutral if unknown

        if commute_min <= 5:
            return 100.0
        elif commute_min <= 10:
            return 85.0
        elif commute_min <= 20:
            return 60.0
        else:
            return 30.0
    
    def compute_safety_score(self, row: pd.Series) -> float:
        """
        Score based on walkability and building amenities.
        - Walk Score >70 = safer, more developed area
        - Presence of 24h security, concierge = +10
        """
        walk_score = row.get("official_walk_score")
        if pd.isna(walk_score):
            walk_score = row.get("walk_score")
        has_security = row.get("has_security", False)
        has_concierge = row.get("has_concierge", False)
        
        score = 50.0  # Baseline
        
        if pd.notna(walk_score):
            score = walk_score
        
        if has_security:
            score += 10
        if has_concierge:
            score += 5
        
        return min(score, 100.0)
    
    def compute_nightlife_score(self, row: pd.Series) -> float:
        """
        Score based on proximity to entertainment.
        - Count nearby restaurants, bars, venues
        - Locations with 15+ entertainment venues nearby = 100
        """
        nearby_restaurants = row.get("restaurants_count", row.get("nearby_restaurants"))
        nearby_bars = row.get("nearby_bars")
        nearby_venues = row.get("nearby_venues")

        if pd.isna(nearby_restaurants) and pd.isna(nearby_bars) and pd.isna(nearby_venues):
            return 50.0  # Neutral when nightlife inputs are unavailable

        nearby_restaurants = 0 if pd.isna(nearby_restaurants) else nearby_restaurants
        nearby_bars = 0 if pd.isna(nearby_bars) else nearby_bars
        nearby_venues = 0 if pd.isna(nearby_venues) else nearby_venues

        total_nearby = nearby_restaurants + nearby_bars + nearby_venues
        
        # Cap at 100
        score = min((total_nearby / 15) * 100, 100.0)
        return score
    
    def compute_budget_score(self, row: pd.Series) -> float:
        """
        Score based on value: price and sqft ratio.
        - Inverse: lower price = higher score
        - Adjusted by sqft: price_per_sqft
        """
        price = row.get("price_num")
        sqft = row.get("sqft_num")
        
        if pd.isna(price) or pd.isna(sqft) or sqft == 0:
            return 50.0
        
        price_per_sqft = price / sqft
        
        # Scoring: lower is better
        # <$2/sqft = 100, >$4/sqft = 30
        if price_per_sqft <= 2:
            return 100.0
        elif price_per_sqft <= 3:
            return 75.0
        elif price_per_sqft <= 4:
            return 50.0
        else:
            return max(30.0 - (price_per_sqft - 4) * 5, 10.0)
    
    def compute_gym_score(self, row: pd.Series) -> float:
        """
        Score based on fitness amenities and nearby gyms.
        - In-unit gym = +30
        - Building gym = +20
        - Nearby gyms = +score based on count
        """
        has_gym_raw = row.get("has_gym")
        has_fitness_raw = row.get("has_fitness")
        nearby_gyms_raw = row.get("nearby_gyms")

        if has_gym_raw is None and has_fitness_raw is None and pd.isna(nearby_gyms_raw):
            return 50.0  # Neutral when gym inputs are unavailable

        has_gym = bool(has_gym_raw) if pd.notna(has_gym_raw) else False
        has_fitness = bool(has_fitness_raw) if pd.notna(has_fitness_raw) else False
        nearby_gyms = 0 if pd.isna(nearby_gyms_raw) else nearby_gyms_raw
        
        score = 20.0  # Baseline
        
        if has_gym:
            score += 30
        if has_fitness:
            score += 20
        
        # Add points for nearby gyms
        score += min(nearby_gyms * 5, 30.0)
        
        return min(score, 100.0)

    def compute_beds_score(self, row: pd.Series) -> float:
        """Score how close unit bedrooms are to the user's preferred bedroom count."""
        target_beds = self.preferences.get("target_beds")
        if target_beds is None:
            return 50.0

        beds = row.get("beds_num")
        if pd.isna(beds):
            return 50.0

        diff = abs(float(beds) - float(target_beds))
        if diff == 0:
            return 100.0
        if diff <= 0.5:
            return 85.0
        if diff <= 1.0:
            return 65.0
        if diff <= 2.0:
            return 40.0
        return 20.0

    def compute_baths_score(self, row: pd.Series) -> float:
        """Score how close unit bathrooms are to the user's preferred bathroom count."""
        target_baths = self.preferences.get("target_baths")
        if target_baths is None:
            return 50.0

        baths = row.get("baths_num")
        if pd.isna(baths):
            return 50.0

        diff = abs(float(baths) - float(target_baths))
        if diff == 0:
            return 100.0
        if diff <= 0.5:
            return 85.0
        if diff <= 1.0:
            return 65.0
        if diff <= 2.0:
            return 40.0
        return 20.0

    def compute_amenities_score(self, row: pd.Series) -> float:
        """Score by percentage of user-selected must-have amenities present."""
        required_amenities = self.preferences.get("required_amenities") or []
        if not required_amenities:
            return 50.0

        matched = 0
        for amenity_col in required_amenities:
            val = row.get(amenity_col)
            if pd.notna(val) and bool(val):
                matched += 1

        return (matched / len(required_amenities)) * 100.0

    def compute_metro_time_score(self, row: pd.Series) -> float:
        """
        Score by max acceptable minutes for metro proximity/commute.
        - Walking mode: uses metro_min
        - Driving mode: uses commute_driving_min when available
        """
        max_minutes = self.preferences.get("metro_max_minutes")
        if max_minutes is None:
            return 50.0

        metro_mode = self.preferences.get("metro_mode", "walking")
        time_val = row.get("metro_min")
        if metro_mode == "driving":
            driving_val = row.get("commute_driving_min")
            if pd.notna(driving_val):
                time_val = driving_val

        if pd.isna(time_val):
            return 40.0

        minutes = float(time_val)
        if minutes <= max_minutes:
            return 100.0
        if minutes <= max_minutes + 10:
            return 70.0
        if minutes <= max_minutes + 20:
            return 45.0
        return 20.0
    
    def compute_lifestyle_score(self, row: pd.Series) -> Tuple[float, Dict[str, float]]:
        """
        Compute weighted lifestyle score and component breakdown.
        Returns: (total_score, component_scores)
        """
        scores = {
            "commute": self.compute_commute_score(row),
            "safety": self.compute_safety_score(row),
            "nightlife": self.compute_nightlife_score(row),
            "budget": self.compute_budget_score(row),
            "gym": self.compute_gym_score(row),
            "beds": self.compute_beds_score(row),
            "baths": self.compute_baths_score(row),
            "amenities": self.compute_amenities_score(row),
            "metro_time": self.compute_metro_time_score(row),
        }
        
        total_score = sum(scores[k] * self.weights.get(k, 0.0) for k in scores)
        
        return round(total_score, 2), scores
    
    def score_apartments(self, df: pd.DataFrame) -> pd.DataFrame:
        """Score all apartments and return ranked DataFrame."""
        df = df.copy()
        
        scores = []
        component_data = {
            k: [] for k in [
                "commute",
                "safety",
                "nightlife",
                "budget",
                "gym",
                "beds",
                "baths",
                "amenities",
                "metro_time",
            ]
        }
        
        for _, row in df.iterrows():
            total, components = self.compute_lifestyle_score(row)
            scores.append(total)
            for k, v in components.items():
                component_data[k].append(v)
        
        df["lifestyle_score"] = scores
        for k, v in component_data.items():
            df[f"lifestyle_{k}_score"] = v
        
        return df.sort_values("lifestyle_score", ascending=False)


def get_priority_weights_from_sliders(priority_values: Dict[str, int]) -> Dict[str, float]:
    """Convert 0-5 slider values into normalized weights for enabled priorities."""
    enabled = {
        k: float(v) for k, v in priority_values.items()
        if v is not None and float(v) > 0
    }
    total = sum(enabled.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in enabled.items()}
