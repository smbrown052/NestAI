"""
auth_client.py — Thin HTTP client for the NestAI FastAPI auth endpoints.

Reads NESTAI_API_URL from Streamlit secrets.  All functions return a
(data, error_message) tuple.  When the API is unreachable or not configured,
the error message explains what happened so the UI can show a friendly note.
"""

from __future__ import annotations

from typing import Any

import requests
import streamlit as st


# ── Internal helpers ──────────────────────────────────────────────────────────

def _api_url() -> str | None:
    """Return the configured API base URL, or None if not set."""
    try:
        url = st.secrets.get("NESTAI_API_URL", "").rstrip("/")
        return url if url else None
    except Exception:
        return None


def _post(path: str, payload: dict, token: str | None = None) -> tuple[dict | None, str | None]:
    base = _api_url()
    if not base:
        return None, "Authentication service not configured."
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"******"
    try:
        resp = requests.post(f"{base}{path}", json=payload, headers=headers, timeout=10)
        if resp.ok:
            return resp.json(), None
        detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        return None, str(detail)
    except requests.ConnectionError:
        return None, "Could not connect to the authentication service."
    except Exception as exc:
        return None, f"Unexpected error: {exc}"


def _get(path: str, token: str | None = None, params: dict | None = None) -> tuple[Any, str | None]:
    base = _api_url()
    if not base:
        return None, "Authentication service not configured."
    headers = {}
    if token:
        headers["Authorization"] = f"******"
    try:
        resp = requests.get(f"{base}{path}", headers=headers, params=params, timeout=10)
        if resp.ok:
            return resp.json(), None
        detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        return None, str(detail)
    except requests.ConnectionError:
        return None, "Could not connect to the authentication service."
    except Exception as exc:
        return None, f"Unexpected error: {exc}"


def _patch(path: str, payload: dict, token: str | None = None) -> tuple[dict | None, str | None]:
    base = _api_url()
    if not base:
        return None, "Authentication service not configured."
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"******"
    try:
        resp = requests.patch(f"{base}{path}", json=payload, headers=headers, timeout=10)
        if resp.ok:
            return resp.json(), None
        detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        return None, str(detail)
    except requests.ConnectionError:
        return None, "Could not connect to the authentication service."
    except Exception as exc:
        return None, f"Unexpected error: {exc}"


# ── Public API ────────────────────────────────────────────────────────────────

def login(email: str, password: str) -> tuple[dict | None, str | None]:
    """Authenticate and return {access_token, token_type} or error."""
    return _post("/auth/login", {"email": email, "password": password})


def register(email: str, password: str, display_name: str = "") -> tuple[dict | None, str | None]:
    """Create a new account and return the token data or error."""
    payload: dict = {"email": email, "password": password}
    if display_name:
        payload["display_name"] = display_name
    return _post("/auth/register", payload)


def get_me(token: str) -> tuple[dict | None, str | None]:
    """Return the current authenticated user's profile."""
    return _get("/auth/me", token=token)


def update_profile(token: str, display_name: str | None = None) -> tuple[dict | None, str | None]:
    """Update display name or other patchable user fields."""
    payload: dict = {}
    if display_name is not None:
        payload["display_name"] = display_name
    return _patch("/users/me", payload, token=token)


def request_password_reset(email: str) -> tuple[dict | None, str | None]:
    """Request a password-reset email."""
    return _post("/auth/password-reset-request", {"email": email})


def confirm_password_reset(token: str, new_password: str) -> tuple[dict | None, str | None]:
    """Confirm a password reset with the token received by email."""
    return _post("/auth/password-reset", {"token": token, "new_password": new_password})


def accept_beta_invite(invite_token: str, password: str, display_name: str = "") -> tuple[dict | None, str | None]:
    """Complete registration from a beta invitation link."""
    payload: dict = {"token": invite_token, "password": password}
    if display_name:
        payload["display_name"] = display_name
    return _post("/auth/accept-invite", payload)


# ── Admin helpers ─────────────────────────────────────────────────────────────

def admin_get_users(token: str, search: str = "", skip: int = 0, limit: int = 50) -> tuple[Any, str | None]:
    return _get("/admin/users", token=token, params={"search": search, "skip": skip, "limit": limit})


def admin_get_overview(token: str) -> tuple[dict | None, str | None]:
    return _get("/admin/", token=token)


def admin_get_feedback(token: str, status_filter: str = "", skip: int = 0, limit: int = 50) -> tuple[Any, str | None]:
    params: dict = {"skip": skip, "limit": limit}
    if status_filter:
        params["status"] = status_filter
    return _get("/admin/feedback", token=token, params=params)


def admin_user_action(token: str, user_id: int, action: str, body: dict | None = None) -> tuple[dict | None, str | None]:
    base = _api_url()
    if not base:
        return None, "Authentication service not configured."
    headers = {"Authorization": f"******", "Content-Type": "application/json"}
    try:
        resp = requests.post(
            f"{base}/admin/users/{user_id}/{action}",
            json=body or {},
            headers=headers,
            timeout=10,
        )
        if resp.ok:
            return resp.json(), None
        detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        return None, str(detail)
    except Exception as exc:
        return None, f"Unexpected error: {exc}"


def admin_invite_beta(token: str, payload: dict) -> tuple[dict | None, str | None]:
    return _post("/admin/beta/invite", payload, token=token)


def admin_get_beta_users(token: str) -> tuple[Any, str | None]:
    return _get("/admin/beta/users", token=token)


def admin_get_beta_invitations(token: str) -> tuple[Any, str | None]:
    return _get("/admin/beta/invitations", token=token)


def admin_update_feedback(token: str, feedback_id: int, payload: dict) -> tuple[dict | None, str | None]:
    return _patch(f"/admin/feedback/{feedback_id}", payload, token=token)


def admin_get_billing(token: str) -> tuple[dict | None, str | None]:
    return _get("/admin/billing/overview", token=token)


def admin_get_analytics(token: str, days: int = 30) -> tuple[dict | None, str | None]:
    return _get("/admin/analytics/overview", token=token, params={"days": days})


def admin_get_audit_log(token: str, skip: int = 0, limit: int = 50) -> tuple[Any, str | None]:
    return _get("/admin/audit-log", token=token, params={"skip": skip, "limit": limit})


def admin_get_ai_costs(token: str, days: int = 30) -> tuple[dict | None, str | None]:
    return _get("/admin/ai-costs", token=token, params={"days": days})
