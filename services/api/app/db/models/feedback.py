"""
FeedbackReport model — mirrors the feedback_reports table from the legacy
SQLite database, promoted to PostgreSQL.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FeedbackReport(Base):
    __tablename__ = "feedback_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    public_reference: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    actual_behavior: Mapped[str | None] = mapped_column(Text)
    expected_behavior: Mapped[str | None] = mapped_column(Text)
    requested_feature: Mapped[str | None] = mapped_column(Text)
    problem_to_solve: Mapped[str | None] = mapped_column(Text)
    value_rating: Mapped[str | None] = mapped_column(String(64))
    what_were_you_doing: Mapped[str | None] = mapped_column(Text)
    what_was_unclear: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str | None] = mapped_column(String(64))
    app_version: Mapped[str | None] = mapped_column(String(32))
    build_number: Mapped[str | None] = mapped_column(String(32))
    route_or_screen: Mapped[str | None] = mapped_column(String(128))
    browser: Mapped[str | None] = mapped_column(String(128))
    operating_system: Mapped[str | None] = mapped_column(String(128))
    device_model: Mapped[str | None] = mapped_column(String(128))
    comparison_id: Mapped[str | None] = mapped_column(String(64))
    building_id: Mapped[str | None] = mapped_column(String(64))
    unit_id: Mapped[str | None] = mapped_column(String(64))
    ai_report_id: Mapped[str | None] = mapped_column(String(64))
    error_correlation_id: Mapped[str | None] = mapped_column(String(64))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    user_contact_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attachment_url: Mapped[str | None] = mapped_column(String(512))
    user_plan: Mapped[str | None] = mapped_column(String(32))
    beta_tester: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    unit_count: Mapped[int | None] = mapped_column(Integer)
    building_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False, index=True)
    severity: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[str | None] = mapped_column(String(32))
    duplicate_of_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("feedback_reports.id", ondelete="SET NULL")
    )
    internal_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
