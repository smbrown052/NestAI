"""
feedback.py
NestAI feedback, bug reporting, and beta-access layer.

All feedback is persisted in the same SQLite database used by the rest of
the app (data/nestai_cache.db).  A public reference like NEST-1042 is
generated for every submission so users can track their report without
exposing the raw sequential row id.

Public API
----------
submit_feedback(payload)   -> str          public ref e.g. "NEST-1042"
send_feedback_email(...)                   degrades gracefully if SMTP not configured
validate_beta_code(code)   -> bool         checks against BETA_CODES secret
"""

import html
import smtplib
import sqlite3
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import streamlit as st

# ── Database path (shared with cache.py) ─────────────────────────────────────

_DB_PATH = Path(__file__).parent / "data" / "nestai_cache.db"

# ── Schema ────────────────────────────────────────────────────────────────────

_FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback_reports (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    public_reference        TEXT UNIQUE,
    user_id                 TEXT,
    category                TEXT NOT NULL,
    title                   TEXT NOT NULL,
    description             TEXT,
    actual_behavior         TEXT,
    expected_behavior       TEXT,
    requested_feature       TEXT,
    problem_to_solve        TEXT,
    value_rating            TEXT,
    what_were_you_doing     TEXT,
    what_was_unclear        TEXT,
    platform                TEXT,
    app_version             TEXT,
    build_number            TEXT,
    route_or_screen         TEXT,
    browser                 TEXT,
    operating_system        TEXT,
    device_model            TEXT,
    comparison_id           TEXT,
    building_id             TEXT,
    unit_id                 TEXT,
    ai_report_id            TEXT,
    error_correlation_id    TEXT,
    contact_email           TEXT,
    user_contact_allowed    INTEGER DEFAULT 0,
    attachment_url          TEXT,
    user_plan               TEXT,
    beta_tester             INTEGER DEFAULT 0,
    unit_count              INTEGER,
    building_count          INTEGER,
    status                  TEXT DEFAULT 'new',
    severity                TEXT,
    priority                TEXT,
    duplicate_of_feedback_id INTEGER,
    internal_notes          TEXT,
    created_at              TEXT,
    updated_at              TEXT,
    resolved_at             TEXT
);

CREATE INDEX IF NOT EXISTS idx_feedback_ref      ON feedback_reports (public_reference);
CREATE INDEX IF NOT EXISTS idx_feedback_category ON feedback_reports (category);
CREATE INDEX IF NOT EXISTS idx_feedback_status   ON feedback_reports (status);
"""

_ALLOWED_CATEGORIES = {"bug", "feature_request", "improvement", "confusing_experience"}
_ALLOWED_STATUSES = {
    "new", "triaged", "planned", "investigating", "in_progress",
    "fixed", "completed", "closed", "duplicate", "unable_to_reproduce", "declined",
}
_ALLOWED_SEVERITIES = {"low", "normal", "high", "critical"}
_ALLOWED_PRIORITIES = {"low", "medium", "high", "urgent"}
_ALLOWED_VALUE_RATINGS = {
    "nice_to_have",
    "use_occasionally",
    "use_every_search",
    "might_not_use_without",
}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_table() -> None:
    with _connect() as conn:
        conn.executescript(_FEEDBACK_SCHEMA)
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Public reference generation ───────────────────────────────────────────────

def _generate_public_ref(conn: sqlite3.Connection) -> str:
    """Generate NEST-XXXX where XXXX avoids guessable low numbers."""
    row = conn.execute("SELECT MAX(id) FROM feedback_reports").fetchone()
    max_id = row[0] if row and row[0] is not None else 0
    ref_num = max_id + 1 + 1000  # offset to avoid NEST-1, NEST-2 etc.
    return f"NEST-{ref_num}"


# ── Input sanitisation ────────────────────────────────────────────────────────

def _sanitize(value: str | None, max_len: int = 4000) -> str:
    """Escape HTML entities and truncate to prevent injection or oversized blobs."""
    if not value:
        return ""
    return html.escape(str(value).strip())[:max_len]


def _sanitize_email(email: str | None) -> str:
    if not email:
        return ""
    email = email.strip()[:254]
    # Simple structural check: one @, non-empty local and domain, a dot in domain.
    # Avoids backtracking-heavy patterns on user-supplied input.
    at_idx = email.find("@")
    if at_idx < 1 or at_idx == len(email) - 1:
        return ""
    local = email[:at_idx]
    domain = email[at_idx + 1:]
    if " " in local or " " in domain:
        return ""
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        return ""
    return email


# ── Secrets helper ────────────────────────────────────────────────────────────

def _secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default) or default
    except Exception:
        return default


# ── Submit ────────────────────────────────────────────────────────────────────

def submit_feedback(payload: dict) -> str:
    """
    Validate, sanitise, persist, and return the public reference for a
    feedback submission.

    Required keys in payload:
        category  – one of bug | feature_request | improvement | confusing_experience
        title     – short summary (non-empty)

    All other keys are optional; unknown keys are ignored.
    """
    _ensure_table()

    category = str(payload.get("category", "")).strip().lower()
    if category not in _ALLOWED_CATEGORIES:
        raise ValueError(f"Invalid category: {category!r}")

    title = _sanitize(payload.get("title"), 300)
    if not title:
        raise ValueError("title is required")

    now = _now_iso()

    with _connect() as conn:
        ref = _generate_public_ref(conn)
        conn.execute(
            """
            INSERT INTO feedback_reports (
                public_reference, user_id, category, title, description,
                actual_behavior, expected_behavior,
                requested_feature, problem_to_solve, value_rating,
                what_were_you_doing, what_was_unclear,
                platform, app_version, build_number, route_or_screen,
                browser, operating_system, device_model,
                comparison_id, building_id, unit_id, ai_report_id,
                error_correlation_id,
                contact_email, user_contact_allowed, attachment_url,
                user_plan, beta_tester, unit_count, building_count,
                status, severity, priority, created_at, updated_at
            ) VALUES (
                ?,?,?,?,?,
                ?,?,
                ?,?,?,
                ?,?,
                ?,?,?,?,
                ?,?,?,
                ?,?,?,?,
                ?,
                ?,?,?,
                ?,?,?,?,
                ?,?,?,?,?
            )
            """,
            (
                ref,
                _sanitize(payload.get("user_id"), 128),
                category,
                title,
                _sanitize(payload.get("description")),
                _sanitize(payload.get("actual_behavior")),
                _sanitize(payload.get("expected_behavior")),
                _sanitize(payload.get("requested_feature")),
                _sanitize(payload.get("problem_to_solve")),
                str(payload.get("value_rating", "")) or None,
                _sanitize(payload.get("what_were_you_doing")),
                _sanitize(payload.get("what_was_unclear")),
                _sanitize(payload.get("platform"), 64),
                _sanitize(payload.get("app_version"), 32),
                _sanitize(payload.get("build_number"), 32),
                _sanitize(payload.get("route_or_screen"), 128),
                _sanitize(payload.get("browser"), 128),
                _sanitize(payload.get("operating_system"), 128),
                _sanitize(payload.get("device_model"), 128),
                _sanitize(payload.get("comparison_id"), 64),
                _sanitize(payload.get("building_id"), 64),
                _sanitize(payload.get("unit_id"), 64),
                _sanitize(payload.get("ai_report_id"), 64),
                _sanitize(payload.get("error_correlation_id"), 64),
                _sanitize_email(payload.get("contact_email")),
                1 if payload.get("user_contact_allowed") else 0,
                _sanitize(payload.get("attachment_url"), 512),
                _sanitize(payload.get("user_plan"), 32),
                1 if payload.get("beta_tester") else 0,
                int(payload["unit_count"]) if payload.get("unit_count") is not None else None,
                int(payload["building_count"]) if payload.get("building_count") is not None else None,
                "new",
                str(payload.get("severity", "")) or None,
                str(payload.get("priority", "")) or None,
                now,
                now,
            ),
        )
        conn.commit()

    return ref


# ── Email notification ────────────────────────────────────────────────────────

def send_feedback_email(payload: dict, ref: str) -> None:
    """
    Send an email notification via SMTP.  Requires the following Streamlit
    secrets to be configured; silently skips if any are missing:

        SMTP_HOST     – e.g. smtp.sendgrid.net
        SMTP_PORT     – e.g. 587
        SMTP_USER     – sender username / API key name
        SMTP_PASS     – sender password / API key
        FEEDBACK_EMAIL – destination address, e.g. feedback@nestai.app
    """
    host = _secret("SMTP_HOST")
    port_str = _secret("SMTP_PORT", "587")
    user = _secret("SMTP_USER")
    password = _secret("SMTP_PASS")
    dest = _secret("FEEDBACK_EMAIL")

    if not all([host, user, password, dest]):
        return  # SMTP not configured; email silently skipped

    try:
        port = int(port_str)
    except ValueError:
        port = 587

    category = payload.get("category", "").replace("_", " ").title()
    title = payload.get("title", "(no title)")
    body_lines = [
        f"Reference: {ref}",
        f"Category: {category}",
        f"Title: {title}",
        "",
        f"Description:\n{payload.get('description', '')}",
        "",
        f"Plan: {payload.get('user_plan', 'unknown')}",
        f"Beta tester: {bool(payload.get('beta_tester', False))}",
        f"Platform: {payload.get('platform', '')}",
        f"App version: {payload.get('app_version', '')}",
        f"Units in comparison: {payload.get('unit_count', '')}",
        f"Buildings in comparison: {payload.get('building_count', '')}",
    ]
    if payload.get("contact_email") and payload.get("user_contact_allowed"):
        body_lines.append(f"\nContact: {payload['contact_email']}")

    body = "\n".join(body_lines)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[NestAI Feedback] {ref} — {category}: {title[:60]}"
    msg["From"] = f"NestAI Notifications <{user}>"
    msg["To"] = dest

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
    except Exception:
        # Email failure must never crash the feedback submission flow
        pass


# ── Beta access ───────────────────────────────────────────────────────────────

def validate_beta_code(code: str) -> bool:
    """
    Return True when *code* matches one of the comma-separated codes stored in
    the BETA_CODES Streamlit secret.  Comparison is case-insensitive and
    whitespace-trimmed.
    """
    if not code or not code.strip():
        return False

    raw = _secret("BETA_CODES", "")
    if not raw:
        return False

    valid_codes = {c.strip().lower() for c in raw.split(",") if c.strip()}
    return code.strip().lower() in valid_codes
