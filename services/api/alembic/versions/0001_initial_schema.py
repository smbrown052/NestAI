"""Initial schema — all NestAI tables

Revision ID: 0001
Revises:
Create Date: 2026-07-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("tier", sa.String(32), nullable=False, server_default="free"),
        sa.Column("beta_tester", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notes", sa.Text(), nullable=True),
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
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── buildings ─────────────────────────────────────────────────────────────
    op.create_table(
        "buildings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("building_key", sa.String(128), nullable=False),
        sa.Column("google_place_id", sa.String(255), nullable=True),
        sa.Column("building_name", sa.String(255), nullable=True),
        sa.Column("street_address", sa.String(255), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("state", sa.String(64), nullable=True),
        sa.Column("zip_code", sa.String(16), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("walk_score", sa.Integer(), nullable=True),
        sa.Column("walk_description", sa.String(128), nullable=True),
        sa.Column("transit_score", sa.Integer(), nullable=True),
        sa.Column("transit_description", sa.String(128), nullable=True),
        sa.Column("bike_score", sa.Integer(), nullable=True),
        sa.Column("bike_description", sa.String(128), nullable=True),
        sa.Column("grocery_count", sa.Integer(), nullable=True),
        sa.Column("restaurant_count", sa.Integer(), nullable=True),
        sa.Column("gym_count", sa.Integer(), nullable=True),
        sa.Column("park_count", sa.Integer(), nullable=True),
        sa.Column("cafe_count", sa.Integer(), nullable=True),
        sa.Column("nearest_metro", sa.String(255), nullable=True),
        sa.Column("nearest_metro_distance", sa.String(64), nullable=True),
        sa.Column("raw_listing_text", sa.Text(), nullable=True),
        sa.Column("last_enriched_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_buildings_id", "buildings", ["id"])
    op.create_index("ix_buildings_building_key", "buildings", ["building_key"], unique=True)
    op.create_index("ix_buildings_google_place_id", "buildings", ["google_place_id"])
    op.create_index("ix_buildings_street_address", "buildings", ["street_address"])

    # ── units ─────────────────────────────────────────────────────────────────
    op.create_table(
        "units",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("building_id", sa.Integer(), nullable=False),
        sa.Column("unit_number", sa.String(32), nullable=True),
        sa.Column("floorplan", sa.String(64), nullable=True),
        sa.Column("bedrooms", sa.Integer(), nullable=True),
        sa.Column("bathrooms", sa.Float(), nullable=True),
        sa.Column("rent_price", sa.Float(), nullable=True),
        sa.Column("square_feet", sa.Integer(), nullable=True),
        sa.Column("floor_level", sa.Integer(), nullable=True),
        sa.Column("availability_date", sa.String(64), nullable=True),
        sa.Column("amenities", sa.Text(), nullable=True),
        sa.Column("apartment_features", sa.Text(), nullable=True),
        sa.Column("rent_per_sqft", sa.Float(), nullable=True),
        sa.Column("deal_score", sa.Float(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["building_id"], ["buildings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_units_id", "units", ["id"])
    op.create_index("ix_units_building_id", "units", ["building_id"])

    # ── comparisons ───────────────────────────────────────────────────────────
    op.create_table(
        "comparisons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("share_token", sa.String(64), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("units_snapshot", sa.Text(), nullable=True),
        sa.Column("lifestyle_weights", sa.Text(), nullable=True),
        sa.Column("commute_destination", sa.String(255), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comparisons_id", "comparisons", ["id"])
    op.create_index("ix_comparisons_user_id", "comparisons", ["user_id"])
    op.create_index("ix_comparisons_share_token", "comparisons", ["share_token"], unique=True)

    # ── feedback_reports ──────────────────────────────────────────────────────
    op.create_table(
        "feedback_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_reference", sa.String(32), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("actual_behavior", sa.Text(), nullable=True),
        sa.Column("expected_behavior", sa.Text(), nullable=True),
        sa.Column("requested_feature", sa.Text(), nullable=True),
        sa.Column("problem_to_solve", sa.Text(), nullable=True),
        sa.Column("value_rating", sa.String(64), nullable=True),
        sa.Column("what_were_you_doing", sa.Text(), nullable=True),
        sa.Column("what_was_unclear", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(64), nullable=True),
        sa.Column("app_version", sa.String(32), nullable=True),
        sa.Column("build_number", sa.String(32), nullable=True),
        sa.Column("route_or_screen", sa.String(128), nullable=True),
        sa.Column("browser", sa.String(128), nullable=True),
        sa.Column("operating_system", sa.String(128), nullable=True),
        sa.Column("device_model", sa.String(128), nullable=True),
        sa.Column("comparison_id", sa.String(64), nullable=True),
        sa.Column("building_id", sa.String(64), nullable=True),
        sa.Column("unit_id", sa.String(64), nullable=True),
        sa.Column("ai_report_id", sa.String(64), nullable=True),
        sa.Column("error_correlation_id", sa.String(64), nullable=True),
        sa.Column("contact_email", sa.String(254), nullable=True),
        sa.Column("user_contact_allowed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("attachment_url", sa.String(512), nullable=True),
        sa.Column("user_plan", sa.String(32), nullable=True),
        sa.Column("beta_tester", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("unit_count", sa.Integer(), nullable=True),
        sa.Column("building_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="new"),
        sa.Column("severity", sa.String(32), nullable=True),
        sa.Column("priority", sa.String(32), nullable=True),
        sa.Column("duplicate_of_id", sa.Integer(), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
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
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["feedback_reports.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_reports_id", "feedback_reports", ["id"])
    op.create_index(
        "ix_feedback_reports_public_reference",
        "feedback_reports",
        ["public_reference"],
        unique=True,
    )
    op.create_index("ix_feedback_reports_user_id", "feedback_reports", ["user_id"])
    op.create_index("ix_feedback_reports_category", "feedback_reports", ["category"])
    op.create_index("ix_feedback_reports_status", "feedback_reports", ["status"])

    # ── beta_access ───────────────────────────────────────────────────────────
    op.create_table(
        "beta_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("redeemed_by_id", sa.Integer(), nullable=True),
        sa.Column("email_hint", sa.String(254), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["redeemed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_beta_access_id", "beta_access", ["id"])
    op.create_index("ix_beta_access_code", "beta_access", ["code"], unique=True)

    # ── credit_balances ───────────────────────────────────────────────────────
    op.create_table(
        "credit_balances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(32), nullable=False, server_default="free"),
        sa.Column("credits_remaining", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("credits_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credits_purchased", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_balances_id", "credit_balances", ["id"])
    op.create_index("ix_credit_balances_user_id", "credit_balances", ["user_id"], unique=True)

    # ── credit_transactions ───────────────────────────────────────────────────
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("transaction_type", sa.String(32), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("reference_id", sa.String(128), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_transactions_id", "credit_transactions", ["id"])
    op.create_index("ix_credit_transactions_user_id", "credit_transactions", ["user_id"])

    # ── billing_events ────────────────────────────────────────────────────────
    op.create_table(
        "billing_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="stripe"),
        sa.Column("provider_event_id", sa.String(255), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("tier_before", sa.String(32), nullable=True),
        sa.Column("tier_after", sa.String(32), nullable=True),
        sa.Column("credits_granted", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_events_id", "billing_events", ["id"])
    op.create_index("ix_billing_events_user_id", "billing_events", ["user_id"])
    op.create_index("ix_billing_events_event_type", "billing_events", ["event_type"])
    op.create_index(
        "ix_billing_events_provider_event_id",
        "billing_events",
        ["provider_event_id"],
        unique=True,
    )

    # ── ai_call_logs ──────────────────────────────────────────────────────────
    op.create_table(
        "ai_call_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("call_type", sa.String(64), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("cache_key", sa.String(128), nullable=True),
        sa.Column("was_cache_hit", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_call_logs_id", "ai_call_logs", ["id"])
    op.create_index("ix_ai_call_logs_user_id", "ai_call_logs", ["user_id"])
    op.create_index("ix_ai_call_logs_call_type", "ai_call_logs", ["call_type"])


def downgrade() -> None:
    op.drop_table("ai_call_logs")
    op.drop_table("billing_events")
    op.drop_table("credit_transactions")
    op.drop_table("credit_balances")
    op.drop_table("beta_access")
    op.drop_table("feedback_reports")
    op.drop_table("comparisons")
    op.drop_table("units")
    op.drop_table("buildings")
    op.drop_table("users")
