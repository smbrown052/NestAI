"""
Building model — mirrors the buildings table in the legacy SQLite cache,
promoted to PostgreSQL with typed columns.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Canonical key — Google Place ID when available, else address hash.
    building_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    google_place_id: Mapped[str | None] = mapped_column(String(255), index=True)
    building_name: Mapped[str | None] = mapped_column(String(255))
    street_address: Mapped[str | None] = mapped_column(String(255), index=True)
    city: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str | None] = mapped_column(String(64))
    zip_code: Mapped[str | None] = mapped_column(String(16))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # Walk / transit / bike scores
    walk_score: Mapped[int | None] = mapped_column(Integer)
    walk_description: Mapped[str | None] = mapped_column(String(128))
    transit_score: Mapped[int | None] = mapped_column(Integer)
    transit_description: Mapped[str | None] = mapped_column(String(128))
    bike_score: Mapped[int | None] = mapped_column(Integer)
    bike_description: Mapped[str | None] = mapped_column(String(128))
    # Nearby places counts
    grocery_count: Mapped[int | None] = mapped_column(Integer)
    restaurant_count: Mapped[int | None] = mapped_column(Integer)
    gym_count: Mapped[int | None] = mapped_column(Integer)
    park_count: Mapped[int | None] = mapped_column(Integer)
    cafe_count: Mapped[int | None] = mapped_column(Integer)
    nearest_metro: Mapped[str | None] = mapped_column(String(255))
    nearest_metro_distance: Mapped[str | None] = mapped_column(String(64))
    raw_listing_text: Mapped[str | None] = mapped_column(Text)
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
