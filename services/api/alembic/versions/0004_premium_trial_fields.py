"""Add premium trial fields to users

Revision ID: 0004_premium_trial_fields
Revises: 0003_account_plans
Create Date: 2026-07-28

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_premium_trial_fields"
down_revision: Union[str, None] = "0003_account_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("premium_trial_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("premium_trial_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "premium_trial_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "premium_trial_used")
    op.drop_column("users", "premium_trial_ends_at")
    op.drop_column("users", "premium_trial_started_at")
