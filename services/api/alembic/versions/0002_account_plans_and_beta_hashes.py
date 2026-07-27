"""Account plans and hashed beta invites

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-27

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pwdlib import PasswordHash

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("active_plan", sa.String(32), nullable=False, server_default="free"),
    )
    op.add_column(
        "users",
        sa.Column("requested_plan", sa.String(32), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("subscription_status", sa.String(32), nullable=False, server_default="active"),
    )
    op.add_column(
        "users",
        sa.Column("payment_customer_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("payment_subscription_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("beta_approved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.alter_column("beta_access", "code", existing_type=sa.String(length=64), type_=sa.String(length=255), existing_nullable=False)

    connection = op.get_bind()
    password_hasher = PasswordHash.recommended()

    user_rows = connection.execute(sa.text("SELECT id, tier, beta_tester FROM users")).fetchall()
    for row in user_rows:
        active_plan = "beta" if row.beta_tester else (row.tier or "free")
        connection.execute(
            sa.text(
                """
                UPDATE users
                SET active_plan = :active_plan,
                    subscription_status = 'active',
                    beta_approved_at = CASE WHEN :is_beta THEN COALESCE(beta_approved_at, now()) ELSE beta_approved_at END
                WHERE id = :user_id
                """
            ),
            {"active_plan": active_plan, "is_beta": bool(row.beta_tester), "user_id": row.id},
        )

    beta_rows = connection.execute(sa.text("SELECT id, code FROM beta_access")).fetchall()
    for row in beta_rows:
        if row.code and not row.code.startswith("$"):
            hashed = password_hasher.hash(row.code)
            connection.execute(
                sa.text("UPDATE beta_access SET code = :hashed WHERE id = :invite_id"),
                {"hashed": hashed, "invite_id": row.id},
            )


def downgrade() -> None:
    op.alter_column("beta_access", "code", existing_type=sa.String(length=255), type_=sa.String(length=64), existing_nullable=False)
    op.drop_column("users", "beta_approved_at")
    op.drop_column("users", "payment_subscription_id")
    op.drop_column("users", "payment_customer_id")
    op.drop_column("users", "subscription_status")
    op.drop_column("users", "requested_plan")
    op.drop_column("users", "active_plan")
