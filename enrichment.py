"""
enrichment.py
External data enrichment for NestAI: commute times, neighborhood places, Walk Score.
All public functions degrade gracefully when API keys are absent — the app
continues to work normally, just without the live data layer.
"""

import requests
import streamlit as st
import pandas as pd


# ── API key helpers ───────────────────────────────────────────────────────────

def _key(name: str) -> str:
    """Safely read a secret from st.secrets, returning '' when unavailable."""
    try:
        return st.secrets.get(name, "") or ""
    except Exception:
        return ""


def maps_api_configured() -> bool:
    return bool(_key("GOOGLE_MAPS_API_KEY"))


def walkscore_api_configured() -> bool:
    return bool(_key("WALKSCORE_API_KEY"))


# ── Geocoding ─────────────────────────────────────────────────────────────────

def geocode_address(address: str) -> tuple | None:
    """
    Return (lat, lng) for an address using Google Geocoding API.
    Returns None when the key is absent or geocoding fails.
    """
    key = _key("GOOGLE_MAPS_API_KEY")
    if not key or not address:
        return None
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": key},
            timeout=5,
        )
        data = resp.json()
        if data.get("status") == "OK":
            loc = data["results"][0]["geometry"]["location"]
            return (loc["lat"], loc["lng"])
    except Exception:
        pass
    return None


# ── Commute Intelligence ──────────────────────────────────────────────────────

def get_commute_times(origin_address: str, destination: str) -> dict:
    """
    Fetch commute times from origin to destination via Google Distance Matrix API.

    Returns a dict like:
        {"driving": 26, "transit": 34, "bicycling": 19, "walking": 52}
    Values are in minutes. Modes that fail are omitted.
    """
    key = _key("GOOGLE_MAPS_API_KEY")
    if not key or not origin_address or not destination:
        return {}

    modes = ["driving", "transit", "bicycling", "walking"]
    results = {}
    for mode in modes:
        try:
            params = {
                "origins": origin_address,
                "destinations": destination,
                "mode": mode,
                "key": key,
            }
            if mode in ("driving", "transit"):
                params["departure_time"] = "now"
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params=params,
                timeout=10,
            )
            data = resp.json()
            if data.get("status") == "OK":
                rows = data.get("rows", [])
                if rows:
                    element = rows[0].get("elements", [{}])[0]
                    if element.get("status") == "OK":
                        dur = element.get("duration_in_traffic") or element.get("duration")
                        if dur:
                            results[mode] = round(dur["value"] / 60)
        except Exception:
            continue
    return results


def format_commute_display(commute: dict) -> str:
    """
    Format commute times dict into a compact multi-icon string.
    e.g. "🚗 26 min  🚇 34 min  🚲 19 min  🚶 52 min"
    """
    icons = {
        "driving": "🚗",
        "transit": "🚇",
        "bicycling": "🚲",
        "walking": "🚶",
    }
    parts = []
    for mode in ["driving", "transit", "bicycling", "walking"]:
        if mode in commute:
            parts.append(f"{icons[mode]} {commute[mode]} min")
    return "  ".join(parts) if parts else "—"


# ── Neighborhood Places ───────────────────────────────────────────────────────

def get_neighborhood_places(address: str, radius_meters: int = 1000) -> dict:
    """
    Count nearby places by category using Google Places Nearby Search.

    Returns a dict like:
        {"nearby_groceries": 3, "restaurants_count": 12, "nearby_gyms": 2, "nearby_parks": 4}
    """
    key = _key("GOOGLE_MAPS_API_KEY")
    if not key or not address:
        return {}

    coords = geocode_address(address)
    if not coords:
        return {}
    lat, lng = coords

    place_types = {
        "nearby_groceries": "supermarket",
        "restaurants_count": "restaurant",
        "nearby_gyms": "gym",
        "nearby_parks": "park",
        "nearby_cafes": "cafe",
    }

    counts = {}
    for field, place_type in place_types.items():
        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
                params={
                    "location": f"{lat},{lng}",
                    "radius": radius_meters,
                    "type": place_type,
                    "key": key,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("status") in ("OK", "ZERO_RESULTS"):
                counts[field] = len(data.get("results", []))
            else:
                counts[field] = None
        except Exception:
            counts[field] = None
    return counts


# ── Official Walk Score ───────────────────────────────────────────────────────

def get_official_walk_score(address: str, lat: float = None, lng: float = None) -> dict:
    """
    Fetch official Walk Score, Transit Score, and Bike Score from walkscore.com.

    Returns a dict like:
        {
          "official_walk_score": 90, "walk_description": "Walker's Paradise",
          "transit_score": 70,        "transit_description": "Excellent Transit",
          "bike_score": 65,           "bike_description": "Bikeable",
        }
    """
    key = _key("WALKSCORE_API_KEY")
    if not key or not address:
        return {}

    if lat is None or lng is None:
        coords = geocode_address(address)
        if coords:
            lat, lng = coords
        else:
            return {}

    try:
        resp = requests.get(
            "https://api.walkscore.com/score",
            params={
                "format": "json",
                "address": address,
                "lat": lat,
                "lon": lng,
                "transit": 1,
                "bike": 1,
                "wsapikey": key,
            },
            timeout=10,
        )
        data = resp.json()
        result = {}
        if "walkscore" in data:
            result["official_walk_score"] = data["walkscore"]
            result["walk_description"] = data.get("description", "")
        transit = data.get("transit") or {}
        if transit.get("score") is not None:
            result["transit_score"] = transit["score"]
            result["transit_description"] = transit.get("description", "")
        bike = data.get("bike") or {}
        if bike.get("score") is not None:
            result["bike_score"] = bike["score"]
            result["bike_description"] = bike.get("description", "")
        return result
    except Exception:
        return {}


# ── Lifestyle Summary ─────────────────────────────────────────────────────────

def generate_lifestyle_summary(unit: dict) -> str:
    """
    Produce a one-sentence lifestyle label from available neighborhood signals.
    Rule-based — no LLM required.
    """
    walk = unit.get("official_walk_score") or unit.get("walk_score") or 0
    transit = unit.get("transit_score") or 0
    bike = unit.get("bike_score") or 0
    groceries = unit.get("nearby_groceries") or 0
    gyms = unit.get("nearby_gyms") or 0
    restaurants = unit.get("restaurants_count") or 0
    parks = unit.get("nearby_parks") or 0

    tags = []

    if walk >= 90:
        tags.append("walker's paradise")
    elif walk >= 70:
        tags.append("very walkable")
    elif walk >= 50:
        tags.append("somewhat walkable")

    if transit >= 70:
        tags.append("excellent transit")
    elif transit >= 50:
        tags.append("good transit access")

    if bike >= 70:
        tags.append("very bikeable")
    elif bike >= 50:
        tags.append("bikeable")

    if restaurants >= 10:
        tags.append("surrounded by dining")
    elif restaurants >= 5:
        tags.append("plenty of dining nearby")

    if parks >= 3:
        tags.append("near multiple parks")
    elif parks == 1:
        tags.append("near a park")

    if gyms >= 2:
        tags.append("fitness options nearby")

    if not tags:
        return "Neighborhood data not yet available."

    main = tags[0].capitalize()
    rest = tags[1:]
    if rest:
        return f"{main} — {', '.join(rest)}."
    return f"{main}."


# ── Cost of Living ────────────────────────────────────────────────────────────

def compute_monthly_total(price_num: float, extras: dict) -> dict:
    """
    Compute estimated monthly total cost given rent + optional extras.

    extras keys (all optional): parking, utilities, pet_fee, renters_insurance
    Returns a dict with line items and estimated_total.
    """
    breakdown = {"Rent": price_num or 0}
    if extras.get("parking"):
        breakdown["Parking"] = extras["parking"]
    if extras.get("utilities"):
        breakdown["Utilities"] = extras["utilities"]
    if extras.get("pet_fee"):
        breakdown["Pet Fee"] = extras["pet_fee"]
    if extras.get("renters_insurance"):
        breakdown["Renter's Insurance"] = extras["renters_insurance"]
    breakdown["Estimated Total"] = sum(breakdown.values())
    return breakdown


# ── Per-DataFrame Enrichment ──────────────────────────────────────────────────

_ENRICHED_COLS = [
    "commute_driving_min", "commute_transit_min",
    "commute_biking_min", "commute_walking_min", "commute_display",
    "nearby_groceries", "restaurants_count", "nearby_gyms",
    "nearby_parks", "nearby_cafes",
    "official_walk_score", "walk_description",
    "transit_score", "transit_description",
    "bike_score", "bike_description",
    "lifestyle_summary",
]


def enrich_units_df(df: pd.DataFrame, commute_destination: str = "") -> pd.DataFrame:
    """
    Return a copy of *df* with all enrichment columns populated.
    Results are cached in st.session_state by address to avoid redundant API calls.
    Safe to call even when no API keys are configured.
    """
    if df.empty:
        return df

    rows = []
    address_cache: dict[str, dict] = {}

    for _, row in df.iterrows():
        address = str(row.get("address", "") or "")
        dest_key = f"{address}||{commute_destination}"

        if dest_key not in address_cache:
            enriched_vals: dict = {}

            # Commute
            if commute_destination and address:
                ck = f"commute::{dest_key}"
                if ck not in st.session_state:
                    st.session_state[ck] = get_commute_times(address, commute_destination)
                commute = st.session_state[ck]
                enriched_vals["commute_driving_min"] = commute.get("driving")
                enriched_vals["commute_transit_min"] = commute.get("transit")
                enriched_vals["commute_biking_min"] = commute.get("bicycling")
                enriched_vals["commute_walking_min"] = commute.get("walking")
                enriched_vals["commute_display"] = format_commute_display(commute)

            # Neighborhood places
            if address:
                ck = f"places::{address}"
                if ck not in st.session_state:
                    st.session_state[ck] = get_neighborhood_places(address)
                enriched_vals.update(st.session_state[ck])

            # Official Walk Score
            if address:
                ck = f"walkscore::{address}"
                if ck not in st.session_state:
                    st.session_state[ck] = get_official_walk_score(address)
                enriched_vals.update(st.session_state[ck])

            # Lifestyle summary (uses whatever data we got)
            unit_dict = {**row.to_dict(), **enriched_vals}
            enriched_vals["lifestyle_summary"] = generate_lifestyle_summary(unit_dict)

            address_cache[dest_key] = enriched_vals

        row_dict = row.to_dict()
        row_dict.update(address_cache[dest_key])
        rows.append(row_dict)

    return pd.DataFrame(rows)
