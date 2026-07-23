"""
enrichment.py
NestAI V2 data enrichment: building-level cache-first design.

Architecture
------------
All expensive API calls (Google Maps, Walk Score) operate at the *building*
level, not the unit level.  Results are persisted in the SQLite cache
(cache.py) so every future user benefits from a single API call.

Public entry points
-------------------
enrich_building(address)          — main cache-first enrichment for a building
get_commute_cached(building_id, address, destination)  — cache-first commute
geocode_address(address)          — cache-first geocoding (returns (lat, lng))

All other functions degrade gracefully when API keys are absent.
"""

import requests
import streamlit as st
import pandas as pd

from cache import (
    get_building_by_address,
    get_building_by_place_id,
    upsert_building,
    get_geocode,
    store_geocode,
    get_all_commutes,
    store_commute,
    check_rate_limit,
    record_api_call,
)


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
    Return (lat, lng) for an address.  Cache-first: coordinates never expire.
    Also returns the Google Place ID as a side-effect stored in the cache.
    """
    if not address:
        return None

    # Check persistent cache first (coordinates never expire)
    cached = get_geocode(address)
    if cached:
        return (cached["latitude"], cached["longitude"])

    key = _key("GOOGLE_MAPS_API_KEY")
    if not key:
        return None

    if not check_rate_limit("geocode", address):
        return None

    try:
        record_api_call("geocode", address)
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": key},
            timeout=5,
        )
        data = resp.json()
        if data.get("status") == "OK":
            result = data["results"][0]
            loc = result["geometry"]["location"]
            lat, lng = loc["lat"], loc["lng"]
            place_id = result.get("place_id", "")
            store_geocode(address, lat, lng, place_id)
            return (lat, lng)
    except Exception:
        pass
    return None


def _geocode_with_place_id(address: str) -> tuple[float, float, str] | None:
    """
    Return (lat, lng, place_id).  Used internally; results always cached.
    """
    if not address:
        return None

    cached = get_geocode(address)
    if cached and cached.get("latitude") is not None:
        return (
            cached["latitude"],
            cached["longitude"],
            cached.get("google_place_id") or "",
        )

    key = _key("GOOGLE_MAPS_API_KEY")
    if not key:
        return None

    if not check_rate_limit("geocode", address):
        return None

    try:
        record_api_call("geocode", address)
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": key},
            timeout=5,
        )
        data = resp.json()
        if data.get("status") == "OK":
            result = data["results"][0]
            loc = result["geometry"]["location"]
            lat, lng = loc["lat"], loc["lng"]
            place_id = result.get("place_id", "")
            store_geocode(address, lat, lng, place_id)
            return (lat, lng, place_id)
    except Exception:
        pass
    return None


# ── Building-Level Enrichment (cache-first) ────────────────────────────────────

def enrich_building(address: str) -> dict:
    """
    Return a fully-enriched building dict for *address*.

    Cache-first: if a fresh record exists in the SQLite cache it is returned
    immediately without any API calls.  Otherwise, all necessary APIs are called
    once, the result is stored permanently, and the dict is returned.

    Returns {} when enrichment is impossible (e.g. missing API keys).
    """
    if not address:
        return {}

    # ── 1. Check for a cached record by address ──────────────────────────────
    cached = get_building_by_address(address)
    if cached:
        return _building_row_to_enrichment(cached)

    # ── 2. Geocode (also retrieves Place ID) ─────────────────────────────────
    geo = _geocode_with_place_id(address)
    if not geo:
        return {}
    lat, lng, place_id = geo

    # ── 3. Check cache again by Place ID (handles address variants) ───────────
    if place_id:
        cached = get_building_by_place_id(place_id)
        if cached:
            return _building_row_to_enrichment(cached)

    # ── 4. Call Walk Score ─────────────────────────────────────────────────────
    ws_data = {}
    if walkscore_api_configured():
        ws_data = _fetch_walk_score(address, lat, lng)

    # ── 5. Call Google Places nearby ─────────────────────────────────────────
    places_data = {}
    if maps_api_configured():
        places_data = _fetch_nearby_places(lat, lng)

    # ── 6. Build record and store ─────────────────────────────────────────────
    building_data = {
        "google_place_id": place_id,
        "street_address": address,
        "latitude": lat,
        "longitude": lng,
        **ws_data,
        **places_data,
    }
    building_id = upsert_building(building_data)
    building_data["building_id"] = building_id
    return building_data


def _building_row_to_enrichment(row: dict) -> dict:
    """Map a buildings table row to the enrichment dict shape used by the app."""
    return {
        "building_id": row.get("building_id"),
        "google_place_id": row.get("google_place_id"),
        "street_address": row.get("street_address"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        # Walk Score fields
        "official_walk_score": row.get("walk_score"),
        "walk_description": row.get("walk_description"),
        "transit_score": row.get("transit_score"),
        "transit_description": row.get("transit_description"),
        "bike_score": row.get("bike_score"),
        "bike_description": row.get("bike_description"),
        # Nearby places
        "nearby_groceries": row.get("grocery_count"),
        "restaurants_count": row.get("restaurant_count"),
        "nearby_gyms": row.get("gym_count"),
        "nearby_parks": row.get("park_count"),
        "nearby_cafes": row.get("cafe_count"),
        # Transit
        "nearest_metro": row.get("nearest_metro"),
        "nearest_metro_distance": row.get("nearest_metro_distance"),
        # Metadata
        "last_enriched_at": row.get("last_enriched_at"),
    }


def _fetch_walk_score(address: str, lat: float, lng: float) -> dict:
    """Fetch Walk/Transit/Bike scores from walkscore.com.  Rate-limited."""
    key = _key("WALKSCORE_API_KEY")
    if not key:
        return {}
    if not check_rate_limit("walkscore", address):
        return {}
    try:
        record_api_call("walkscore", address)
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
            result["walk_score"] = data["walkscore"]
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


def _fetch_nearby_places(lat: float, lng: float, radius_meters: int = 1000) -> dict:
    """Count nearby places by category via Google Places Nearby Search."""
    key = _key("GOOGLE_MAPS_API_KEY")
    if not key:
        return {}
    place_types = {
        "grocery_count": "supermarket",
        "restaurant_count": "restaurant",
        "gym_count": "gym",
        "park_count": "park",
        "cafe_count": "cafe",
    }
    counts: dict = {}
    location_str = f"{lat},{lng}"
    for field, place_type in place_types.items():
        if not check_rate_limit("places", f"{location_str}:{place_type}"):
            counts[field] = None
            continue
        try:
            record_api_call("places", f"{location_str}:{place_type}")
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
                params={
                    "location": location_str,
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


# ── Commute (cache-first) ─────────────────────────────────────────────────────

def get_commute_cached(building_id: str, origin_address: str, destination: str) -> dict:
    """
    Return commute times for all modes, using cache when available.
    Key: building_id × destination × mode.  TTL: 7 days.
    """
    if not destination:
        return {}

    # Try cache first
    cached = get_all_commutes(building_id, destination)
    if cached:
        return cached

    # Fall back to live API
    live = get_commute_times(origin_address, destination)
    for mode, minutes in live.items():
        store_commute(building_id, destination, mode, minutes)
    return live


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


# ── Walk Score (kept for backwards-compat; delegates to enrich_building) ─────

def get_official_walk_score(address: str, lat: float = None, lng: float = None) -> dict:
    """
    Return Walk/Transit/Bike scores for *address*.

    V2: Delegates to enrich_building() so results are always cached at the
    building level.  The lat/lng arguments are ignored (geocoding happens
    inside enrich_building).
    """
    building = enrich_building(address)
    if not building:
        return {}
    result = {}
    if building.get("official_walk_score") is not None:
        result["official_walk_score"] = building["official_walk_score"]
        result["walk_description"] = building.get("walk_description", "")
    if building.get("transit_score") is not None:
        result["transit_score"] = building["transit_score"]
        result["transit_description"] = building.get("transit_description", "")
    if building.get("bike_score") is not None:
        result["bike_score"] = building["bike_score"]
        result["bike_description"] = building.get("bike_description", "")
    return result


# ── Neighborhood Places (kept for backwards-compat) ───────────────────────────

def get_neighborhood_places(address: str, radius_meters: int = 1000) -> dict:
    """
    Return nearby place counts for *address*.

    V2: Delegates to enrich_building() so results are cached per building.
    radius_meters is ignored (default 1 km used internally).
    """
    building = enrich_building(address)
    if not building:
        return {}
    return {
        "nearby_groceries": building.get("nearby_groceries"),
        "restaurants_count": building.get("restaurants_count"),
        "nearby_gyms": building.get("nearby_gyms"),
        "nearby_parks": building.get("nearby_parks"),
        "nearby_cafes": building.get("nearby_cafes"),
    }


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
    "building_id",
    "last_enriched_at",
]


def enrich_units_df(df: pd.DataFrame, commute_destination: str = "") -> pd.DataFrame:
    """
    Return a copy of *df* with all enrichment columns populated.

    V2: Operates at the building level — all units at the same address share
    one set of enrichment data.  Results are pulled from the SQLite building
    cache first; APIs are only called when the cache is missing or expired.
    """
    if df.empty:
        return df

    rows = []
    # building-level cache keyed by address (within this call)
    building_cache: dict[str, dict] = {}

    for _, row in df.iterrows():
        address = str(row.get("address", "") or "")

        if address not in building_cache:
            # enrich_building is cache-first: SQLite → API
            building_data = enrich_building(address) if address else {}

            # Commute data (cache-first per building × destination)
            commute_data: dict = {}
            if commute_destination and building_data.get("building_id"):
                commute_data = get_commute_cached(
                    building_data["building_id"],
                    address,
                    commute_destination,
                )
            elif commute_destination and address:
                # No building_id yet (geocode failed); try direct lookup
                commute_data = get_commute_times(address, commute_destination)

            enriched_vals: dict = {**building_data}

            # Flatten commute dict into columns
            if commute_data:
                enriched_vals["commute_driving_min"] = commute_data.get("driving")
                enriched_vals["commute_transit_min"] = commute_data.get("transit")
                enriched_vals["commute_biking_min"] = commute_data.get("bicycling")
                enriched_vals["commute_walking_min"] = commute_data.get("walking")
                enriched_vals["commute_display"] = format_commute_display(commute_data)

            # Lifestyle summary
            unit_dict = {**row.to_dict(), **enriched_vals}
            enriched_vals["lifestyle_summary"] = generate_lifestyle_summary(unit_dict)

            building_cache[address] = enriched_vals

        row_dict = row.to_dict()
        row_dict.update(building_cache[address])
        rows.append(row_dict)

    return pd.DataFrame(rows)
