"""Additive account-owned records; never claim legacy session records."""

from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class AccountProperty(Base):
    __tablename__ = "account_properties"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    parsed: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "external_id"),)


class AccountUnit(Base):
    __tablename__ = "account_units"
    property_id: Mapped[str] = mapped_column(ForeignKey("account_properties.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    parsed: Mapped[dict] = mapped_column(JSON)


class AccountPreference(Base):
    __tablename__ = "account_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)


class MonthlyUsage(Base):
    __tablename__ = "account_monthly_usage"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    period: Mapped[str] = mapped_column(String(7), primary_key=True)
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class RequestReceipt(Base):
    __tablename__ = "account_request_receipts"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
