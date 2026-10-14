"""Restoration credentials are scoped, hashed, expiring and server-revocable."""

from datetime import datetime, timedelta, timezone

from app.db.models.browser_session import BrowserSession
from app.db.models.password_reset_token import PasswordResetToken
from app.auth.security import hash_reset_token
from test_platform import api


def test_browser_restoration_logout_and_password_reset(api):
    client, factory, headers, ids, _ = api
    created = client.post("/auth/browser-session", headers=headers[0])
    assert created.status_code == 200
    assert created.headers["cache-control"] == "no-store"
    credential = created.json()["credential"]
    with factory() as db:
        row = db.query(BrowserSession).one()
        assert row.token_hash == hash_reset_token(credential)
        assert row.token_hash != credential
        assert row.user_id == ids[0]
    restored = client.post("/auth/restore", json={"credential": credential})
    assert restored.status_code == 200
    assert restored.headers["cache-control"] == "no-store"
    assert restored.json()["user"]["id"] == ids[0]
    token = restored.json()["access_token"]
    assert client.get("/properties", headers={"Authorization": "Bearer " + token}).status_code == 200
    assert client.post("/auth/revoke-browser-session", json={"credential": credential}).status_code == 200
    assert client.post("/auth/restore", json={"credential": credential}).status_code == 401
    assert client.post("/auth/revoke-browser-session", json={"credential": credential}).status_code == 200

    credentials = [client.post("/auth/browser-session", headers=headers[0]).json()["credential"] for _ in range(2)]
    other = client.post("/auth/browser-session", headers=headers[1]).json()["credential"]
    raw_reset = "a-secure-reset-token-only-for-tests"
    with factory() as db:
        db.add(PasswordResetToken(user_id=ids[0], token_hash=hash_reset_token(raw_reset),
                                  expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
        db.commit()
    assert client.post("/auth/reset-password", json={
        "token": raw_reset, "password": "NewPassword123!",
    }).status_code == 200
    for value in credentials:
        assert client.post("/auth/restore", json={"credential": value}).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401
    assert client.post("/auth/restore", json={"credential": other}).status_code == 200
    assert client.post("/auth/browser-session", headers=headers[0]).status_code == 401
    login = client.post("/auth/login", json={"email": "user1@example.com", "password": "NewPassword123!"})
    assert login.status_code == 200
    fresh = client.post("/auth/browser-session", headers={
        "Authorization": "Bearer " + login.json()["access_token"],
    })
    assert fresh.status_code == 200
    assert client.post("/auth/restore", json=fresh.json()).status_code == 200


def test_restoration_expiry_invalid_and_version_check(api):
    client, factory, headers, ids, _ = api
    from app.db.models.user import User
    assert client.post("/auth/browser-session").status_code == 401
    assert client.post("/auth/restore", json={"credential": "x" * 48}).status_code == 401
    assert client.post("/auth/restore", json={"credential": "short"}).status_code == 422
    for change in ("expired", "version", "inactive"):
        credential = client.post("/auth/browser-session", headers=headers[0]).json()["credential"]
        with factory() as db:
            row = db.get(BrowserSession, hash_reset_token(credential))
            if change == "expired":
                row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            elif change == "version":
                row.auth_version = -1
            else:
                db.get(User, ids[0]).is_active = False
            db.commit()
        assert client.post("/auth/restore", json={"credential": credential}).status_code == 401
