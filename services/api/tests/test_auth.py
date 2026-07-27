from __future__ import annotations

import json
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth.security import hash_password


ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "services" / "api"


class AuthApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tempdir = tempfile.TemporaryDirectory()
        db_path = Path(cls._tempdir.name) / "test.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        os.environ["JWT_SECRET_KEY"] = "test-secret-key"
        os.environ["SECRET_KEY"] = "test-secret-key"
        os.environ["BILLING_WEBHOOK_SECRET"] = "test-billing-secret"
        os.environ["NESTAI_STREAMLIT_URL"] = "http://localhost:8501"

        if str(API_ROOT) not in sys.path:
            sys.path.insert(0, str(API_ROOT))

        for module_name in [
            "app.db.session",
            "app.db.base",
            "app.db.models.user",
            "app.db.models.beta_access",
            "app.auth.security",
            "app.auth.plans",
            "app.auth.dependencies",
            "app.auth.router",
            "app.billing.service",
            "app.billing.router",
            "app.admin.router",
            "main",
        ]:
            sys.modules.pop(module_name, None)

        cls.session_module = importlib.import_module("app.db.session")
        cls.base_module = importlib.import_module("app.db.base")
        cls.user_module = importlib.import_module("app.db.models.user")
        cls.beta_access_module = importlib.import_module("app.db.models.beta_access")
        cls.billing_service = importlib.import_module("app.billing.service")
        cls.main_module = importlib.import_module("main")
        cls.base_module.Base.metadata.create_all(bind=cls.session_module.engine)
        cls.client = TestClient(cls.main_module.app)

        db = cls.session_module.SessionLocal()
        try:
            admin_user = cls.user_module.User(
                email="admin@example.com",
                hashed_password=hash_password("AdminPassword123!"),
                display_name="Admin User",
                is_active=True,
                is_admin=True,
                tier="premium",
                active_plan="premium",
                subscription_status="active",
            )
            db.add(admin_user)
            db.commit()
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tempdir.cleanup()

    def _unique_email(self) -> str:
        return f"user-{self.id()}@example.com"

    def _register(self, email: str, password: str, display_name: str, account_type: str, beta_invite_code: str | None = None):
        payload = {
            "email": email,
            "password": password,
            "display_name": display_name,
            "account_type": account_type,
        }
        if beta_invite_code is not None:
            payload["beta_invite_code"] = beta_invite_code
        return self.client.post("/auth/register", json=payload)

    def _basic_headers(self, email: str, password: str) -> dict[str, str]:
        import base64

        token = base64.b64encode(f"{email}:{password}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def test_routes_are_not_duplicated(self) -> None:
        paths = self.main_module.app.openapi()["paths"]
        self.assertIn("/auth/register", paths)
        self.assertIn("/auth/login", paths)
        self.assertIn("/auth/me", paths)
        self.assertIn("/billing/create-checkout-session", paths)
        self.assertIn("/billing/webhook", paths)
        self.assertIn("/billing/status", paths)
        self.assertNotIn("/auth/auth/register", paths)
        self.assertNotIn("/auth/auth/login", paths)
        self.assertNotIn("/auth/auth/me", paths)

    def test_register_login_me_and_duplicate(self) -> None:
        email = self._unique_email()
        password = "CorrectHorseBatteryStaple!"

        register_response = self._register(email, password, "Test User", "free")
        self.assertEqual(register_response.status_code, 201)
        self.assertEqual(register_response.json()["user"]["email"], email)
        self.assertEqual(register_response.json()["user"]["display_name"], "Test User")
        self.assertEqual(register_response.json()["user"]["active_plan"], "free")
        self.assertEqual(register_response.json()["user"]["selected_account_type"], "free")

        duplicate_response = self._register(email, password, "Test User", "free")
        self.assertEqual(duplicate_response.status_code, 409)

        bad_login = self.client.post(
            "/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
        self.assertEqual(bad_login.status_code, 401)
        self.assertEqual(bad_login.json()["detail"], "Invalid email or password")

        login_response = self.client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.json()["token_type"], "bearer")
        token = login_response.json()["access_token"]
        self.assertTrue(token)

        me_response = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["email"], email)
        self.assertEqual(me_response.json()["display_name"], "Test User")

        db = self.session_module.SessionLocal()
        try:
            user_count = db.query(self.user_module.User).filter(self.user_module.User.email == email).count()
            self.assertEqual(user_count, 1)
        finally:
            db.close()

    def test_beta_access_premium_payment_and_webhook_flow(self) -> None:
        db = self.session_module.SessionLocal()
        try:
            invite_code = "NEST-BETA-ACCESS"
            beta_invite = self.beta_access_module.BetaAccess(
                code_hash=hash_password(invite_code),
                created_by_id=1,
                email_hint="beta@example.com",
                max_uses=1,
            )
            db.add(beta_invite)
            db.commit()
            db.refresh(beta_invite)
            invite_id = beta_invite.id
        finally:
            db.close()

        beta_response = self._register("beta@example.com", "CorrectHorseBatteryStaple!", "Beta User", "beta", invite_code)
        self.assertEqual(beta_response.status_code, 201)
        self.assertTrue(beta_response.json()["user"]["beta_access"])
        self.assertEqual(beta_response.json()["user"]["active_plan"], "beta")

        admin_headers = self._basic_headers("admin@example.com", "AdminPassword123!")
        admin_create = self.client.post(
            "/admin/beta-codes",
            json={"email_restriction": "restricted@example.com", "max_uses": 2},
            headers=admin_headers,
        )
        self.assertEqual(admin_create.status_code, 200)
        self.assertIn("invite_code", admin_create.json())

        admin_list = self.client.get("/admin/beta-codes", headers=admin_headers)
        self.assertEqual(admin_list.status_code, 200)
        self.assertNotIn("invite_code", admin_list.json()[0])

        premium_response = self._register("premium@example.com", "CorrectHorseBatteryStaple!", "Premium User", "premium")
        self.assertEqual(premium_response.status_code, 201)
        premium_payload = premium_response.json()
        self.assertEqual(premium_payload["user"]["requested_plan"], "premium")
        self.assertEqual(premium_payload["user"]["subscription_status"], "pending_payment")
        self.assertTrue(premium_payload["checkout_session_id"])
        self.assertEqual(premium_payload["payment_required_message"], "Payment required to activate Premium")

        billing_status = self.client.get(
            "/billing/status",
            headers={"Authorization": f"Bearer {premium_payload['access_token']}"},
        )
        self.assertEqual(billing_status.status_code, 200)
        self.assertEqual(billing_status.json()["requested_plan"], "premium")
        self.assertEqual(billing_status.json()["subscription_status"], "pending_payment")

        webhook_payload = {
            "event_id": "evt_premium_success",
            "event_type": "payment_succeeded",
            "checkout_session_id": premium_payload["checkout_session_id"],
            "payment_customer_id": "cus_123",
            "payment_subscription_id": "sub_123",
        }
        raw_webhook = json.dumps(webhook_payload).encode("utf-8")
        webhook_signature = self.billing_service.sign_webhook_payload(raw_webhook)
        webhook_response = self.client.post(
            "/billing/webhook",
            data=raw_webhook,
            headers={"Content-Type": "application/json", "X-NestAI-Signature": webhook_signature},
        )
        self.assertEqual(webhook_response.status_code, 200)
        self.assertEqual(webhook_response.json()["active_plan"], "premium")
        self.assertEqual(webhook_response.json()["subscription_status"], "active")

        premium_me = self.client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {premium_payload['access_token']}"},
        )
        self.assertEqual(premium_me.status_code, 200)
        self.assertEqual(premium_me.json()["active_plan"], "premium")
        self.assertEqual(premium_me.json()["subscription_status"], "active")

        plus_response = self._register("plus@example.com", "CorrectHorseBatteryStaple!", "Plus User", "premium_plus")
        self.assertEqual(plus_response.status_code, 201)
        plus_payload = plus_response.json()
        self.assertEqual(plus_payload["user"]["requested_plan"], "premium_plus")
        self.assertEqual(plus_payload["user"]["active_plan"], "free")
        self.assertEqual(plus_payload["payment_required_message"], "Payment required to activate Premium Plus")

        cancel_payload = {
            "event_id": "evt_plus_cancel",
            "event_type": "payment_cancelled",
            "checkout_session_id": plus_payload["checkout_session_id"],
        }
        raw_cancel = json.dumps(cancel_payload).encode("utf-8")
        cancel_signature = self.billing_service.sign_webhook_payload(raw_cancel)
        cancel_response = self.client.post(
            "/billing/webhook",
            data=raw_cancel,
            headers={"Content-Type": "application/json", "X-NestAI-Signature": cancel_signature},
        )
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.json()["subscription_status"], "cancelled")

        plus_me = self.client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {plus_payload['access_token']}"},
        )
        self.assertEqual(plus_me.status_code, 200)
        self.assertEqual(plus_me.json()["active_plan"], "free")
        self.assertEqual(plus_me.json()["subscription_status"], "cancelled")

    def test_beta_invite_deactivate_blocks_future_redemption(self) -> None:
        admin_headers = self._basic_headers("admin@example.com", "AdminPassword123!")
        create_response = self.client.post(
            "/admin/beta-codes",
            json={"email_restriction": "locked@example.com", "max_uses": 1},
            headers=admin_headers,
        )
        self.assertEqual(create_response.status_code, 200)

        invite_code = create_response.json()["invite_code"]
        invite_id = create_response.json()["id"]
        deactivate_response = self.client.post(f"/admin/beta-codes/{invite_id}/deactivate", headers=admin_headers)
        self.assertEqual(deactivate_response.status_code, 200)

        blocked = self._register("locked@example.com", "CorrectHorseBatteryStaple!", "Locked User", "beta", invite_code)
        self.assertEqual(blocked.status_code, 401)
