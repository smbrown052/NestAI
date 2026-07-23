"""HomeDetails — extended attributes for HOME_FOR_SALE and RENTAL_HOME properties.

Linked to ``properties`` via ``property_id``.  One-to-one relationship.

Fields are nullable by design; the Zillow parser populates what it finds.
Extension-point fields (school_quality_json, walkability_json, investment_json)
are present but never populated in this phase — they exist so future phases
can fill them without a schema migration.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HomeDetails(Base):
    __tablename__ = "home_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    property_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    # Home-specific facts
    property_subtype: Mapped[Optional[str]] = mapped_column(String(64))
    lot_size: Mapped[Optional[float]] = mapped_column(Float)
    lot_size_unit: Mapped[Optional[str]] = mapped_column(String(32))   # "sqft" | "acres"
    year_built: Mapped[Optional[int]] = mapped_column(Integer)

    # HOA
    hoa_amount: Mapped[Optional[int]] = mapped_column(Integer)
    hoa_frequency: Mapped[Optional[str]] = mapped_column(String(32))   # "monthly" | "annual"

    # Financials
    annual_property_tax: Mapped[Optional[int]] = mapped_column(Integer)
    estimated_monthly_payment: Mapped[Optional[int]] = mapped_column(Integer)

    # Garage / basement / fireplace / stories
    garage_spaces: Mapped[Optional[int]] = mapped_column(Integer)
    garage_type: Mapped[Optional[str]] = mapped_column(String(64))
    basement: Mapped[Optional[bool]] = mapped_column(Boolean)
    fireplace: Mapped[Optional[bool]] = mapped_column(Boolean)
    stories: Mapped[Optional[int]] = mapped_column(Integer)

    # Market timing
    days_on_market: Mapped[Optional[int]] = mapped_column(Integer)
    days_on_zillow: Mapped[Optional[int]] = mapped_column(Integer)
    hours_on_zillow: Mapped[Optional[int]] = mapped_column(Integer)
    listing_status: Mapped[Optional[str]] = mapped_column(String(64))

    # Listing agents
    listing_agent: Mapped[Optional[str]] = mapped_column(String(255))
    brokerage: Mapped[Optional[str]] = mapped_column(String(255))

    # Utility and feature detail (JSON arrays / free text)
    cooling: Mapped[Optional[str]] = mapped_column(String(255))
    heating: Mapped[Optional[str]] = mapped_column(String(128))
    parking: Mapped[Optional[str]] = mapped_column(String(255))
    laundry: Mapped[Optional[str]] = mapped_column(String(128))
    features_json: Mapped[Optional[str]] = mapped_column(Text)         # JSON array
    schools_json: Mapped[Optional[str]] = mapped_column(Text)          # JSON array

    # Walk / Transit / Bike scores
    walk_score: Mapped[Optional[int]] = mapped_column(Integer)
    transit_score: Mapped[Optional[int]] = mapped_column(Integer)
    bike_score: Mapped[Optional[int]] = mapped_column(Integer)

    # Availability
    available_date: Mapped[Optional[str]] = mapped_column(String(128))
    pets_policy: Mapped[Optional[str]] = mapped_column(String(255))

    # Extension points — NOT populated in Phase 1
    school_quality_json: Mapped[Optional[str]] = mapped_column(Text)   # future: school ratings
    walkability_json: Mapped[Optional[str]] = mapped_column(Text)      # future: walkability details
    investment_json: Mapped[Optional[str]] = mapped_column(Text)       # future: investment signals

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
