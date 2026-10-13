"""Preserve trusted beta grants separately from Stripe subscriptions."""

from alembic import op
import sqlalchemy as sa

revision = "0008_beta_grants"
down_revision = "0007_account_services"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("beta_access_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("beta_limits", sa.JSON, nullable=True))
    op.add_column("users", sa.Column("beta_features", sa.JSON, nullable=True))


def downgrade():
    for name in ("beta_features", "beta_limits", "beta_access_expires_at"):
        op.drop_column("users", name)
