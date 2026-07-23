"""
home_storage.py
Local SQLite persistence for saved/archived homes (Homes tab).

NOTE (local/session-based enforcement):
    All records are stored per-session using a session identifier derived
    from Streamlit's session state.  Ownership enforcement is LOCAL and
    not production-grade — it uses a randomly generated session ID rather
    than an authenticated user account.  This is intentional for the
    current phase; the interface is designed so it can be replaced by an
    API-backed service later without changing call sites.

    Current controls:
      - Each save/read is scoped to `session_id`.
      - Free users may have at most 1 active saved home; extras are archived.
      - Archived homes are retained (never deleted) so they can be restored
        after upgrading.

Schema:
    saved_homes
      id             INTEGER PK
      session_id     TEXT NOT NULL
      property_type  TEXT     (RENTAL_HOME | HOME_FOR_SALE)
      address        TEXT
      city           TEXT
      state          TEXT
      postal_code    TEXT
      display_name   TEXT
      monthly_rent   INTEGER  (nullable)
      sale_price     INTEGER  (nullable)
      bedrooms       INTEGER  (nullable)
      bathrooms      REAL     (nullable)
      square_feet    INTEGER  (nullable)
      available_date TEXT
      pets_policy    TEXT
      cooling        TEXT
      heating        TEXT
      parking        TEXT
      laundry        TEXT
      walk_score     INTEGER  (nullable)
      transit_score  INTEGER  (nullable)
      bike_score     INTEGER  (nullable)
      days_on_zillow INTEGER  (nullable)
      hours_on_zillow INTEGER (nullable)
      description    TEXT
      features_json  TEXT     (JSON array)
      schools_json   TEXT     (JSON array)
      warnings_json  TEXT     (JSON array)
      is_active      INTEGER  DEFAULT 1
      is_archived    INTEGER  DEFAULT 0
      created_at     TEXT
      updated_at     TEXT
      raw_source_text TEXT    (capped at 128 KB)

    home_events
      id             INTEGER PK
      session_id     TEXT NOT NULL
      event_type     TEXT     (saved | archived | restored | replaced)
      home_id        INTEGER  (FK → saved_homes.id)
      created_at     TEXT
"""

from __future__ import annotations

import html
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import streamlit as st

from parser.home_listing import ParsedHomeResult

# ── Database path ─────────────────────────────────────────────────────────────

_DB_PATH = Path(__file__).parent / "data" / "nestai_cache.db"

_MAX_RAW_TEXT_BYTES = 131_072   # 128 KB

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_homes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT    NOT NULL,
    property_type    TEXT,
    address          TEXT,
    city             TEXT,
    state            TEXT,
    postal_code      TEXT,
    display_name     TEXT,
    monthly_rent     INTEGER,
    sale_price       INTEGER,
    bedrooms         INTEGER,
    bathrooms        REAL,
    square_feet      INTEGER,
    available_date   TEXT,
    pets_policy      TEXT,
    cooling          TEXT,
    heating          TEXT,
    parking          TEXT,
    laundry          TEXT,
    walk_score       INTEGER,
    transit_score    INTEGER,
    bike_score       INTEGER,
    days_on_zillow   INTEGER,
    hours_on_zillow  INTEGER,
    description      TEXT,
    features_json    TEXT,
    schools_json     TEXT,
    warnings_json    TEXT,
    is_active        INTEGER DEFAULT 1,
    is_archived      INTEGER DEFAULT 0,
    created_at       TEXT,
    updated_at       TEXT,
    raw_source_text  TEXT
);

CREATE INDEX IF NOT EXISTS idx_saved_homes_session
    ON saved_homes (session_id, is_active, is_archived);

CREATE TABLE IF NOT EXISTS home_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    home_id     INTEGER,
    meta_json   TEXT,
    created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_home_events_session
    ON home_events (session_id);
"""


# ── Connection helpers ────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Session ID ────────────────────────────────────────────────────────────────

def get_session_id() -> str:
    """Return a stable identifier for the current Streamlit session.

    This is a randomly-generated UUID assigned once per browser session.
    It is NOT an authenticated user ID.  See module-level note.
    """
    if "nestai_session_id" not in st.session_state:
        st.session_state.nestai_session_id = str(uuid.uuid4())
    return st.session_state.nestai_session_id


# ── Input sanitization ────────────────────────────────────────────────────────

def _s(value: str | None, max_len: int = 2000) -> str:
    if not value:
        return ""
    return html.escape(str(value).strip())[:max_len]


def _sanitize_raw_text(text: str | None) -> str:
    if not text:
        return ""
    # Cap at 128 KB and escape HTML to prevent injection
    truncated = text[:_MAX_RAW_TEXT_BYTES]
    return html.escape(truncated)


# ── Public API ────────────────────────────────────────────────────────────────

def save_home(
    result: ParsedHomeResult,
    raw_source_text: str | None = None,
) -> int:
    """Persist a parsed home result for the current session.

    Returns the new row's ``id``.
    Does NOT enforce the one-active-property rule — callers must call
    :func:`count_active_homes` and :func:`archive_home` before saving if
    the plan limit applies.
    """
    _ensure_schema()
    session_id = get_session_id()
    now = _now()

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO saved_homes (
                session_id, property_type, address, city, state, postal_code,
                display_name, monthly_rent, sale_price, bedrooms, bathrooms,
                square_feet, available_date, pets_policy, cooling, heating,
                parking, laundry, walk_score, transit_score, bike_score,
                days_on_zillow, hours_on_zillow, description,
                features_json, schools_json, warnings_json,
                is_active, is_archived, created_at, updated_at, raw_source_text
            ) VALUES (
                ?,?,?,?,?,?,
                ?,?,?,?,?,
                ?,?,?,?,?,
                ?,?,?,?,?,
                ?,?,?,
                ?,?,?,
                1, 0, ?, ?, ?
            )
            """,
            (
                session_id,
                _s(result.property_type, 32),
                _s(result.address, 255),
                _s(result.city, 128),
                _s(result.state, 64),
                _s(result.postal_code, 16),
                _s(result.display_name or result.address, 255),
                result.monthly_rent,
                result.sale_price,
                result.bedrooms,
                result.bathrooms,
                result.square_feet,
                _s(result.available_date, 128),
                _s(result.pets_policy, 255),
                _s(result.cooling, 255),
                _s(result.heating, 128),
                _s(result.parking, 255),
                _s(result.laundry, 128),
                result.walk_score,
                result.transit_score,
                result.bike_score,
                result.days_on_zillow,
                result.hours_on_zillow,
                _s(result.description, 4000),
                json.dumps(result.features or []),
                json.dumps(result.schools or []),
                json.dumps(result.warnings or []),
                now,
                now,
                _sanitize_raw_text(raw_source_text),
            ),
        )
        home_id = cur.lastrowid
        _log_event(conn, session_id, "saved", home_id)
        conn.commit()
    return home_id


def archive_home(home_id: int) -> None:
    """Mark a saved home as archived (inactive).

    Archived homes are hidden from normal access but never deleted.
    They can be restored after a plan upgrade.
    """
    _ensure_schema()
    session_id = get_session_id()
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE saved_homes
               SET is_active = 0, is_archived = 1, updated_at = ?
             WHERE id = ? AND session_id = ?
            """,
            (now, home_id, session_id),
        )
        _log_event(conn, session_id, "archived", home_id)
        conn.commit()


def restore_home(home_id: int) -> None:
    """Restore a previously archived home to active status."""
    _ensure_schema()
    session_id = get_session_id()
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE saved_homes
               SET is_active = 1, is_archived = 0, updated_at = ?
             WHERE id = ? AND session_id = ?
            """,
            (now, home_id, session_id),
        )
        _log_event(conn, session_id, "restored", home_id)
        conn.commit()


def count_active_homes() -> int:
    """Return the number of currently active (non-archived) saved homes."""
    _ensure_schema()
    session_id = get_session_id()
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM saved_homes WHERE session_id = ? AND is_active = 1 AND is_archived = 0",
            (session_id,),
        ).fetchone()
    return row[0] if row else 0


def list_active_homes() -> list[dict]:
    """Return active saved homes as a list of row dicts."""
    _ensure_schema()
    session_id = get_session_id()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM saved_homes
             WHERE session_id = ? AND is_active = 1 AND is_archived = 0
             ORDER BY created_at DESC
            """,
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_archived_homes() -> list[dict]:
    """Return archived homes as a list of row dicts."""
    _ensure_schema()
    session_id = get_session_id()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM saved_homes
             WHERE session_id = ? AND is_archived = 1
             ORDER BY updated_at DESC
            """,
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_home_by_id(home_id: int) -> Optional[dict]:
    """Return a single home record or None if not found / not owned by session."""
    _ensure_schema()
    session_id = get_session_id()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM saved_homes WHERE id = ? AND session_id = ?",
            (home_id, session_id),
        ).fetchone()
    return dict(row) if row else None


def get_oldest_active_home_id() -> Optional[int]:
    """Return the id of the oldest active saved home for replacement prompts."""
    _ensure_schema()
    session_id = get_session_id()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM saved_homes
             WHERE session_id = ? AND is_active = 1 AND is_archived = 0
             ORDER BY created_at ASC
             LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    return row["id"] if row else None


# ── Event log ─────────────────────────────────────────────────────────────────

def _log_event(conn: sqlite3.Connection, session_id: str, event_type: str,
               home_id: Optional[int] = None, meta: Optional[dict] = None) -> None:
    conn.execute(
        "INSERT INTO home_events (session_id, event_type, home_id, meta_json, created_at) VALUES (?,?,?,?,?)",
        (session_id, event_type, home_id, json.dumps(meta or {}), _now()),
    )
