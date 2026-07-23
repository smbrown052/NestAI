import pandas as pd
from datetime import datetime, timedelta


def apply_ai_filters(df: pd.DataFrame, prefs: dict) -> pd.DataFrame:
    filtered = df.copy()
    must_haves = prefs.get("must_haves", {})

    max_price = must_haves.get("max_price")
    min_sqft = must_haves.get("min_sqft")
    beds = must_haves.get("beds")
    baths = must_haves.get("baths")
    availability = must_haves.get("availability")

    if max_price is not None and "unit_price" in filtered.columns:
        filtered = filtered[
            filtered["unit_price"].isna() | (filtered["unit_price"] <= max_price)
        ]

    if min_sqft is not None and "unit_sqft" in filtered.columns:
        filtered = filtered[
            filtered["unit_sqft"].isna() | (filtered["unit_sqft"] >= min_sqft)
        ]

    if beds is not None and "beds" in filtered.columns:
        filtered = filtered[
            filtered["beds"].isna() | (filtered["beds"] == beds)
        ]

    if baths is not None and "baths" in filtered.columns:
        filtered = filtered[
            filtered["baths"].isna() | (filtered["baths"] == baths)
        ]

    today = datetime.today()
    seven_days = today + timedelta(days=7)
    thirty_days = today + timedelta(days=30)

    if availability == "now":
        filtered = filtered[
            filtered["available_date"].astype(str).str.lower().isin(["now", "immediately"])
        ]
    elif availability == "within_7_days":
        filtered = filtered[
            filtered["availability_dt"].notna() & (filtered["availability_dt"] <= seven_days)
        ]
    elif availability == "within_30_days":
        filtered = filtered[
            filtered["availability_dt"].notna() & (filtered["availability_dt"] <= thirty_days)
        ]

    return filtered


def compute_ai_match_score(row: pd.Series, prefs: dict) -> float:
    nice = prefs.get("nice_to_haves", {})

    low_price_weight = nice.get("low_price", 0.5)
    large_space_weight = nice.get("large_space", 0.5)
    soon_available_weight = nice.get("soon_available", 0.5)

    rent = row.get("unit_price")
    sqft = row.get("unit_sqft")
    availability_dt = row.get("availability_dt")

    score = 0.0

    if pd.notna(rent) and rent > 0:
        score += (1 / rent) * 100000 * low_price_weight

    if pd.notna(sqft) and sqft > 0:
        score += (sqft / 1000) * 10 * large_space_weight

    if pd.notna(availability_dt):
        days_until = (availability_dt - datetime.today()).days
        if days_until <= 0:
            score += 15 * soon_available_weight
        elif days_until <= 7:
            score += 10 * soon_available_weight
        elif days_until <= 30:
            score += 5 * soon_available_weight

    return round(score, 2)


def rank_listings_with_ai(df: pd.DataFrame, prefs: dict) -> pd.DataFrame:
    filtered = apply_ai_filters(df, prefs).copy()

    if filtered.empty:
        return filtered

    filtered["ai_match_score"] = filtered.apply(
        lambda row: compute_ai_match_score(row, prefs), axis=1
    )

    return filtered.sort_values("ai_match_score", ascending=False)


# ── Apartment Match % ─────────────────────────────────────────────────────────

def compute_match_score(row: pd.Series, profile: dict) -> float:
    """
    Compute how well a unit matches a user profile (0–100).

    Supported profile keys (all optional):
        max_budget           int   — monthly rent ceiling
        min_sqft             int   — minimum square footage
        preferred_beds       float — preferred bedroom count
        commute_tolerance    int   — max acceptable commute in minutes
        walk_score_priority  float — 0–1, weight given to walkability
        space_priority       float — 0–1, extra weight for square footage
        price_priority       float — 0–1, extra weight for price fit
    """
    if not profile:
        return 0.0

    factors: list[tuple[str, float, float]] = []  # (name, score 0–1, weight)

    # ── Price fit ──────────────────────────────────────────────────────────
    budget = profile.get("max_budget")
    price = row.get("price_num")
    price_priority = float(profile.get("price_priority", 1.0))
    if budget and pd.notna(price) and price > 0:
        ratio = price / budget
        if ratio <= 0.85:
            score = 1.0
        elif ratio <= 1.0:
            score = 1.0 - (ratio - 0.85) * (1.0 / 0.15)
        else:
            score = max(0.0, 1.0 - (ratio - 1.0) * 3)
        factors.append(("price", min(1.0, score), price_priority))

    # ── Square footage fit ────────────────────────────────────────────────
    preferred_sqft = profile.get("min_sqft")
    sqft = row.get("sqft_num")
    space_priority = float(profile.get("space_priority", 0.8))
    if preferred_sqft and pd.notna(sqft) and sqft > 0:
        ratio = sqft / preferred_sqft
        score = min(1.0, ratio)
        factors.append(("sqft", score, space_priority))

    # ── Bedroom match ─────────────────────────────────────────────────────
    preferred_beds = profile.get("preferred_beds")
    beds = row.get("beds_num")
    if preferred_beds is not None and pd.notna(beds):
        diff = abs(float(beds) - float(preferred_beds))
        score = 1.0 if diff == 0 else max(0.0, 1.0 - diff * 0.5)
        factors.append(("beds", score, 1.0))

    # ── Commute fit ───────────────────────────────────────────────────────
    commute_tolerance = profile.get("commute_tolerance")
    commute = row.get("commute_transit_min") or row.get("commute_driving_min") or row.get("metro_min")
    if commute_tolerance and commute and pd.notna(commute):
        ratio = float(commute) / commute_tolerance
        score = max(0.0, 1.0 - max(0.0, ratio - 0.8) / 0.8)
        factors.append(("commute", min(1.0, score), 1.2))

    # ── Walkability fit ───────────────────────────────────────────────────
    walk_priority = float(profile.get("walk_score_priority", 0.0))
    walk = row.get("official_walk_score") or row.get("walk_score")
    if walk_priority > 0 and walk and pd.notna(walk):
        score = float(walk) / 100.0
        factors.append(("walk", score, walk_priority))

    if not factors:
        return 0.0

    total_weight = sum(w for _, _, w in factors)
    weighted_sum = sum(s * w for _, s, w in factors)
    raw = weighted_sum / total_weight if total_weight > 0 else 0.0
    return round(raw * 100, 1)


def explain_match(row: pd.Series, profile: dict, match_pct: float) -> list[str]:
    """
    Return 2–3 human-readable reasons why this unit matches (or doesn't) the profile.
    """
    reasons: list[str] = []
    tradeoffs: list[str] = []

    budget = profile.get("max_budget")
    price = row.get("price_num")
    if budget and pd.notna(price):
        price_int = int(price)
        if price <= budget * 0.85:
            reasons.append(f"Well under your ${budget:,} budget at ${price_int:,}/mo")
        elif price <= budget:
            reasons.append(f"Within your ${budget:,} budget at ${price_int:,}/mo")
        else:
            tradeoffs.append(f"Over budget at ${price_int:,}/mo (budget: ${budget:,})")

    commute_tolerance = profile.get("commute_tolerance")
    commute = row.get("commute_transit_min") or row.get("commute_driving_min") or row.get("metro_min")
    if commute_tolerance and commute and pd.notna(commute):
        commute_int = int(commute)
        if commute_int <= commute_tolerance:
            reasons.append(f"{commute_int}-min commute fits your {commute_tolerance}-min limit")
        else:
            tradeoffs.append(f"{commute_int}-min commute exceeds your {commute_tolerance}-min limit")

    walk_priority = float(profile.get("walk_score_priority", 0.0))
    walk = row.get("official_walk_score") or row.get("walk_score")
    if walk_priority >= 0.5 and walk and pd.notna(walk):
        walk_int = int(walk)
        if walk_int >= 70:
            reasons.append(f"Walk score {walk_int}/100 matches your walkability priority")
        else:
            tradeoffs.append(f"Walk score {walk_int}/100 is lower than ideal")

    preferred_sqft = profile.get("min_sqft")
    sqft = row.get("sqft_num")
    if preferred_sqft and pd.notna(sqft):
        sqft_int = int(sqft)
        if sqft_int >= preferred_sqft:
            reasons.append(f"{sqft_int} sqft meets your {preferred_sqft}+ sqft preference")
        else:
            tradeoffs.append(f"{sqft_int} sqft is under your {preferred_sqft} sqft preference")

    out = reasons[:2] + tradeoffs[:1]
    if not out:
        out = [f"{match_pct:.0f}% match based on your profile"]
    return out


def price_position(row: pd.Series, all_units_df: pd.DataFrame) -> tuple[float | None, float | None]:
    """
    Compare this unit's price against the average for the same bedroom count.

    Returns (difference_vs_avg, average_price).
    Positive difference means the unit is more expensive than average.
    Returns (None, None) when insufficient comparison data is available.
    """
    beds = row.get("beds_num")
    price = row.get("price_num")
    if pd.isna(price) or price is None:
        return None, None

    same_beds = all_units_df[
        all_units_df["beds_num"] == beds
    ]["price_num"].dropna()

    if len(same_beds) < 2:
        return None, None

    avg = same_beds.mean()
    return round(price - avg), round(avg)