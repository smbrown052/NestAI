"""Pydantic schemas for NestAI auth requests and responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)
    account_type: str = Field(default="free")
    beta_invite_code: str | None = None
    referral_code: str | None = Field(default=None, max_length=64)
    trial_consent: bool = False
    payment_method_confirmed: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_input(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_input(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_input(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_link: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=8, max_length=128)


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
    referrer_id: int | None = None
    referral_code: str | None = None
    referral_credit_cents: int = 0
    is_admin: bool
    is_active: bool


class ReferralInviteRequest(BaseModel):
    email: EmailStr


class ReferralRead(BaseModel):
    id: int
    referred_email: EmailStr
    status: str
    reward_cents: int
    created_at: datetime
    converted_at: datetime | None = None
    rewarded_at: datetime | None = None


class ReferralSummaryRead(BaseModel):
    referral_code: str
    referral_link: str
    earned_credit_cents: int
    referrals: list[ReferralRead]


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CheckoutSessionCreateRequest(BaseModel):
    plan: str
    trial_consent: bool = False
    payment_method_confirmed: bool = False


class CheckoutSessionCreateResponse(BaseModel):
    checkout_session_id: str
    checkout_url: str
    payment_required_message: str
    active_plan: str
    requested_plan: str
    trial_days: int | None = None
    trial_end_date: str | None = None
    future_monthly_price: str | None = None
    cancellation_terms: str | None = None
    billing_reminder: str | None = None


class BillingStatusRead(BaseModel):
    active_plan: str
    requested_plan: str | None = None
    subscription_status: str
    payment_customer_id: str | None = None
    payment_subscription_id: str | None = None
    checkout_session_id: str | None = None
    checkout_url: str | None = None
    payment_required_message: str | None = None
    trial_days: int | None = None
    trial_end_date: str | None = None
    future_monthly_price: str | None = None
    cancellation_terms: str | None = None
    billing_reminder: str | None = None