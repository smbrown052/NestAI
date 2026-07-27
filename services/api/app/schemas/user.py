"""User and authentication schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=4096)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=4096)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str | None
    is_admin: bool
    is_active: bool
    plan: str
    tier: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
