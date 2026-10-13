"""Add account-owned persistence and quotas without touching legacy data."""

from alembic import op
import sqlalchemy as sa

revision = "0007_account_services"
down_revision = "ae05715be4e2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_properties",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("parsed", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "external_id"),
    )
    op.create_index("ix_account_properties_user_id", "account_properties", ["user_id"])
    op.create_table(
        "account_units",
        sa.Column("property_id", sa.String(36), sa.ForeignKey("account_properties.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("parsed", sa.JSON, nullable=False),
    )
    op.create_table(
        "account_preferences",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("preferences", sa.JSON, nullable=False),
    )
    op.create_table(
        "account_monthly_usage",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("period", sa.String(7), primary_key=True),
        sa.Column("metric", sa.String(32), primary_key=True),
        sa.Column("count", sa.Integer, nullable=False),
    )
    op.create_table(
        "account_request_receipts",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    for name in ("account_request_receipts", "account_monthly_usage", "account_preferences", "account_units", "account_properties"):
        op.drop_table(name)
