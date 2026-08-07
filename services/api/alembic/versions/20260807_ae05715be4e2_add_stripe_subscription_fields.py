"""add stripe subscription fields

Revision ID: ae05715be4e2
Revises: 0005_password_reset
Create Date: 2026-08-07 13:30:16.570491

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae05715be4e2'
down_revision: Union[str, None] = '0005_password_reset'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
    )

    op.add_column(
        "users",
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
    )

    op.add_column(
        "users",
        sa.Column(
            "trial_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "trial_ends_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "cancel_at_period_end")
    op.drop_column("users", "trial_ends_at")
    op.drop_column("users", "trial_used")
    op.drop_column("users", "stripe_subscription_id")
    op.drop_column("users", "stripe_customer_id")
