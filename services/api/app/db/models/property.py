"""Property domain model — generic property record.

This is the base property record shared across property types.
Subtype-specific fields live in dedicated detail tables
(home_details, apartment_details) linked by property_id.

property_type values:
    APARTMENT_BUILDING  — an entire Apartments.com building entry
    APARTMENT_UNIT      — a single unit within an apartment building
    HOME_FOR_SALE       — Zillow/MLS for-sale listing
    RENTAL_HOME         — Zillow/MLS for-rent listing
    CONDO               — Condominium listing (future)
    TOWNHOME            — Townhome listing (future)
    NEW_CONSTRUCTION    — New construction listing (future)

status values:
    ACTIVE      — currently available/listed
    SOLD        — sold (homes)
    RENTED      — rented (rental homes / apartments)
    EXPIRED     — listing expired
    ARCHIVED    — user-archived
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Ownership — nullable until full auth is wired
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Session identifier (used before account-backed ownership is available)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Classification
    property_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(64))   # e.g. "zillow", "apartments_com"
    source_url: Mapped[Optional[str]] = mapped_column(String(1024))

    # Address
    address: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(128))
    state: Mapped[Optional[str]] = mapped_column(String(64))
    postal_code: Mapped[Optional[str]] = mapped_column(String(16))
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Core facts
    bedrooms: Mapped[Optional[int]] = mapped_column(Integer)
    bathrooms: Mapped[Optional[float]] = mapped_column(Float)
    square_feet: Mapped[Optional[int]] = mapped_column(Integer)

    # Pricing — store rent and sale price separately
    monthly_rent: Mapped[Optional[int]] = mapped_column(Integer)
    sale_price: Mapped[Optional[int]] = mapped_column(Integer)

    # Geolocation (extension point — not populated by parser yet)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)

    # Status / lifecycle
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Raw source text (capped in application layer before insert)
    raw_source_text: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_properties_session_type", "session_id", "property_type"),
        Index("ix_properties_user_type", "user_id", "property_type"),
    )
