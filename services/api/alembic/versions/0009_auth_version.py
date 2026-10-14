"""Add account-wide bearer-session revocation without changing user data."""

from alembic import op
import sqlalchemy as sa

revision = "0009_auth_version"
down_revision = "0008_beta_grants"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("users", "auth_version")
