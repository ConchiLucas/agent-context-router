"""Add the local shared AI default.

Revision ID: 20260824_0057
Revises: 20260823_0056
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260824_0057"
down_revision: str | None = "20260823_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shared_ai_defaults",
        sa.Column("defaults_key", sa.String(32), primary_key=True),
        sa.Column("default_provider_id", sa.String(100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("defaults_key = 'default'", name="ck_shared_ai_defaults_key"),
        sa.CheckConstraint(
            "length(default_provider_id) > 0", name="ck_shared_ai_defaults_provider"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_shared_ai_defaults_revision"),
    )


def downgrade() -> None:
    op.drop_table("shared_ai_defaults")
