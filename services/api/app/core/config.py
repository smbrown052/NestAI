"""Central application settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_API_ROOT = Path(__file__).resolve().parents[2]
_INSECURE_DEV_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    environment: str = "development"
    nestai_owner_email: str | None = None
    jwt_secret_key: str = _INSECURE_DEV_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=1)

    model_config = SettingsConfigDict(
        env_file=str(_API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"dev", "development", "local", "test", "testing"}

    @field_validator("jwt_algorithm")
    @classmethod
    def validate_algorithm(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or normalized.lower() == "none":
            raise ValueError("JWT_ALGORITHM must be a supported signing algorithm.")
        return normalized

    @model_validator(mode="after")
    def validate_secret(self) -> "Settings":
        if not self.is_development and self.jwt_secret_key == _INSECURE_DEV_SECRET:
            raise ValueError(
                "JWT_SECRET_KEY must be set to a secure value outside development/test environments."
            )
        if not self.is_development and len(self.jwt_secret_key) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters outside development/test environments."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
