"""
cache.py
NestAI V2 persistent cache layer.

Implements building-level and commute caching via SQLite so expensive
Google Maps / Walk Score API calls are made only once per building,
then reused by every future user.

Cache TTLs:
  geocode / place_id  — never expires (address does not change)
  building enrichment — 30 days
  nearby places       — 30 days
  walk score          — 30 days
  commute             — 7 days
  AI output           — until apartment/building data changes
"""

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Path ──────────────────────────────────────────────────────────────────────

_DB_PATH = Path(__file__).parent / "data" / "nestai_cache.db"

# TTLs in days
_TTL_BUILDING = 30
_TTL_COMMUTE = 7

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS buildings (
    building_id       TEXT PRIMARY KEY,
    google_place_id   TEXT,
    building_name     TEXT,
    street_address    TEXT,
    city              TEXT,
    state             TEXT,
    zip               TEXT,
    latitude          REAL,
    longitude         REAL,
    walk_score        INTEGER,
    walk_description  TEXT,
    transit_score     INTEGER,
    transit_description TEXT,
    bike_score        INTEGER,
    bike_description  TEXT,
    grocery_count     INTEGER,
    restaurant_count  INTEGER,
    gym_count         INTEGER,
    park_count        INTEGER,
    cafe_count        INTEGER,
    nearest_metro     TEXT,
    nearest_metro_distance TEXT,
    created_at        TEXT,
    updated_at        TEXT,
    last_enriched_at  TEXT
);

CREATE TABLE IF NOT EXISTS commute_cache (
    building_id       TEXT NOT NULL,
    destination       TEXT NOT NULL,
    travel_mode       TEXT NOT NULL,
    travel_time_min   INTEGER,
    distance_text     TEXT,
    cached_at         TEXT,
    PRIMARY KEY (building_id, destination, travel_mode)
);

CREATE TABLE IF NOT EXISTS ai_cache (
    cache_key         TEXT PRIMARY KEY,
    cache_type        TEXT,
    content           TEXT,
    created_at        TEXT,
    invalidated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_buildings_place_id ON buildings (google_place_id);
CREATE INDEX IF NOT EXISTS idx_buildings_address  ON buildings (street_address);
"""


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def get_connection() -> sqlite3.Connection:
    """Return an initialised connection."""
    conn = _connect()
    _init_db(conn)
    return conn


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_expired(cached_at_iso: str | None, ttl_days: int) -> bool:
    if not cached_at_iso:
        return True
    try:
        cached = datetime.fromisoformat(cached_at_iso)
        if cached.tzinfo is None:
            cached = cached.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - cached > timedelta(days=ttl_days)
    except Exception:
        return True


def _address_key(address: str) -> str:
    """Stable hash key for a raw address string."""
    normalized = address.lower().strip()
    return "addr:" + hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _ai_cache_key(cache_type: str, inputs: dict) -> str:
    raw = json.dumps(inputs, sort_keys=True, default=str)
    return f"{cache_type}:{hashlib.sha256(raw.encode()).hexdigest()[:20]}"


# ── Building Cache ─────────────────────────────────────────────────────────────

def get_building(building_id: str) -> dict | None:
    """
    Return cached building dict if present and not expired, else None.
    building_id is either a Google Place ID or an address hash.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM buildings WHERE building_id = ?", (building_id,)
        ).fetchone()
        if row is None:
            return None
        row = dict(row)
        if _is_expired(row.get("last_enriched_at"), _TTL_BUILDING):
            return None
        return row


def get_building_by_place_id(place_id: str) -> dict | None:
    """Lookup by Google Place ID (handles address variant deduplication)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM buildings WHERE google_place_id = ?", (place_id,)
        ).fetchone()
        if row is None:
            return None
        row = dict(row)
        if _is_expired(row.get("last_enriched_at"), _TTL_BUILDING):
            return None
        return row


def get_building_by_address(address: str) -> dict | None:
    """
    Look up a building by normalised address hash.
    Falls back to a case-insensitive partial match when no hash record exists.
    """
    building_id = _address_key(address)
    result = get_building(building_id)
    if result:
        return result
    # Try exact street_address match (different hash but same canonical address)
    normalized = address.strip()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM buildings WHERE lower(street_address) = lower(?)",
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        row = dict(row)
        if _is_expired(row.get("last_enriched_at"), _TTL_BUILDING):
            return None
        return row


def upsert_building(data: dict) -> str:
    """
    Insert or update a building record.  Returns the building_id used.

    data should include at minimum:
      street_address, latitude, longitude

    Optional but preferred:
      google_place_id, building_name, city, state, zip,
      walk_score, transit_score, bike_score, walk_description,
      transit_description, bike_description,
      grocery_count, restaurant_count, gym_count, park_count, cafe_count,
      nearest_metro, nearest_metro_distance
    """
    place_id = data.get("google_place_id") or ""
    address = data.get("street_address", "")

    # Determine the canonical key
    if place_id:
        building_id = place_id
    else:
        building_id = _address_key(address)

    now = _now_iso()

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT building_id, created_at FROM buildings WHERE building_id = ?",
            (building_id,),
        ).fetchone()

        created_at = existing["created_at"] if existing else now

        conn.execute(
            """
            INSERT INTO buildings (
                building_id, google_place_id, building_name,
                street_address, city, state, zip,
                latitude, longitude,
                walk_score, walk_description,
                transit_score, transit_description,
                bike_score, bike_description,
                grocery_count, restaurant_count, gym_count, park_count, cafe_count,
                nearest_metro, nearest_metro_distance,
                created_at, updated_at, last_enriched_at
            ) VALUES (
                :building_id, :google_place_id, :building_name,
                :street_address, :city, :state, :zip,
                :latitude, :longitude,
                :walk_score, :walk_description,
                :transit_score, :transit_description,
                :bike_score, :bike_description,
                :grocery_count, :restaurant_count, :gym_count, :park_count, :cafe_count,
                :nearest_metro, :nearest_metro_distance,
                :created_at, :updated_at, :last_enriched_at
            )
            ON CONFLICT(building_id) DO UPDATE SET
                google_place_id      = excluded.google_place_id,
                building_name        = excluded.building_name,
                street_address       = excluded.street_address,
                city                 = excluded.city,
                state                = excluded.state,
                zip                  = excluded.zip,
                latitude             = excluded.latitude,
                longitude            = excluded.longitude,
                walk_score           = excluded.walk_score,
                walk_description     = excluded.walk_description,
                transit_score        = excluded.transit_score,
                transit_description  = excluded.transit_description,
                bike_score           = excluded.bike_score,
                bike_description     = excluded.bike_description,
                grocery_count        = excluded.grocery_count,
                restaurant_count     = excluded.restaurant_count,
                gym_count            = excluded.gym_count,
                park_count           = excluded.park_count,
                cafe_count           = excluded.cafe_count,
                nearest_metro        = excluded.nearest_metro,
                nearest_metro_distance = excluded.nearest_metro_distance,
                updated_at           = excluded.updated_at,
                last_enriched_at     = excluded.last_enriched_at
            """,
            {
                "building_id": building_id,
                "google_place_id": place_id or None,
                "building_name": data.get("building_name"),
                "street_address": address or None,
                "city": data.get("city"),
                "state": data.get("state"),
                "zip": data.get("zip"),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "walk_score": data.get("walk_score"),
                "walk_description": data.get("walk_description"),
                "transit_score": data.get("transit_score"),
                "transit_description": data.get("transit_description"),
                "bike_score": data.get("bike_score"),
                "bike_description": data.get("bike_description"),
                "grocery_count": data.get("grocery_count"),
                "restaurant_count": data.get("restaurant_count"),
                "gym_count": data.get("gym_count"),
                "park_count": data.get("park_count"),
                "cafe_count": data.get("cafe_count"),
                "nearest_metro": data.get("nearest_metro"),
                "nearest_metro_distance": data.get("nearest_metro_distance"),
                "created_at": created_at,
                "updated_at": now,
                "last_enriched_at": now,
            },
        )
        conn.commit()
    return building_id


# ── Geocode-only stub ─────────────────────────────────────────────────────────
# Coordinates and Place ID never expire — store them even before full enrichment.

def get_geocode(address: str) -> dict | None:
    """Return cached lat/lon/place_id for address, regardless of enrichment TTL."""
    building_id = _address_key(address)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT building_id, google_place_id, latitude, longitude "
            "FROM buildings WHERE building_id = ? OR lower(street_address) = lower(?)",
            (building_id, address.strip()),
        ).fetchone()
        if row and row["latitude"] is not None:
            return dict(row)
    return None


def store_geocode(address: str, lat: float, lng: float, place_id: str = "") -> str:
    """
    Persist geocode result (coordinates + optional Place ID).
    Returns building_id.
    """
    building_id = place_id if place_id else _address_key(address)
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO buildings (
                building_id, google_place_id, street_address,
                latitude, longitude, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(building_id) DO UPDATE SET
                google_place_id = excluded.google_place_id,
                latitude        = excluded.latitude,
                longitude       = excluded.longitude,
                updated_at      = excluded.updated_at
            """,
            (building_id, place_id or None, address.strip(), lat, lng, now, now),
        )
        conn.commit()
    return building_id


# ── Commute Cache ─────────────────────────────────────────────────────────────

def get_commute(building_id: str, destination: str, mode: str) -> int | None:
    """Return cached commute time in minutes or None if missing/expired."""
    dest_key = destination.strip().lower()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT travel_time_min, cached_at FROM commute_cache "
            "WHERE building_id = ? AND lower(destination) = ? AND travel_mode = ?",
            (building_id, dest_key, mode),
        ).fetchone()
        if row is None:
            return None
        if _is_expired(row["cached_at"], _TTL_COMMUTE):
            return None
        return row["travel_time_min"]


def store_commute(
    building_id: str,
    destination: str,
    mode: str,
    travel_time_min: int,
    distance_text: str = "",
) -> None:
    dest_key = destination.strip().lower()
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO commute_cache
                (building_id, destination, travel_mode, travel_time_min, distance_text, cached_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(building_id, destination, travel_mode) DO UPDATE SET
                travel_time_min = excluded.travel_time_min,
                distance_text   = excluded.distance_text,
                cached_at       = excluded.cached_at
            """,
            (building_id, dest_key, mode, travel_time_min, distance_text, now),
        )
        conn.commit()


def get_all_commutes(building_id: str, destination: str) -> dict:
    """Return all cached (non-expired) commute modes for a building+destination."""
    dest_key = destination.strip().lower()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_TTL_COMMUTE)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT travel_mode, travel_time_min FROM commute_cache "
            "WHERE building_id = ? AND lower(destination) = ? AND cached_at > ?",
            (building_id, dest_key, cutoff),
        ).fetchall()
    return {r["travel_mode"]: r["travel_time_min"] for r in rows}


# ── AI Cache ──────────────────────────────────────────────────────────────────

def get_ai_output(cache_type: str, inputs: dict) -> str | None:
    """Return a cached AI output string or None."""
    key = _ai_cache_key(cache_type, inputs)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT content, invalidated_at FROM ai_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        if row["invalidated_at"]:
            return None
        return row["content"]


def store_ai_output(cache_type: str, inputs: dict, content: str) -> None:
    key = _ai_cache_key(cache_type, inputs)
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_cache (cache_key, cache_type, content, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                content    = excluded.content,
                created_at = excluded.created_at,
                invalidated_at = NULL
            """,
            (key, cache_type, content, now),
        )
        conn.commit()


def invalidate_ai_output(cache_type: str, inputs: dict) -> None:
    key = _ai_cache_key(cache_type, inputs)
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE ai_cache SET invalidated_at = ? WHERE cache_key = ?",
            (now, key),
        )
        conn.commit()


# ── Rate limiter ──────────────────────────────────────────────────────────────
# In-process cooldown store.  Resets on server restart (acceptable for Streamlit).

_LAST_CALL: dict[str, float] = {}
_COOLDOWN_SEC = {
    "geocode": 1,
    "walkscore": 2,
    "places": 2,
    "commute": 2,
    "default": 1,
}


def check_rate_limit(action: str, key: str = "") -> bool:
    """
    Return True if the action is allowed (cooldown elapsed), False if throttled.
    key can be a user/session identifier for per-user limiting.
    """
    full_key = f"{action}:{key}"
    last = _LAST_CALL.get(full_key, 0)
    cooldown = _COOLDOWN_SEC.get(action, _COOLDOWN_SEC["default"])
    return (time.time() - last) >= cooldown


def record_api_call(action: str, key: str = "") -> None:
    """Record that an API call was made (for rate limiting)."""
    full_key = f"{action}:{key}"
    _LAST_CALL[full_key] = time.time()
