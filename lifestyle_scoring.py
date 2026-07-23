"""
Lifestyle Score Engine
Reweights apartment scores based on user priorities across key life domains.
"""

import pandas as pd
from typing import Dict, Tuple


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
    
    # Default priority weights (will be overridden by user input)
    DEFAULT_WEIGHTS = {
        "commute": 0.20,
        "safety": 0.20,
        "nightlife": 0.20,
        "budget": 0.20,
        "gym": 0.20,
    }
    
    def __init__(self, user_weights: Dict[str, float] = None):
        """Initialize scorer with user priority weights."""
        self.weights = user_weights or self.DEFAULT_WEIGHTS
        # Normalize weights to sum to 1.0
        weight_sum = sum(self.weights.values())
        self.weights = {k: v / weight_sum for k, v in self.weights.items()}
    
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
        nearby_restaurants = row.get("restaurants_count", row.get("nearby_restaurants", 0))
        nearby_bars = row.get("nearby_bars", 0)
        nearby_venues = row.get("nearby_venues", 0)
        
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
        has_gym = row.get("has_gym", False)
        has_fitness = row.get("has_fitness", False)
        nearby_gyms = row.get("nearby_gyms", 0)
        
        score = 20.0  # Baseline
        
        if has_gym:
            score += 30
        if has_fitness:
            score += 20
        
        # Add points for nearby gyms
        score += min(nearby_gyms * 5, 30.0)
        
        return min(score, 100.0)
    
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
        }
        
        total_score = sum(scores[k] * self.weights[k] for k in scores)
        
        return round(total_score, 2), scores
    
    def score_apartments(self, df: pd.DataFrame) -> pd.DataFrame:
        """Score all apartments and return ranked DataFrame."""
        df = df.copy()
        
        scores = []
        component_data = {k: [] for k in ["commute", "safety", "nightlife", "budget", "gym"]}
        
        for _, row in df.iterrows():
            total, components = self.compute_lifestyle_score(row)
            scores.append(total)
            for k, v in components.items():
                component_data[k].append(v)
        
        df["lifestyle_score"] = scores
        for k, v in component_data.items():
            df[f"lifestyle_{k}_score"] = v
        
        return df.sort_values("lifestyle_score", ascending=False)


def get_priority_weights_from_sliders(commute: int, safety: int, nightlife: int, budget: int, gym: int) -> Dict[str, float]:
    """Convert slider values (1-5 stars) to normalized weights."""
    raw_weights = {
        "commute": commute,
        "safety": safety,
        "nightlife": nightlife,
        "budget": budget,
        "gym": gym,
    }
    
    # Normalize to sum to 1
    total = sum(raw_weights.values())
    return {k: v / total for k, v in raw_weights.items()}
