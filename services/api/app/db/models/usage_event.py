"""UsageEvent — lightweight audit trail for property platform actions.

event_type values (non-exhaustive, grow as needed):
    property_analyzed       — user analyzed a property (any type)
    property_saved          — user saved a property
    property_archived       — user or system archived a property
    property_restored       — user restored an archived property
    property_replaced       — free-tier archive-and-replace flow completed
    homes_tab_opened        — user opened the Homes tab
    zillow_example_loaded   — user loaded a Zillow fixture example
    zillow_parse_succeeded  — Zillow parser ran successfully
    zillow_parse_failed     — Zillow parser returned empty result
    premium_feature_attempted — user tried a gated feature
    upgrade_prompt_shown    — upgrade nudge was displayed
    comparison_viewed       — comparison table was opened
    export_generated        — export was produced (future)

The ``plan`` column captures the user's plan at the time of the event so
quota/behavior can be reconstructed later even after plan changes.

NOTE: This table is append-only.  Records are never deleted or updated.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Ownership — at least one must be present
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    plan: Mapped[Optional[str]] = mapped_column(String(32))   # plan at time of event
    property_type: Mapped[Optional[str]] = mapped_column(String(32))   # property type involved
    meta_json: Mapped[Optional[str]] = mapped_column(Text)    # arbitrary JSON context

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
