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