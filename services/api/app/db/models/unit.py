"""Unit model — individual apartment units extracted from a listing."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    building_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_number: Mapped[str | None] = mapped_column(String(32))
    floorplan: Mapped[str | None] = mapped_column(String(64))
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    bathrooms: Mapped[float | None] = mapped_column(Float)
    rent_price: Mapped[float | None] = mapped_column(Float)
    square_feet: Mapped[int | None] = mapped_column(Integer)
    floor_level: Mapped[int | None] = mapped_column(Integer)
    availability_date: Mapped[str | None] = mapped_column(String(64))
    amenities: Mapped[str | None] = mapped_column(Text)   # JSON array
    apartment_features: Mapped[str | None] = mapped_column(Text)   # JSON array
    rent_per_sqft: Mapped[float | None] = mapped_column(Float)
    deal_score: Mapped[float | None] = mapped_column(Float)
    raw_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    building = relationship("Building", back_populates=None)
