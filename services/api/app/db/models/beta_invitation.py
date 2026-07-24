"""BetaInvitation model — pending invitations sent to new beta testers."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BetaInvitation(Base):
    __tablename__ = "beta_invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Admin who sent the invitation.
    invited_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # User created when the invitation is accepted (NULL while pending).
    accepted_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    # One-time token embedded in the invitation link.
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    # Credits to grant on acceptance.
    building_analyses: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    ai_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    commute_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    premium_features: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    beta_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "pending" | "accepted" | "expired" | "revoked"
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
