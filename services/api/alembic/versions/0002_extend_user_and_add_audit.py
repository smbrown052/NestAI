"""Extend user fields, credit balance, add audit_logs, beta_invitations

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: add new columns ─────────────────────────────────────────────────
    op.add_column("users", sa.Column("role", sa.String(32), nullable=False, server_default="user"))
    op.add_column("users", sa.Column("last_login", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("premium_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("premium_expiration", sa.DateTime(timezone=True), nullable=True))

    # Sync role with existing is_admin values.
    op.execute(
        "UPDATE users SET role = 'admin' WHERE is_admin = TRUE"
    )

    # Tier can now also be "beta"; extend allowed values by documentation only
    # (no CHECK constraint was defined — no DDL change needed).

    # ── credit_balances: add per-feature credit columns ────────────────────────
    op.add_column("credit_balances", sa.Column(
        "ai_credits_remaining", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("credit_balances", sa.Column(
        "ai_credits_used", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("credit_balances", sa.Column(
        "commute_credits_remaining", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("credit_balances", sa.Column(
        "commute_credits_used", sa.Integer(), nullable=False, server_default="0"
    ))

    # ── credit_transactions: add credit_type column ────────────────────────────
    op.add_column("credit_transactions", sa.Column(
        "credit_type", sa.String(32), nullable=False, server_default="building"
    ))

    # ── beta_invitations ───────────────────────────────────────────────────────
    op.create_table(
        "beta_invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invited_by_id", sa.Integer(), nullable=True),
        sa.Column("accepted_by_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("building_analyses", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("ai_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("commute_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("premium_features", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("beta_expiration", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["accepted_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_beta_invitations_id", "beta_invitations", ["id"])
    op.create_index("ix_beta_invitations_email", "beta_invitations", ["email"])
    op.create_index("ix_beta_invitations_token", "beta_invitations", ["token"], unique=True)
    op.create_index("ix_beta_invitations_status", "beta_invitations", ["status"])
    op.create_index("ix_beta_invitations_invited_by_id", "beta_invitations", ["invited_by_id"])

    # ── audit_logs ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=True),
        sa.Column("affected_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("previous_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["affected_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_admin_id", "audit_logs", ["admin_id"])
    op.create_index("ix_audit_logs_affected_user_id", "audit_logs", ["affected_user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("beta_invitations")
    op.drop_column("credit_transactions", "credit_type")
    op.drop_column("credit_balances", "commute_credits_used")
    op.drop_column("credit_balances", "commute_credits_remaining")
    op.drop_column("credit_balances", "ai_credits_used")
    op.drop_column("credit_balances", "ai_credits_remaining")
    op.drop_column("users", "premium_expiration")
    op.drop_column("users", "premium_start")
    op.drop_column("users", "last_login")
    op.drop_column("users", "role")
