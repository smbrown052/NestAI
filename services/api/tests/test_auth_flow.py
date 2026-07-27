import os
import tempfile
import unittest
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir()) / 'nestai-api-auth-tests.db'}"
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-32-plus-characters"
os.environ["NESTAI_OWNER_EMAIL"] = "owner@example.com"

import app.db.models  # noqa: F401
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
        self.assertEqual(body["email"], "owner@example.com")
        self.assertEqual(body["display_name"], "Owner")
        self.assertTrue(body["is_admin"])
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
        self.assertEqual(response.json()["detail"], "Invalid credentials")

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
            json={"email": "owner@example.com", "password": "StrongPassword123!"},
        )
        owner_login = self.client.post(
            "/auth/login",
            json={"email": "owner@example.com", "password": "StrongPassword123!"},
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
