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
        self.assertEqual(login_error_message(401), "Invalid email or password.")
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
