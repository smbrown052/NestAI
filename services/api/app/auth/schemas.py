"""
app/auth/schemas.py — Pydantic request/response schemas for authentication.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ── Request schemas ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)


# ── Response schemas ──────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CreditSummary(BaseModel):
    building_credits_remaining: int
    building_credits_used: int
    ai_credits_remaining: int
    ai_credits_used: int
    commute_credits_remaining: int
    commute_credits_used: int


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str | None
    is_active: bool
    is_admin: bool
    role: str
    tier: str
    beta_tester: bool
    last_login: datetime | None
    premium_start: datetime | None
    premium_expiration: datetime | None
    created_at: datetime
    credits: CreditSummary | None = None

    class Config:
        from_attributes = True
