"""BillingEvent model — records of payment events (e.g. Stripe webhooks)."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BillingEvent(Base):
    __tablename__ = "billing_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # "subscription_created" | "subscription_cancelled" | "credit_pack_purchased" | "refund" etc.
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), default="stripe", nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(8))
    # Tier granted / changed to.
    tier_before: Mapped[str | None] = mapped_column(String(32))
    tier_after: Mapped[str | None] = mapped_column(String(32))
    credits_granted: Mapped[int | None] = mapped_column(Integer)
    raw_payload: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
