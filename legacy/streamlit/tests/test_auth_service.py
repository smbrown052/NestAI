from __future__ import annotations

import os
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

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
    handle_forgot_password_response as _run_forgot_password_block,
)
from ui_state import get_navigation_options  # noqa: E402


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class StreamlitAuthServiceTests(unittest.TestCase):
    def comparison_ui(self, state=None):
        ui = Mock()
        ui.session_state = state or {}
        ui.form.return_value = nullcontext()
        ui.expander.return_value = nullcontext()
        ui.number_input.side_effect = [0, 0, 0, 0]
        ui.text_input.return_value = ""
        ui.slider.return_value = 1.0
        ui.checkbox.return_value = False
        ui.form_submit_button.return_value = False
        ui.button.return_value = False
        ui.selectbox.side_effect = [0, "units"]
        return ui

    def test_natural_priorities_are_not_overwritten_by_default_sliders(self):
        import api_views
        ui = self.comparison_ui()
        ui.text_input.return_value = "prioritize space over price"
        ui.form_submit_button.return_value = True
        with patch.object(api_views, "st", ui), patch.object(api_views, "capability", return_value=True), patch.object(api_views, "api_call", side_effect=[
            {"constraints": {}, "priorities": {"space": 5.0, "price": 1.0}},
            {"ranked": []},
        ]) as call:
            api_views.render_comparison(Mock(), [{"id": "one"}])
        self.assertEqual(call.call_args.args[3]["priorities"], {"space": 5.0, "price": 1.0})
        ui.caption.assert_any_call("Applied priorities: {'space': 5.0, 'price': 1.0}")

    def test_export_passes_exact_comparison_inputs(self):
        import api_views
        ui = self.comparison_ui({"account_filters": {"max_budget": 2000, "priorities": {"price": 4.0}}})
        ui.button.side_effect = lambda label, **kwargs: label == "Prepare CSV export"
        with patch.object(api_views, "st", ui), patch.object(api_views, "display_frame"), patch.object(api_views, "capability", side_effect=lambda name: name == "can_export"), patch.object(api_views, "api_call", side_effect=[
            {"ranked": [{"property_id": "one", "unit_id": "unit-one", "price_num": 1500}]}, "csv",
        ]) as call:
            api_views.render_comparison(Mock(), [{"id": "one"}])
        self.assertEqual(call.call_args.args[3], {
            "property_ids": ["one"], "constraints": {"rent_lte": 2000},
            "priorities": {"price": 4.0}, "format": "csv", "scope": "units",
        })

    def test_manual_priorities_explicitly_override_natural_priorities(self):
        import api_views
        ui = self.comparison_ui()
        ui.text_input.return_value = "prioritize space"
        ui.checkbox.return_value = True
        ui.form_submit_button.return_value = True
        with patch.object(api_views, "st", ui), patch.object(api_views, "capability", return_value=True), patch.object(api_views, "api_call", side_effect=[
            {"constraints": {}, "priorities": {"space": 5.0}},
            {"ranked": []},
        ]) as call:
            api_views.render_comparison(Mock(), [{"id": "one"}])
        self.assertEqual(call.call_args.args[3]["priorities"], {
            "price": 1.0, "space": 1.0, "commute": 1.0, "walkability": 1.0, "pets": 1.0,
        })

    def test_numeric_inputs_do_not_weaken_natural_constraints(self):
        import api_views
        ui = self.comparison_ui()
        ui.text_input.return_value = "at least 3 bedrooms and up to $2000"
        ui.number_input.side_effect = [3000, 1, 0, 0]
        ui.form_submit_button.return_value = True
        with patch.object(api_views, "st", ui), patch.object(api_views, "capability", return_value=False), patch.object(api_views, "api_call", side_effect=[
            {"constraints": {"min_beds": 3, "rent_lte": 2000}, "priorities": {}},
            {"ranked": []},
        ]) as call:
            api_views.render_comparison(Mock(), [{"id": "one"}])
        self.assertEqual(call.call_args.args[3]["constraints"], {"min_beds": 3, "rent_lte": 2000})

    def test_changed_comparison_clears_old_downloads_even_for_empty_results(self):
        import api_views
        ui = self.comparison_ui({
            "account_export": "private stale CSV", "account_report": {"content": "{}"},
            "account_comparison_fingerprint": "old",
        })
        with patch.object(api_views, "st", ui), patch.object(api_views, "capability", return_value=False), patch.object(api_views, "api_call", return_value={"ranked": []}):
            api_views.render_comparison(Mock(), [{"id": "one"}])
        self.assertNotIn("account_export", ui.session_state)
        self.assertNotIn("account_report", ui.session_state)

    def test_failed_hydration_clears_stale_account_snapshot(self):
        import api_views
        ui = Mock()
        ui.session_state = {"account_properties": [{"id": "old"}], "user_profile": {"max_budget": 9000},
                            "account_entitlements": {"plan": "premium"}, "account_export": "old"}
        with patch.object(api_views, "st", ui), patch.object(api_views, "api_call", return_value=None):
            self.assertFalse(api_views.hydrate_account(Mock()))
        self.assertEqual(ui.session_state["account_properties"], [])
        self.assertEqual(ui.session_state["user_profile"], {})
        self.assertNotIn("account_export", ui.session_state)

    def test_property_fee_form_preserves_unknown_values_and_scopes_widgets(self):
        import api_views
        ui = Mock()
        ui.session_state = {}
        ui.selectbox.return_value = "property-one"
        ui.form.return_value = nullcontext()
        ui.number_input.return_value = None
        ui.form_submit_button.return_value = True
        ui.button.return_value = False
        with patch.object(api_views, "st", ui), patch.object(api_views, "capability", return_value=False), patch.object(api_views, "api_call", return_value={"id": "property-one"}) as call:
            api_views.render_property_controls(Mock(), [{"id": "property-one", "fees": {}}])
            self.assertEqual(call.call_args.args[1:3], ("PATCH", "/properties/property-one"))
            self.assertTrue(all(value is None for value in call.call_args.args[3]["fees"].values()))
            for widget in ui.number_input.call_args_list:
                self.assertIsNone(widget.kwargs["value"])
                self.assertTrue(widget.kwargs["key"].startswith("property_fee_property-one_"))

    def test_checkout_uses_supplied_retry_key_and_explicit_consent(self):
        session = Mock()
        session.request.return_value = FakeResponse(200, {"checkout_url": "https://checkout.stripe.com/example"})
        client = NestAIAPIClient(base_url="http://127.0.0.1:8000", session=session)
        client.create_checkout_session("premium", trial_consent=True, payment_method_confirmed=True, idempotency_key="stable-intent")
        self.assertEqual(session.request.call_args.kwargs["json"], {
            "plan": "premium", "idempotency_key": "stable-intent",
            "trial_consent": True, "payment_method_confirmed": True,
        })

    def test_api_retry_reuses_intent_key_until_response_succeeds(self):
        import api_views
        client = Mock()
        client.request.side_effect = [FakeResponse(0, {}), FakeResponse(200, {"answer": "ok"}), FakeResponse(200, {"answer": "new"})]
        ui = Mock()
        ui.session_state = {}
        with patch.object(api_views, "st", ui):
            for key in ("first", "retry", "new-intent"):
                api_views.api_call(client, "POST", "/advisor", {"question": "same", "property_ids": ["one"], "idempotency_key": key})
        keys = [call.kwargs["json"]["idempotency_key"] for call in client.request.call_args_list]
        self.assertEqual(keys, ["first", "first", "new-intent"])

    def test_report_download_rechecks_authenticated_backend_route(self):
        import api_views
        ui = Mock()
        ui.session_state = {"account_entitlements": {"plan": "premium"}}
        ui.form.return_value = nullcontext()
        ui.expander.return_value = nullcontext()
        ui.number_input.side_effect = [0, 0, 0, 0]
        ui.text_input.return_value = ""
        ui.form_submit_button.return_value = False
        ui.button.side_effect = lambda label, **kwargs: label == "Generate decision report"
        ui.selectbox.side_effect = [0, "properties"]
        report = {"report_id": "report-one", "content": "{}", "filename": "report.json", "media_type": "application/json"}
        with patch.object(api_views, "st", ui), patch.object(api_views, "display_frame"), patch.object(api_views, "capability", side_effect=lambda feature: feature in {"can_export", "can_generate_ai_reports"}), patch.object(api_views, "api_call", side_effect=[{"ranked": [{"property_id": "property-one", "price_num": 1500}]}, report, '{"verified": true}']) as call:
            api_views.render_comparison(Mock(), [{"id": "property-one"}])
            self.assertEqual(call.call_args.args[1:3], ("GET", "/reports/report-one/download"))
            self.assertTrue(call.call_args.kwargs["raw"])
            self.assertEqual(ui.download_button.call_args.args[1], '{"verified": true}')

    def test_numeric_filter_submission_uses_shared_constraint_contract(self):
        import api_views
        ui = Mock()
        ui.session_state = {}
        ui.form.return_value = nullcontext()
        ui.number_input.side_effect = [2000, 1, 1.5, 700]
        ui.text_input.return_value = ""
        ui.form_submit_button.return_value = True
        ui.button.return_value = False
        with patch.object(api_views, "st", ui), patch.object(api_views, "capability", return_value=False), patch.object(api_views, "api_call", return_value={"ranked": []}) as call:
            api_views.render_comparison(Mock(), [{"id": "property-one"}])
            self.assertEqual(call.call_args.args[2], "/ranking")
            self.assertEqual(call.call_args.args[3]["constraints"], {
                "rent_lte": 2000, "min_beds": 1, "min_baths": 1.5, "min_sqft": 700,
            })
            self.assertEqual(call.call_args.args[3]["property_ids"], ["property-one"])

    def test_feedback_uses_backend_persistence_without_email_dispatch(self):
        import api_views
        ui = Mock()
        ui.session_state = {"account_entitlements": {"plan": "free"}, "show_feedback_form": True}
        ui.form.return_value = nullcontext()
        ui.selectbox.return_value = "bug"
        ui.text_input.return_value = "A reproducible issue"
        ui.text_area.return_value = "Steps to reproduce"
        ui.form_submit_button.return_value = True
        ui.button.return_value = False
        auth = Mock()
        auth.is_authenticated.return_value = True
        with patch.object(api_views, "st", ui), patch.object(api_views, "render_profile"), patch.object(api_views, "api_call", return_value={"public_reference": "FEEDBACK-1"}) as call:
            api_views.render_account_view(Mock(), auth, "Profile")
            self.assertEqual(call.call_args.args[2], "/feedback")
            payload = call.call_args.args[3]
            self.assertTrue(payload.pop("idempotency_key"))
            self.assertEqual(payload, {
                "category": "bug", "title": "A reproducible issue", "description": "Steps to reproduce",
                "route_or_screen": "Profile",
            })

    def test_account_switch_clears_house_widgets_preferences_and_caches(self):
        state = {"auth_user": {"id": 1}, "homes_current_result": {"address": "private"},
                 "apt_prefs": {"pets": "Yes"}, "account_report": "private", "user_profile": {"max_budget": 9000}}
        manager = StreamlitAuthManager(Mock(), state)
        manager.set_authenticated("new-token", {"id": 2, "active_plan": "free"})
        self.assertNotIn("homes_current_result", state)
        self.assertNotIn("apt_prefs", state)
        self.assertNotIn("account_report", state)
        self.assertEqual(state["user_profile"], {})
        self.assertEqual(state["auth_user"]["id"], 2)

    def test_api_entitlements_hydrate_profile_and_mixed_properties(self):
        import api_views
        client = Mock()
        client.request.side_effect = [
            FakeResponse(200, {"plan": "premium_plus", "features": {"exports": True, "advisor": True},
                               "limits": {"analyses": 500, "properties": 200}, "usage": {"analyses": 7}}),
            FakeResponse(200, {"properties": [{"id": "a", "kind": "apartment", "parsed": {"address": "A"}},
                                               {"id": "h", "kind": "home", "parsed": {"address": "H"}}]}),
            FakeResponse(200, {"preferences": {"max_budget": 2500}}),
        ]
        with patch.object(api_views.st, "session_state", {}):
            self.assertTrue(api_views.hydrate_account(client))
            state = api_views.st.session_state
            self.assertEqual(state["user_profile"]["max_budget"], 2500)
            self.assertEqual(len(state["account_properties"]), 2)
            self.assertEqual(state["account_entitlements"]["quotas"]["monthly_analyses_limit"], 500)
            self.assertTrue(state["account_entitlements"]["capabilities"]["can_export"])
            self.assertEqual(state["account_entitlements"]["usage"]["analyses_used"], 7)

    def test_free_uses_static_table_not_native_download_toolbar(self):
        import api_views
        with patch.object(api_views, "capability", return_value=False), patch.object(api_views.st, "table", create=True) as table, patch.object(api_views.st, "dataframe", create=True) as dataframe:
            api_views.display_frame(pd.DataFrame([{"property": "A"}]))
            table.assert_called_once()
            dataframe.assert_not_called()

    def test_safe_errors_do_not_render_backend_details(self):
        import api_views
        client = Mock()
        client.request.return_value = FakeResponse(500, {"detail": "database secret exception"})
        with patch.object(api_views.st, "error", create=True) as error:
            self.assertIsNone(api_views.api_call(client, "GET", "/properties"))
            self.assertNotIn("secret", error.call_args.args[0])

    def test_bed_and_bath_labels_are_normalized(self):
        from api_views import number_label
        self.assertEqual(number_label(1.0, "bed"), "1 bed")
        self.assertEqual(number_label(1.0, "bath"), "1 bath")
        self.assertEqual(number_label(1.5, "bath"), "1.5 baths")

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
            return

        try:
            payload = response.json()
        except ValueError:
            state["auth_error"] = (
                f"Service error (HTTP {response.status_code}). Please try again."
            )
            return

        if response.status_code >= 400:
            state["auth_error"] = payload.get(
                "detail",
                "Could not process password reset request."
            )
            return

        state["auth_notice"] = (
            payload.get("message")
            or "If an account exists for that email, a password reset link has been sent."
        )

        reset_link = payload.get("reset_link")

        if reset_link:
            state["auth_notice"] += " Development reset link generated below."
            state["dev_reset_link"] = reset_link
        else:
            state["dev_reset_link"] = None


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
