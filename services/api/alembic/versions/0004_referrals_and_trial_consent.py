"""Referrals and trial consent support

Revision ID: 0004_referrals_trial
Revises: 0003_account_plans
Create Date: 2026-08-03
"""

from __future__ import annotations

import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_referrals_trial"
down_revision: Union[str, None] = "0003_account_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ref_code() -> str:
    return f"nest-{secrets.token_urlsafe(6).replace('-', '').replace('_', '').lower()[:10]}"


def upgrade() -> None:
    op.add_column("users", sa.Column("referrer_id", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("referral_code", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("referral_credit_cents", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_users_referrer_id", "users", ["referrer_id"])
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)
    op.create_foreign_key(
        "fk_users_referrer_id_users",
        "users",
        "users",
        ["referrer_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referrer_user_id", sa.Integer(), nullable=False),
        sa.Column("referred_user_id", sa.Integer(), nullable=True),
        sa.Column("referred_email", sa.String(length=254), nullable=False),
        sa.Column("referral_code", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="invited"),
        sa.Column("reward_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_referrals_id", "referrals", ["id"])
    op.create_index("ix_referrals_referrer_user_id", "referrals", ["referrer_user_id"])
    op.create_index("ix_referrals_referred_user_id", "referrals", ["referred_user_id"])
    op.create_index("ix_referrals_referred_email", "referrals", ["referred_email"])
    op.create_index("ix_referrals_referral_code", "referrals", ["referral_code"])

    connection = op.get_bind()
    user_rows = connection.execute(sa.text("SELECT id FROM users WHERE referral_code IS NULL OR referral_code = ''")).fetchall()
    for row in user_rows:
        code = _ref_code()
        while connection.execute(sa.text("SELECT 1 FROM users WHERE referral_code = :code"), {"code": code}).first():
            code = _ref_code()
        connection.execute(
            sa.text("UPDATE users SET referral_code = :code WHERE id = :user_id"),
            {"code": code, "user_id": row.id},
        )

    if connection.dialect.name != "sqlite":
        op.alter_column("users", "referral_code", nullable=False)


def downgrade() -> None:
    op.drop_index("ix_referrals_referral_code", table_name="referrals")
    op.drop_index("ix_referrals_referred_email", table_name="referrals")
    op.drop_index("ix_referrals_referred_user_id", table_name="referrals")
    op.drop_index("ix_referrals_referrer_user_id", table_name="referrals")
    op.drop_index("ix_referrals_id", table_name="referrals")
    op.drop_table("referrals")
    op.drop_constraint("fk_users_referrer_id_users", "users", type_="foreignkey")
    op.drop_index("ix_users_referral_code", table_name="users")
    op.drop_index("ix_users_referrer_id", table_name="users")
    op.drop_column("users", "referral_credit_cents")
    op.drop_column("users", "referral_code")
    op.drop_column("users", "referrer_id")
