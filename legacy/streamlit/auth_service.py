"""Streamlit auth helpers for NestAI."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import socket
import secrets
import time
from typing import Any, Mapping

import requests

DEFAULT_API_BASE_URL = "http://127.0.0.1:8001"
API_BASE_URL_ENV = "NESTAI_API_BASE_URL"
SERVICE_UNAVAILABLE_MESSAGE = "Account services are temporarily unavailable."
API_REQUEST_TIMEOUT_SECONDS = 20
API_HEALTH_TIMEOUT_SECONDS = 3
API_HEALTH_TTL_SECONDS = 20

logger = logging.getLogger(__name__)

AUTH_STATE_DEFAULTS = {
    "auth_token": None,
    "auth_user": None,
    "auth_notice": None,
    "auth_error": None,
    "main_nav": "Apartments",
    "signup_account_type": "free",
    "pending_checkout_session_id": None,
    "pending_checkout_url": None,
    "api_available": True,
    "api_last_health_check": 0.0,
}


def login_error_message(status_code: int) -> str:
    if status_code == 0:
        return SERVICE_UNAVAILABLE_MESSAGE
    if status_code == 401:
        return "Invalid email or password."
    return "Could not sign in right now. Please try again."


def registration_error_message(status_code: int) -> str:
    if status_code == 0:
        return SERVICE_UNAVAILABLE_MESSAGE
    if status_code == 409:
        return "That email is already registered."
    if status_code == 422:
        return "Please check the registration fields and try again."
    return "Could not create the account right now. Please try again."


def _streamlit_secret_value(key: str) -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(key)
    except Exception:
        return None
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _looks_like_streamlit_cloud() -> bool:
    markers = [
        os.getenv("STREAMLIT_SHARING_MODE", ""),
        os.getenv("STREAMLIT_RUNTIME", ""),
        os.getenv("IS_STREAMLIT_CLOUD", ""),
    ]
    for marker in markers:
        value = marker.strip().lower()
        if value in {"1", "true", "yes", "cloud", "community", "streamlit_cloud"}:
            return True
    hostname = socket.gethostname().lower()
    if "streamlit" in hostname and "app" in hostname:
        return True
    return False


def payment_required_message(plan: str) -> str:
    normalized = (plan or "free").strip().lower().replace(" ", "_").replace("-", "_")
    if normalized == "premium_plus":
        return "Payment required to activate Premium Plus"
    return "Payment required to activate Premium"


def billing_webhook_secret() -> str:
    return os.getenv("BILLING_WEBHOOK_SECRET") or os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY") or ""


def sign_webhook_payload(raw_payload: bytes) -> str:
    secret = billing_webhook_secret()
    if not secret:
        raise RuntimeError("BILLING_WEBHOOK_SECRET or JWT_SECRET_KEY is required for payment confirmation")
    return hmac.new(secret.encode("utf-8"), raw_payload, hashlib.sha256).hexdigest()


def get_api_base_url() -> str | None:
    secret_value = _streamlit_secret_value(API_BASE_URL_ENV)
    if secret_value:
        return secret_value.rstrip("/")
    env_value = os.getenv(API_BASE_URL_ENV, "").strip()
    if env_value:
        return env_value.rstrip("/")
    if _looks_like_streamlit_cloud():
        return None
    return DEFAULT_API_BASE_URL


class APIErrorResponse:
    def __init__(self, message: str = SERVICE_UNAVAILABLE_MESSAGE):
        self.status_code = 0
        self._payload = {"detail": message}

    def json(self) -> dict[str, Any]:
        return self._payload


class NestAIAPIClient:
    """Thin API client that attaches the bearer token when available."""

    def __init__(self, base_url: str | None = None, session: requests.Session | None = None):
        resolved = base_url if base_url is not None else get_api_base_url()
        self.base_url = resolved.rstrip("/") if resolved else None
        self.session = session or requests.Session()
        self.access_token: str | None = None

    def set_token(self, token: str | None) -> None:
        self.access_token = token

    def clear_token(self) -> None:
        self.access_token = None

    def _url(self, path: str) -> str:
        if not self.base_url:
            return ""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    def request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> requests.Response:
        if not self.base_url:
            logger.warning("API request skipped because %s is not configured", API_BASE_URL_ENV)
            return APIErrorResponse()
        headers: dict[str, str] = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            return self.session.request(
                method,
                self._url(path),
                json=json,
                headers=headers,
                timeout=API_REQUEST_TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout, requests.RequestException) as exc:
            logger.warning("API request failed for %s %s: %s", method, path, exc.__class__.__name__)
            return APIErrorResponse()

    def health_check(self) -> bool:
        if not self.base_url:
            logger.warning("API health check skipped because %s is not configured", API_BASE_URL_ENV)
            return False
        try:
            response = self.session.get(
                self._url("/health"),
                timeout=API_HEALTH_TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout, requests.RequestException) as exc:
            logger.warning("API health check failed: %s", exc.__class__.__name__)
            return False
        return response.status_code == 200

    def register(self, email: str, password: str, display_name: str) -> requests.Response:
        return self.request(
            "POST",
            "/auth/register",
            json={"email": email, "password": password, "display_name": display_name},
        )

    def login(self, email: str, password: str) -> requests.Response:
        return self.request("POST", "/auth/login", json={"email": email, "password": password})

    def me(self) -> requests.Response:
        return self.request("GET", "/auth/me")

    def create_checkout_session(self, plan: str) -> requests.Response:
        return self.request("POST", "/billing/create-checkout-session", json={"plan": plan})

    def billing_status(self) -> requests.Response:
        return self.request("GET", "/billing/status")

    def confirm_payment(self, checkout_session_id: str, requested_plan: str) -> requests.Response:
        event_payload = {
            "event_id": f"evt_{secrets.token_urlsafe(16)}",
            "event_type": "payment_succeeded",
            "checkout_session_id": checkout_session_id,
            "payment_customer_id": f"cus_{secrets.token_urlsafe(12)}",
            "payment_subscription_id": f"sub_{secrets.token_urlsafe(12)}",
            "requested_plan": requested_plan,
        }
        raw_payload = json.dumps(event_payload).encode("utf-8")
        signature = sign_webhook_payload(raw_payload)
        response = self.session.request(
            "POST",
            self._url("/billing/webhook"),
            data=raw_payload,
            headers={"Content-Type": "application/json", "X-NestAI-Signature": signature},
            timeout=20,
        )
        return response


class StreamlitAuthManager:
    def __init__(self, api_client: NestAIAPIClient, state: Mapping[str, Any] | None = None):
        self.api_client = api_client
        self.state = state if state is not None else None

    @property
    def _session_state(self):
        if self.state is None:
            import streamlit as st

            return st.session_state
        return self.state

    def initialize(self) -> None:
        session_state = self._session_state
        for key, default in AUTH_STATE_DEFAULTS.items():
            if key not in session_state:
                session_state[key] = default

    def is_api_available(self, force: bool = False) -> bool:
        session_state = self._session_state
        now = time.time()
        last_check = float(session_state.get("api_last_health_check") or 0.0)
        if not force and (now - last_check) < API_HEALTH_TTL_SECONDS:
            return bool(session_state.get("api_available", True))
        available = self.api_client.health_check()
        session_state["api_available"] = available
        session_state["api_last_health_check"] = now
        return available

    def is_authenticated(self) -> bool:
        session_state = self._session_state
        return bool(session_state.get("auth_token") and session_state.get("auth_user"))

    def user(self) -> dict[str, Any] | None:
        user = self._session_state.get("auth_user")
        return dict(user) if isinstance(user, dict) else user

    def set_authenticated(self, token: str, user: dict[str, Any]) -> None:
        session_state = self._session_state
        session_state["auth_token"] = token
        session_state["auth_user"] = user
        session_state["auth_error"] = None
        session_state["auth_notice"] = None
        session_state["nestai_tier"] = user.get("active_plan") or user.get("tier", "free")
        self.api_client.set_token(token)

    def clear_authenticated(self) -> None:
        session_state = self._session_state
        session_state["auth_token"] = None
        session_state["auth_user"] = None
        session_state["nestai_tier"] = "free"
        session_state["paid_features_enabled"] = False
        session_state["pending_checkout_session_id"] = None
        session_state["pending_checkout_url"] = None
        self.api_client.clear_token()

    def restore_from_session(self) -> bool:
        token = self._session_state.get("auth_token")
        if not token:
            return False
        self.api_client.set_token(token)
        response = self.api_client.me()
        if response.status_code == 0:
            self._session_state["api_available"] = False
            return False
        if response.status_code != 200:
            self.clear_authenticated()
            return False
        self.set_authenticated(token, response.json())
        billing = self.refresh_billing_status()
        if billing:
            self.store_checkout(billing.get("checkout_session_id"), None)
        return True

    def sync_user_tier(self) -> None:
        user = self.user()
        if user:
            self._session_state["nestai_tier"] = user.get("active_plan") or user.get("tier", "free")

    def logout(self) -> None:
        self.clear_authenticated()
        session_state = self._session_state
        comparison_df = session_state.get("comparison_df")
        enriched_df = session_state.get("enriched_df")
        session_state["comparison_df"] = comparison_df.iloc[0:0] if hasattr(comparison_df, "iloc") else comparison_df
        session_state["enriched_df"] = enriched_df.iloc[0:0] if hasattr(enriched_df, "iloc") else enriched_df
        session_state["enrichment_done"] = False
        session_state["negotiation_outputs"] = {}
        session_state["building_cache"] = {}
        session_state["last_enrich_time"] = {}
        session_state["advisor_messages"] = []

    def login(self, email: str, password: str) -> requests.Response:
        return self.api_client.login(email, password)

    def register(self, email: str, password: str, display_name: str, account_type: str = "free", beta_invite_code: str | None = None) -> requests.Response:
        payload = {
            "email": email,
            "password": password,
            "display_name": display_name,
            "account_type": account_type,
            "beta_invite_code": beta_invite_code,
        }
        return self.api_client.request("POST", "/auth/register", json=payload)

    def fetch_current_user(self) -> requests.Response:
        return self.api_client.me()

    def store_checkout(self, checkout_session_id: str | None, checkout_url: str | None) -> None:
        session_state = self._session_state
        session_state["pending_checkout_session_id"] = checkout_session_id
        session_state["pending_checkout_url"] = checkout_url

    def refresh_billing_status(self) -> dict[str, Any] | None:
        response = self.api_client.billing_status()
        if response.status_code != 200:
            if response.status_code == 0:
                self._session_state["api_available"] = False
            return None
        status_payload = response.json()
        self.store_checkout(status_payload.get("checkout_session_id"), status_payload.get("checkout_url"))
        self._session_state["api_available"] = True
        return status_payload

    def confirm_pending_payment(self) -> bool:
        session_id = self._session_state.get("pending_checkout_session_id")
        user = self.user() or {}
        requested_plan = user.get("requested_plan") or self._session_state.get("signup_account_type")
        if not session_id or not requested_plan:
            return False
        response = self.api_client.confirm_payment(session_id, requested_plan)
        if response.status_code != 200:
            if response.status_code == 0:
                self._session_state["api_available"] = False
            return False
        refreshed = self.fetch_current_user()
        if refreshed.status_code == 200:
            self.set_authenticated(self._session_state.get("auth_token"), refreshed.json())
        self._session_state["pending_checkout_session_id"] = None
        self._session_state["pending_checkout_url"] = None
        return True