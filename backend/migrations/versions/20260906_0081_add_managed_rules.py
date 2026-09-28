"""Add control-plane rules delivered by prepare_task_context.

Revision ID: 20260906_0081
Revises: 20260905_0080
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260906_0081"
down_revision: str | None = "20260905_0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "managed_rules",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint("slug", name="uq_managed_rules_slug"),
        sa.CheckConstraint("length(slug) > 0", name="ck_managed_rules_slug"),
        sa.CheckConstraint("length(title) > 0", name="ck_managed_rules_title"),
        sa.CheckConstraint("length(body) > 0", name="ck_managed_rules_body"),
    )
    op.create_index("ix_managed_rules_sort", "managed_rules", ["sort_order", "title"])


def downgrade() -> None:
    op.drop_index("ix_managed_rules_sort", table_name="managed_rules")
    op.drop_table("managed_rules")
