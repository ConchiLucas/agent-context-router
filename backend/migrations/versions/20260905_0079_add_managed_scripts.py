"""Add managed host scripts for boot and global actions.

Revision ID: 20260905_0079
Revises: 20260905_0078
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260905_0079"
down_revision: str | None = "20260905_0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "managed_scripts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("action_key", sa.String(64), nullable=False),
        sa.Column("workspace_id", sa.String(32), nullable=True),
        sa.Column("autostart_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("slug", name="uq_managed_scripts_slug"),
        sa.CheckConstraint("kind IN ('autostart', 'global')", name="ck_managed_scripts_kind"),
        sa.CheckConstraint(
            "action_key IN ('native_stack_start', 'host_runtime_ensure', "
            "'restore_shared_files', 'sync_scripts')",
            name="ck_managed_scripts_action",
        ),
        sa.CheckConstraint("length(slug) > 0", name="ck_managed_scripts_slug"),
        sa.CheckConstraint("length(name) > 0", name="ck_managed_scripts_name"),
    )
    op.create_index("ix_managed_scripts_kind_sort", "managed_scripts", ["kind", "sort_order"])


def downgrade() -> None:
    op.drop_index("ix_managed_scripts_kind_sort", table_name="managed_scripts")
    op.drop_table("managed_scripts")
