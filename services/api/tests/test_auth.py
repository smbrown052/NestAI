from __future__ import annotations

import json
import importlib
import os
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth.security import hash_password


ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "services" / "api"


class AuthApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("DATABASE_URL", "sqlite://")
        os.environ["JWT_SECRET_KEY"] = "test-secret-key"
        os.environ["SECRET_KEY"] = "test-secret-key"
        os.environ["BILLING_WEBHOOK_SECRET"] = "test-billing-secret"
        os.environ["NESTAI_STREAMLIT_URL"] = "http://localhost:8501"

        if str(API_ROOT) not in sys.path:
            sys.path.insert(0, str(API_ROOT))

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from types import SimpleNamespace
        from app.db.session import get_db
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        cls.session_module = SimpleNamespace(engine=engine, SessionLocal=sessionmaker(bind=engine))
        cls.base_module = importlib.import_module("app.db.base")
        # Import all models so every table is registered with Base.metadata
        importlib.import_module("app.db.models")
        cls.user_module = importlib.import_module("app.db.models.user")
        cls.beta_access_module = importlib.import_module("app.db.models.beta_access")
        cls.billing_service = importlib.import_module("app.billing.service")
        cls.main_module = importlib.import_module("main")
        def test_db():
            with cls.session_module.SessionLocal() as db:
                yield db
        cls.main_module.app.dependency_overrides[get_db] = test_db
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
            db.refresh(admin_user)
            cls._admin_id = admin_user.id
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.main_module.app.dependency_overrides.clear()
        cls.session_module.engine.dispose()

    def _unique_email(self) -> str:
        return f"user-{self.id()}@example.com"

    def _register(
        self,
        email: str,
        password: str,
        display_name: str,
        account_type: str,
        beta_invite_code: str | None = None,
        referral_code: str | None = None,
    ):
        payload = {
            "email": email,
            "password": password,
            "display_name": display_name,
            "account_type": account_type,
        }
        if account_type in {"premium", "premium_plus"}:
            payload["trial_consent"] = True
            payload["payment_method_confirmed"] = True
        if beta_invite_code is not None:
            payload["beta_invite_code"] = beta_invite_code
        if referral_code is not None:
            payload["referral_code"] = referral_code
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
        self.assertIn("/billing/checkout", paths)
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
        self.assertEqual(register_response.json()["user"]["email"], email.lower())
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
        self.assertEqual(bad_login.json()["detail"], "Incorrect password")

        login_response = self.client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.json()["token_type"], "bearer")
        token = login_response.json()["access_token"]
        self.assertTrue(token)

        me_response = self.client.get("/auth/me", headers={"Authorization": "Bearer " + token})
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["email"], email.lower())
        self.assertEqual(me_response.json()["display_name"], "Test User")

        db = self.session_module.SessionLocal()
        try:
            user_count = db.query(self.user_module.User).filter(self.user_module.User.email == email.lower()).count()
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
        premium_token = premium_payload["access_token"]
        self.assertEqual(premium_payload["user"]["requested_plan"], "premium")
        self.assertEqual(premium_payload["user"]["subscription_status"], "pending_payment")
        self.assertTrue(premium_payload["checkout_required"])
        self.assertNotIn("checkout_session_id", premium_payload)
        self.assertEqual(premium_payload["payment_required_message"], "Payment required to activate Premium")

        billing_status = self.client.get(
            "/billing/status",
            headers={"Authorization": "Bearer " + premium_token},
        )
        self.assertEqual(billing_status.status_code, 200)
        self.assertEqual(billing_status.json()["requested_plan"], "premium")
        self.assertEqual(billing_status.json()["subscription_status"], "pending_payment")

        premium_me = self.client.get(
            "/auth/me",
            headers={"Authorization": "Bearer " + premium_token},
        )
        self.assertEqual(premium_me.status_code, 200)
        self.assertEqual(premium_me.json()["active_plan"], "free")
        self.assertEqual(premium_me.json()["subscription_status"], "pending_payment")

        plus_response = self._register("plus@example.com", "CorrectHorseBatteryStaple!", "Plus User", "premium_plus")
        self.assertEqual(plus_response.status_code, 201)
        plus_payload = plus_response.json()
        plus_token = plus_payload["access_token"]
        self.assertEqual(plus_payload["user"]["requested_plan"], "premium_plus")
        self.assertEqual(plus_payload["user"]["active_plan"], "free")
        self.assertEqual(plus_payload["payment_required_message"], "Payment required to activate Premium Plus")

        plus_me = self.client.get(
            "/auth/me",
            headers={"Authorization": "Bearer " + plus_token},
        )
        self.assertEqual(plus_me.status_code, 200)
        self.assertEqual(plus_me.json()["active_plan"], "free")
        self.assertEqual(plus_me.json()["subscription_status"], "pending_payment")

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

    def test_referral_invite_preserved_without_mock_payment_reward(self) -> None:
        referrer = self._register("referrer@example.com", "CorrectHorseBatteryStaple!", "Referrer", "free")
        self.assertEqual(referrer.status_code, 201)
        referrer_token = referrer.json()["access_token"]
        referrer_code = referrer.json()["user"]["referral_code"]
        self.assertTrue(referrer_code)

        invite_response = self.client.post(
            "/auth/referrals/invite",
            json={"email": "friend@example.com"},
            headers={"Authorization": "Bearer " + referrer_token},
        )
        self.assertEqual(invite_response.status_code, 200)
        self.assertEqual(invite_response.json()["status"], "invited")

        premium_response = self._register(
            "friend@example.com",
            "CorrectHorseBatteryStaple!",
            "Friend",
            "premium",
            referral_code=referrer_code,
        )
        self.assertEqual(premium_response.status_code, 201)
        self.assertTrue(premium_response.json()["checkout_required"])

        summary_response = self.client.get(
            "/auth/referrals/summary",
            headers={"Authorization": "Bearer " + referrer_token},
        )
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(summary_response.json()["earned_credit_cents"], 0)
        self.assertTrue(summary_response.json()["referrals"])

    def test_premium_signup_requires_trial_consent(self) -> None:
        response = self.client.post(
            "/auth/register",
            json={
                "email": "consent-missing@example.com",
                "password": "CorrectHorseBatteryStaple!",
                "display_name": "Consent Missing",
                "account_type": "premium",
                "trial_consent": False,
                "payment_method_confirmed": True,
            },
        )
        self.assertEqual(response.status_code, 422)
