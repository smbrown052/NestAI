"""Property platform expansion — Phase 2 schema additions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-23

Additive only.  No existing tables are modified or dropped.

New tables:
    properties      — generic property record (all types)
    home_details    — extended details for HOME_FOR_SALE / RENTAL_HOME
    usage_events    — audit trail for platform actions

Column additions to existing tables:
    users.plan      — new canonical plan column
                      (extends existing `tier` column; both coexist during migration)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: add plan column ──────────────────────────────────────────────────
    # `tier` is kept for backward compatibility.  `plan` is the new canonical
    # column and supports the expanded plan values (FREE, PREMIUM, PREMIUM_PLUS,
    # BETA).  Application code should migrate reads to `plan` over time.
    op.add_column(
        "users",
        sa.Column("plan", sa.String(32), nullable=False, server_default="FREE"),
    )

    # ── properties ─────────────────────────────────────────────────────────────
    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("property_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("address", sa.String(255), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("state", sa.String(64), nullable=True),
        sa.Column("postal_code", sa.String(16), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("bedrooms", sa.Integer(), nullable=True),
        sa.Column("bathrooms", sa.Float(), nullable=True),
        sa.Column("square_feet", sa.Integer(), nullable=True),
        sa.Column("monthly_rent", sa.Integer(), nullable=True),
        sa.Column("sale_price", sa.Integer(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("raw_source_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_properties_id", "properties", ["id"])
    op.create_index("ix_properties_user_id", "properties", ["user_id"])
    op.create_index("ix_properties_session_id", "properties", ["session_id"])
    op.create_index("ix_properties_property_type", "properties", ["property_type"])
    op.create_index(
        "ix_properties_session_type", "properties", ["session_id", "property_type"]
    )
    op.create_index(
        "ix_properties_user_type", "properties", ["user_id", "property_type"]
    )

    # ── home_details ────────────────────────────────────────────────────────────
    op.create_table(
        "home_details",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("property_subtype", sa.String(64), nullable=True),
        sa.Column("lot_size", sa.Float(), nullable=True),
        sa.Column("lot_size_unit", sa.String(32), nullable=True),
        sa.Column("year_built", sa.Integer(), nullable=True),
        sa.Column("hoa_amount", sa.Integer(), nullable=True),
        sa.Column("hoa_frequency", sa.String(32), nullable=True),
        sa.Column("annual_property_tax", sa.Integer(), nullable=True),
        sa.Column("estimated_monthly_payment", sa.Integer(), nullable=True),
        sa.Column("garage_spaces", sa.Integer(), nullable=True),
        sa.Column("garage_type", sa.String(64), nullable=True),
        sa.Column("basement", sa.Boolean(), nullable=True),
        sa.Column("fireplace", sa.Boolean(), nullable=True),
        sa.Column("stories", sa.Integer(), nullable=True),
        sa.Column("days_on_market", sa.Integer(), nullable=True),
        sa.Column("days_on_zillow", sa.Integer(), nullable=True),
        sa.Column("hours_on_zillow", sa.Integer(), nullable=True),
        sa.Column("listing_status", sa.String(64), nullable=True),
        sa.Column("listing_agent", sa.String(255), nullable=True),
        sa.Column("brokerage", sa.String(255), nullable=True),
        sa.Column("cooling", sa.String(255), nullable=True),
        sa.Column("heating", sa.String(128), nullable=True),
        sa.Column("parking", sa.String(255), nullable=True),
        sa.Column("laundry", sa.String(128), nullable=True),
        sa.Column("features_json", sa.Text(), nullable=True),
        sa.Column("schools_json", sa.Text(), nullable=True),
        sa.Column("walk_score", sa.Integer(), nullable=True),
        sa.Column("transit_score", sa.Integer(), nullable=True),
        sa.Column("bike_score", sa.Integer(), nullable=True),
        sa.Column("available_date", sa.String(128), nullable=True),
        sa.Column("pets_policy", sa.String(255), nullable=True),
        sa.Column("school_quality_json", sa.Text(), nullable=True),
        sa.Column("walkability_json", sa.Text(), nullable=True),
        sa.Column("investment_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("property_id"),
    )
    op.create_index("ix_home_details_id", "home_details", ["id"])
    op.create_index("ix_home_details_property_id", "home_details", ["property_id"])

    # ── usage_events ────────────────────────────────────────────────────────────
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("plan", sa.String(32), nullable=True),
        sa.Column("property_type", sa.String(32), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_usage_events_id", "usage_events", ["id"])
    op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"])
    op.create_index("ix_usage_events_session_id", "usage_events", ["session_id"])
    op.create_index("ix_usage_events_event_type", "usage_events", ["event_type"])
    op.create_index("ix_usage_events_occurred_at", "usage_events", ["occurred_at"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("usage_events")
    op.drop_table("home_details")
    op.drop_table("properties")
    op.drop_column("users", "plan")
