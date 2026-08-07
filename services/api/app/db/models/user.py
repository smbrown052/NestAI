"""User model — application accounts and administrator flag."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Legacy compatibility field. Keep it aligned with active_plan.
    tier: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    active_plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    requested_plan: Mapped[str | None] = mapped_column(String(32))
    subscription_status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    payment_customer_id: Mapped[str | None] = mapped_column(String(255))
    payment_subscription_id: Mapped[str | None] = mapped_column(String(255))
    beta_tester: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    beta_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stripe_customer_id = mapped_column(String, nullable=True)
    stripe_subscription_id = mapped_column(String, nullable=True)

    subscription_status = mapped_column(String, nullable=True)

    trial_used = mapped_column(Boolean, nullable=False, default=False)

    trial_ends_at = mapped_column(DateTime(timezone=True), nullable=True)

    cancel_at_period_end = mapped_column(Boolean, nullable=False, default=False)
    referrer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    referral_code: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    referral_credit_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
