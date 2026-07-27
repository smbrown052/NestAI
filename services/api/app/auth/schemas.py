"""Pydantic schemas for NestAI auth requests and responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    account_type: str = Field(default="free")
    beta_invite_code: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuthUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str | None = None
    tier: str
    active_plan: str
    requested_plan: str | None = None
    selected_account_type: str
    subscription_status: str
    payment_customer_id: str | None = None
    payment_subscription_id: str | None = None
    beta_approved_at: datetime | None = None
    beta_access: bool = False
    is_admin: bool
    is_active: bool


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CheckoutSessionCreateRequest(BaseModel):
    plan: str


class CheckoutSessionCreateResponse(BaseModel):
    checkout_session_id: str
    checkout_url: str
    payment_required_message: str
    active_plan: str
    requested_plan: str


class BillingStatusRead(BaseModel):
    active_plan: str
    requested_plan: str | None = None
    subscription_status: str
    payment_customer_id: str | None = None
    payment_subscription_id: str | None = None
    checkout_session_id: str | None = None
    checkout_url: str | None = None
    payment_required_message: str | None = None