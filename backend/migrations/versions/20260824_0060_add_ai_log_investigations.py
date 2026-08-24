"""Add AI Docker log investigation snapshots.

Revision ID: 20260824_0060
Revises: 20260824_0059
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260824_0060"
down_revision: str | None = "20260824_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_log_investigations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("mcp_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("container_id", sa.String(64), nullable=False),
        sa.Column("container_name", sa.String(255), nullable=False),
        sa.Column("image", sa.String(500), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("project_name", sa.String(255), nullable=True),
        sa.Column("project_kind", sa.String(16), nullable=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("error_title", sa.String(240), nullable=False),
        sa.Column("error_excerpt", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("log_line_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
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
        sa.CheckConstraint("severity IN ('error', 'critical')", name="ck_ai_log_severity"),
        sa.CheckConstraint("occurrence_count > 0", name="ck_ai_log_occurrence_count"),
        sa.CheckConstraint("log_line_count > 0", name="ck_ai_log_line_count"),
    )
    op.create_index(
        "ix_ai_log_investigations_updated",
        "ai_log_investigations",
        [sa.text("updated_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_ai_log_investigations_workspace_updated",
        "ai_log_investigations",
        ["workspace_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_log_investigations_workspace_updated",
        table_name="ai_log_investigations",
    )
    op.drop_index(
        "ix_ai_log_investigations_updated",
        table_name="ai_log_investigations",
    )
    op.drop_table("ai_log_investigations")
