import os
import tempfile
import unittest
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir()) / 'nestai-api-auth-tests.db'}"
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-32-plus-characters"
os.environ["NESTAI_OWNER_EMAIL"] = "smbrown.052@gmail.com"

import app.db.models  # noqa: F401
from app.db.base import Base
from app.core.security import hash_password as legacy_hash_password
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.user import User
from app.db.session import SessionLocal
from app.db.session import engine
from fastapi.testclient import TestClient
from main import app


class AuthFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

    def test_register_trims_lowercases_and_sets_owner_admin(self) -> None:
        response = self.client.post(
            "/auth/register",
            json={
                "email": "  OWNER@Example.com  ",
                "password": "StrongPassword123!",
                "display_name": " Owner ",
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["email"], "owner@example.com")
        self.assertEqual(body["display_name"], "Owner")
        self.assertFalse(body["is_admin"])
        self.assertTrue(body["is_active"])
        self.assertEqual(body["tier"], "free")
        self.assertEqual(body["plan"], "FREE")
        self.assertNotIn("hashed_password", body)
        self.assertNotIn("password_hash", body)

    def test_register_rejects_duplicate_email(self) -> None:
        payload = {"email": "duplicate@example.com", "password": "StrongPassword123!"}
        self.client.post("/auth/register", json=payload)
        response = self.client.post("/auth/register", json=payload)

        self.assertEqual(response.status_code, 409, response.text)

    def test_login_returns_bearer_token_and_me_excludes_password_fields(self) -> None:
        self.client.post(
            "/auth/register",
            json={"email": "member@example.com", "password": "StrongPassword123!"},
        )

        login_response = self.client.post(
            "/auth/login",
            json={"email": " MEMBER@example.com ", "password": "StrongPassword123!"},
        )
        self.assertEqual(login_response.status_code, 200, login_response.text)
        token_body = login_response.json()
        self.assertEqual(token_body["token_type"], "bearer")
        self.assertTrue(token_body["access_token"])

        me_response = self.client.get(
            "/auth/me",
            headers={"Authorization": "Bearer " + token_body["access_token"]},
        )
        self.assertEqual(me_response.status_code, 200, me_response.text)
        me_body = me_response.json()
        self.assertEqual(me_body["email"], "member@example.com")
        self.assertNotIn("hashed_password", me_body)
        self.assertNotIn("password_hash", me_body)

    def test_login_rejects_invalid_credentials(self) -> None:
        self.client.post(
            "/auth/register",
            json={"email": "member@example.com", "password": "StrongPassword123!"},
        )

        response = self.client.post(
            "/auth/login",
            json={"email": "member@example.com", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()["detail"], "Incorrect password")

    def test_login_reports_unknown_and_inactive_accounts(self) -> None:
        unknown = self.client.post(
            "/auth/login",
            json={"email": "missing@example.com", "password": "StrongPassword123!"},
        )
        self.assertEqual(unknown.status_code, 404, unknown.text)
        self.assertEqual(unknown.json()["detail"], "Account not found")

        db = SessionLocal()
        try:
            db.add(
                User(
                    email="inactive@example.com",
                    hashed_password=legacy_hash_password("StrongPassword123!"),
                    is_active=False,
                    is_admin=False,
                    tier="free",
                    active_plan="free",
                    subscription_status="active",
                )
            )
            db.commit()
        finally:
            db.close()

        inactive = self.client.post(
            "/auth/login",
            json={"email": "inactive@example.com", "password": "StrongPassword123!"},
        )
        self.assertEqual(inactive.status_code, 403, inactive.text)
        self.assertEqual(inactive.json()["detail"], "Inactive account")

    def test_existing_owner_with_legacy_hash_can_login_and_becomes_admin(self) -> None:
        db = SessionLocal()
        try:
            db.add(
                User(
                    email="smbrown.052@gmail.com",
                    hashed_password=legacy_hash_password("StrongPassword123!"),
                    is_active=True,
                    is_admin=False,
                    tier="free",
                    active_plan="free",
                    subscription_status="active",
                )
            )
            db.commit()
        finally:
            db.close()

        login_response = self.client.post(
            "/auth/login",
            json={"email": "  SMBROWN.052@GMAIL.COM  ", "password": "StrongPassword123!"},
        )
        self.assertEqual(login_response.status_code, 200, login_response.text)
        token = login_response.json()["access_token"]

        me_response = self.client.get(
            "/auth/me",
            headers={"Authorization": "Bearer " + token},
        )
        self.assertEqual(me_response.status_code, 200, me_response.text)
        me_body = me_response.json()
        self.assertEqual(me_body["email"], "smbrown.052@gmail.com")
        self.assertTrue(me_body["is_admin"])
        self.assertTrue(me_body["is_active"])

    def test_forgot_password_and_reset_password_flow(self) -> None:
        self.client.post(
            "/auth/register",
            json={"email": "resetme@example.com", "password": "StrongPassword123!"},
        )

        forgot_response = self.client.post(
            "/auth/forgot-password",
            json={"email": "  RESETME@example.com  "},
        )
        self.assertEqual(forgot_response.status_code, 200, forgot_response.text)
        forgot_body = forgot_response.json()
        self.assertIn("If an account exists", forgot_body["message"])
        self.assertIn("reset_link", forgot_body)
        token = forgot_body["reset_link"].split("reset_token=")[1]

        db = SessionLocal()
        try:
            token_row = db.query(PasswordResetToken).first()
            self.assertIsNotNone(token_row)
            self.assertIsNone(token_row.used_at)
        finally:
            db.close()

        reset_response = self.client.post(
            "/auth/reset-password",
            json={"token": token, "password": "EvenStrongerPassword456!"},
        )
        self.assertEqual(reset_response.status_code, 200, reset_response.text)

        reused_response = self.client.post(
            "/auth/reset-password",
            json={"token": token, "password": "AnotherPassword789!"},
        )
        self.assertEqual(reused_response.status_code, 400, reused_response.text)

        login_response = self.client.post(
            "/auth/login",
            json={"email": "resetme@example.com", "password": "EvenStrongerPassword456!"},
        )
        self.assertEqual(login_response.status_code, 200, login_response.text)

    def test_admin_routes_require_logged_in_admin(self) -> None:
        self.client.post(
            "/auth/register",
            json={"email": "member@example.com", "password": "StrongPassword123!"},
        )
        user_login = self.client.post(
            "/auth/login",
            json={"email": "member@example.com", "password": "StrongPassword123!"},
        )
        user_token = user_login.json()["access_token"]

        forbidden = self.client.get(
            "/admin/users",
            headers={"Authorization": "Bearer " + user_token},
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        self.client.post(
            "/auth/register",
            json={"email": "smbrown.052@gmail.com", "password": "StrongPassword123!"},
        )
        owner_login = self.client.post(
            "/auth/login",
            json={"email": "smbrown.052@gmail.com", "password": "StrongPassword123!"},
        )
        owner_token = owner_login.json()["access_token"]

        allowed = self.client.get(
            "/admin/users",
            headers={"Authorization": "Bearer " + owner_token},
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(len(allowed.json()), 2)

    def test_me_requires_bearer_token(self) -> None:
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 401, response.text)


if __name__ == "__main__":
    unittest.main()
