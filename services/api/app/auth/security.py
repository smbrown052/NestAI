"""Password hashing and JWT helpers for NestAI authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from pwdlib import PasswordHash

PASSWORD_HASHER = PasswordHash.recommended()
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_TOKEN_TYPE = "access"
DEFAULT_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return PASSWORD_HASHER.verify(password, hashed_password)


def _jwt_secret() -> bytes:
    secret = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY or SECRET_KEY must be set")
    return secret.encode("utf-8")


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _base64url_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def create_access_token(
    claims: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + (expires_delta or timedelta(minutes=DEFAULT_TOKEN_EXPIRE_MINUTES))
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    payload = {
        **claims,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "type": JWT_TOKEN_TYPE,
    }

    signing_input = ".".join(
        _base64url_encode(json.dumps(part, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        for part in (header, payload)
    )
    signature = hmac.new(_jwt_secret(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_base64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise ValueError("Invalid token format") from exc

    signing_input = f"{header_b64}.{payload_b64}"
    expected_signature = hmac.new(
        _jwt_secret(),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    provided_signature = _base64url_decode(signature_b64)
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise ValueError("Invalid token signature")

    payload = json.loads(_base64url_decode(payload_b64))
    expires_at = int(payload.get("exp", 0) or 0)
    if expires_at and datetime.now(timezone.utc).timestamp() > expires_at:
        raise ValueError("Token expired")
    if payload.get("type") != JWT_TOKEN_TYPE:
        raise ValueError("Invalid token type")
    return payload