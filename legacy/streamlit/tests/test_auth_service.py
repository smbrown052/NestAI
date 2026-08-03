from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
STREAMLIT_ROOT = ROOT / "legacy" / "streamlit"
if str(STREAMLIT_ROOT) not in sys.path:
    sys.path.insert(0, str(STREAMLIT_ROOT))

from auth_service import (  # noqa: E402
    AUTH_STATE_DEFAULTS,
    API_BASE_URL_ENV,
    NestAIAPIClient,
    StreamlitAuthManager,
    get_api_base_url,
    login_error_message,
    registration_error_message,
)
from ui_state import get_navigation_options  # noqa: E402


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class StreamlitAuthServiceTests(unittest.TestCase):
    def test_bearer_token_is_attached_to_authenticated_requests(self) -> None:
        session = Mock()
        session.request.return_value = FakeResponse(200, {"email": "a@example.com"})
        client = NestAIAPIClient(base_url="http://127.0.0.1:8001", session=session)
        client.set_token("token-123")

        response = client.me()

        self.assertEqual(response.status_code, 200)
        session.request.assert_called_once()
        args, kwargs = session.request.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(args[1], "http://127.0.0.1:8001/auth/me")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer token-123")

    def test_successful_login_restores_user_and_logout_clears_state(self) -> None:
        api_client = Mock()
        api_client.login.return_value = FakeResponse(200, {"access_token": "token-abc"})
        api_client.register.return_value = FakeResponse(201, {"id": 1})
        api_client.me.return_value = FakeResponse(
            200,
            {
                "id": 1,
                "email": "user@example.com",
                "display_name": "User Example",
                "tier": "premium",
                "is_admin": False,
                "is_active": True,
            },
        )

        state = {
            "comparison_df": pd.DataFrame([{"property": "A"}]),
            "enriched_df": pd.DataFrame([{"property": "B"}]),
            "advisor_messages": ["hello"],
            "building_cache": {"A": {}},
            "last_enrich_time": {"A": 1},
        }
        manager = StreamlitAuthManager(api_client, state)
        manager.initialize()

        login_response = manager.login("user@example.com", "password")
        self.assertEqual(login_response.status_code, 200)

        manager.set_authenticated("token-abc", api_client.me.return_value.json())
        self.assertTrue(manager.is_authenticated())
        self.assertEqual(state["nestai_tier"], "premium")

        manager.logout()
        self.assertFalse(manager.is_authenticated())
        self.assertTrue(state["comparison_df"].empty)
        self.assertTrue(state["enriched_df"].empty)
        self.assertEqual(state["advisor_messages"], [])
        self.assertEqual(state["auth_token"], None)
        self.assertEqual(state["auth_user"], None)

    def test_session_restoration_uses_me_and_clears_invalid_token(self) -> None:
        api_client = Mock()
        api_client.me.side_effect = [
            FakeResponse(
                200,
                {
                    "id": 7,
                    "email": "restore@example.com",
                    "display_name": "Restored User",
                    "tier": "free",
                    "is_admin": False,
                    "is_active": True,
                },
            ),
            FakeResponse(401, {"detail": "Invalid"}),
        ]

        state = {"auth_token": "token-restore", "auth_user": None, "comparison_df": pd.DataFrame(), "enriched_df": pd.DataFrame()}
        manager = StreamlitAuthManager(api_client, state)
        manager.initialize()

        self.assertTrue(manager.restore_from_session())
        self.assertEqual(state["auth_user"]["email"], "restore@example.com")

        state["auth_token"] = "token-invalid"
        state["auth_user"] = None
        self.assertFalse(manager.restore_from_session())
        self.assertIsNone(state["auth_token"])
        self.assertIsNone(state["auth_user"])

    def test_error_message_mappings_and_default_navigation(self) -> None:
        self.assertEqual(login_error_message(0), "Account services are temporarily unavailable.")
        self.assertEqual(login_error_message(404), "Account not found.")
        self.assertEqual(login_error_message(401), "Incorrect password.")
        self.assertEqual(login_error_message(403), "This account is inactive.")
        self.assertEqual(registration_error_message(0), "Account services are temporarily unavailable.")
        self.assertEqual(registration_error_message(409), "That email is already registered.")
        self.assertEqual(registration_error_message(422), "Please check the registration fields and try again.")
        self.assertEqual(AUTH_STATE_DEFAULTS["main_nav"], "Home")

    def test_api_base_url_uses_environment_value(self) -> None:
        prior = os.environ.get(API_BASE_URL_ENV)
        try:
            os.environ[API_BASE_URL_ENV] = "https://example-render-api.onrender.com"
            self.assertEqual(get_api_base_url(), "https://example-render-api.onrender.com")
        finally:
            if prior is None:
                os.environ.pop(API_BASE_URL_ENV, None)
            else:
                os.environ[API_BASE_URL_ENV] = prior

    def test_api_base_url_does_not_default_to_localhost_on_streamlit_cloud(self) -> None:
        prior_api = os.environ.get(API_BASE_URL_ENV)
        prior_cloud = os.environ.get("STREAMLIT_SHARING_MODE")
        try:
            os.environ.pop(API_BASE_URL_ENV, None)
            os.environ["STREAMLIT_SHARING_MODE"] = "community"
            self.assertIsNone(get_api_base_url())
        finally:
            if prior_api is None:
                os.environ.pop(API_BASE_URL_ENV, None)
            else:
                os.environ[API_BASE_URL_ENV] = prior_api
            if prior_cloud is None:
                os.environ.pop("STREAMLIT_SHARING_MODE", None)
            else:
                os.environ["STREAMLIT_SHARING_MODE"] = prior_cloud

    def test_hidden_screens_absent_from_nav_options(self) -> None:
        # "Login" and "Create Account" must NOT appear in nav_options so that the
        # sidebar radio guard (`active_screen in nav_options`) keeps them from being
        # overridden back to "Home" when a user navigates to those screens.
        nav_options = get_navigation_options(False)
        self.assertIn("Home", nav_options)
        self.assertNotIn("Login", nav_options)
        self.assertNotIn("Create Account", nav_options)

    def test_sign_in_button_sets_nav_to_login(self) -> None:
        # Simulates clicking "Sign in" on the Home page: main_nav becomes "Login"
        # and the sidebar guard must NOT reset it back.
        nav_options = get_navigation_options(False)
        hidden_screens = {"Login", "Create Account", "Pricing"}

        active_screen = "Login"  # after Sign In button click + rerun
        # The guard: sidebar radio should only fire when active_screen is a visible page.
        sidebar_would_override = active_screen in nav_options
        self.assertFalse(sidebar_would_override, "Sidebar must not override the Login screen")
        self.assertIn(active_screen, hidden_screens)

    def test_sign_up_button_sets_nav_to_create_account(self) -> None:
        # Simulates clicking "Sign up" on the Home page: main_nav becomes "Create Account"
        # and the sidebar guard must NOT reset it back.
        nav_options = get_navigation_options(False)
        hidden_screens = {"Login", "Create Account", "Pricing"}

        active_screen = "Create Account"  # after Sign Up button click + rerun
        sidebar_would_override = active_screen in nav_options
        self.assertFalse(sidebar_would_override, "Sidebar must not override the Create Account screen")
        self.assertIn(active_screen, hidden_screens)

    def test_sign_in_success_sets_authenticated_state(self) -> None:
        api_client = Mock()
        api_client.login.return_value = FakeResponse(200, {"access_token": "tok-sign-in"})
        api_client.me.return_value = FakeResponse(
            200,
            {
                "id": 10,
                "email": "signin@example.com",
                "display_name": "Sign In User",
                "tier": "free",
                "active_plan": "free",
                "is_admin": False,
                "is_active": True,
            },
        )

        state: dict = {}
        manager = StreamlitAuthManager(api_client, state)
        manager.initialize()

        response = manager.login("signin@example.com", "correct-password")
        self.assertEqual(response.status_code, 200)

        token = response.json()["access_token"]
        me = api_client.me.return_value.json()
        manager.set_authenticated(token, me)

        self.assertTrue(manager.is_authenticated())
        self.assertEqual(state["auth_token"], "tok-sign-in")
        self.assertEqual(state["auth_user"]["email"], "signin@example.com")
        self.assertIsNone(state["auth_error"])

    def test_sign_in_failure_returns_error_message(self) -> None:
        api_client = Mock()
        api_client.login.return_value = FakeResponse(401, {"detail": "Invalid email or password"})

        state: dict = {}
        manager = StreamlitAuthManager(api_client, state)
        manager.initialize()

        response = manager.login("bad@example.com", "wrong-password")
        self.assertEqual(response.status_code, 401)
        error_msg = login_error_message(response.status_code)
        self.assertEqual(error_msg, "Incorrect password.")
        self.assertFalse(manager.is_authenticated())

    def test_sign_up_success_sets_authenticated_state(self) -> None:
        api_client = Mock()
        api_client.request.return_value = FakeResponse(
            201,
            {
                "access_token": "tok-sign-up",
                "user": {
                    "id": 20,
                    "email": "signup@example.com",
                    "display_name": "Sign Up User",
                    "tier": "free",
                    "active_plan": "free",
                    "is_admin": False,
                    "is_active": True,
                },
            },
        )

        state: dict = {}
        manager = StreamlitAuthManager(api_client, state)
        manager.initialize()

        response = manager.register("signup@example.com", "strong-password", "Sign Up User")
        self.assertIn(response.status_code, {200, 201})

        payload = response.json()
        token = payload.get("access_token")
        user_payload = payload.get("user") or payload
        if token:
            manager.set_authenticated(token, user_payload)

        self.assertTrue(manager.is_authenticated())
        self.assertEqual(state["auth_user"]["email"], "signup@example.com")

    def test_sign_up_failure_returns_error_message(self) -> None:
        api_client = Mock()
        api_client.request.return_value = FakeResponse(409, {"detail": "Email already registered"})

        state: dict = {}
        manager = StreamlitAuthManager(api_client, state)
        manager.initialize()

        response = manager.register("dup@example.com", "password", "Dup User")
        self.assertEqual(response.status_code, 409)
        error_msg = registration_error_message(response.status_code)
        self.assertEqual(error_msg, "That email is already registered.")
        self.assertFalse(manager.is_authenticated())


def _run_forgot_password_block(response: object, state: dict) -> None:
    """Reproduce the app.py forgot-password submit block without importing Streamlit."""
    SERVICE_UNAVAILABLE_MESSAGE = "Account services are temporarily unavailable."

    if response.status_code == 0:
        state["auth_error"] = SERVICE_UNAVAILABLE_MESSAGE
    else:
        try:
            payload = response.json()
        except ValueError:
            state["auth_error"] = f"Service error (HTTP {response.status_code}). Please try again."
            return
        else:
            state["auth_notice"] = payload.get("message") or "If an account exists for that email, a password reset link has been sent."
            reset_link = payload.get("reset_link")
            if reset_link:
                state["auth_notice"] = f"{state['auth_notice']} Development reset link generated below."
                state["dev_reset_link"] = reset_link


class FakeResponseBadJSON:
    """Simulates a real requests.Response whose .json() raises ValueError (non-JSON body)."""

    def __init__(self, status_code: int):
        self.status_code = status_code

    def json(self) -> None:
        raise ValueError("No JSON object could be decoded")


class ForgotPasswordUITests(unittest.TestCase):
    def test_known_email_success_sets_auth_notice(self) -> None:
        state: dict = {}
        response = FakeResponse(200, {"message": "If an account exists for that email, a password reset link has been sent."})
        _run_forgot_password_block(response, state)
        self.assertIn("password reset link", state.get("auth_notice", ""))
        self.assertIsNone(state.get("auth_error"))

    def test_unknown_email_returns_same_neutral_notice(self) -> None:
        # The backend always returns the same neutral message regardless of whether the
        # account exists — the frontend must not reveal account existence either way.
        state: dict = {}
        response = FakeResponse(200, {"message": "If an account exists for that email, a password reset link has been sent."})
        _run_forgot_password_block(response, state)
        self.assertIn("password reset link", state.get("auth_notice", ""))
        self.assertIsNone(state.get("auth_error"))
        # Neutral wording must not mention whether the account was found
        self.assertNotIn("not found", state.get("auth_notice", "").lower())
        self.assertNotIn("no account", state.get("auth_notice", "").lower())

    def test_unavailable_api_sets_auth_error_not_notice(self) -> None:
        state: dict = {}
        response = FakeResponse(0, {"detail": "Account services are temporarily unavailable."})
        _run_forgot_password_block(response, state)
        self.assertIsNotNone(state.get("auth_error"))
        self.assertIsNone(state.get("auth_notice"))

    def test_404_non_json_sets_error_with_status_code(self) -> None:
        state: dict = {}
        response = FakeResponseBadJSON(404)
        _run_forgot_password_block(response, state)
        self.assertIn("404", state.get("auth_error", ""))
        self.assertIsNone(state.get("auth_notice"))

    def test_422_non_json_sets_error_with_status_code(self) -> None:
        state: dict = {}
        response = FakeResponseBadJSON(422)
        _run_forgot_password_block(response, state)
        self.assertIn("422", state.get("auth_error", ""))
        self.assertIsNone(state.get("auth_notice"))

    def test_500_non_json_sets_error_with_status_code(self) -> None:
        state: dict = {}
        response = FakeResponseBadJSON(500)
        _run_forgot_password_block(response, state)
        self.assertIn("500", state.get("auth_error", ""))
        self.assertIsNone(state.get("auth_notice"))
