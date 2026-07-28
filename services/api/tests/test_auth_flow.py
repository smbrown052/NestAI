import os
import tempfile
import unittest
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir()) / 'nestai-api-auth-tests.db'}"
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-32-plus-characters"
os.environ["NESTAI_OWNER_EMAIL"] = "owner@example.com"

import app.db.models  # noqa: F401 — registers all models so create_all includes all tables
from app.db.base import Base
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
        # Register returns {"user": {...}, "access_token": ..., "token_type": ...}
        user = body["user"]
        self.assertEqual(user["email"], "owner@example.com")
        self.assertEqual(user["display_name"], "Owner")
        self.assertTrue(user["is_admin"])
        self.assertTrue(user["is_active"])
        self.assertEqual(user["tier"], "free")
        self.assertEqual(user["active_plan"], "free")
        self.assertNotIn("hashed_password", user)
        self.assertNotIn("password_hash", user)

    def test_register_rejects_duplicate_email(self) -> None:
        payload = {"email": "duplicate@example.com", "password": "StrongPassword123!", "display_name": "Dup User"}
        self.client.post("/auth/register", json=payload)
        response = self.client.post("/auth/register", json=payload)

        self.assertEqual(response.status_code, 409, response.text)

    def test_register_display_name_optional(self) -> None:
        """display_name is optional — omitting it should succeed."""
        payload = {"email": "nodisplay@example.com", "password": "StrongPassword123!"}
        response = self.client.post("/auth/register", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        user = response.json()["user"]
        self.assertIsNone(user["display_name"])

    def test_login_returns_bearer_token_and_me_excludes_password_fields(self) -> None:
        self.client.post(
            "/auth/register",
            json={"email": "member@example.com", "password": "StrongPassword123!", "display_name": "Member"},
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
            json={"email": "member@example.com", "password": "StrongPassword123!", "display_name": "Member"},
        )

        response = self.client.post(
            "/auth/login",
            json={"email": "member@example.com", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()["detail"], "Invalid email or password")

    def test_admin_routes_require_logged_in_admin(self) -> None:
        import base64

        def _basic(email: str, password: str) -> dict:
            token = base64.b64encode(f"{email}:{password}".encode()).decode()
            return {"Authorization": f"Basic {token}"}

        self.client.post(
            "/auth/register",
            json={"email": "member@example.com", "password": "StrongPassword123!", "display_name": "Member"},
        )
        forbidden = self.client.get(
            "/admin/users",
            headers=_basic("member@example.com", "StrongPassword123!"),
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        self.client.post(
            "/auth/register",
            json={"email": "owner@example.com", "password": "StrongPassword123!", "display_name": "Owner"},
        )
        allowed = self.client.get(
            "/admin/users",
            headers=_basic("owner@example.com", "StrongPassword123!"),
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(len(allowed.json()), 2)

    def test_me_requires_bearer_token(self) -> None:
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 401, response.text)


if __name__ == "__main__":
    unittest.main()
