"""Add AI task visualization conclusions.

Revision ID: 20260824_0062
Revises: 20260824_0061
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260824_0062"
down_revision: str | None = "20260824_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_task_visualization_results",
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("mcp_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("summary", sa.String(4000), nullable=False),
        sa.Column("root_cause", sa.String(4000), nullable=True),
        sa.Column(
            "code_locations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "suggested_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "verification",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column(
            "tool_call_id",
            sa.BigInteger(),
            sa.ForeignKey("mcp_tool_calls.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('investigating', 'resolved', 'failed')",
            name="ck_ai_task_visualization_status",
        ),
        sa.CheckConstraint("revision > 0", name="ck_ai_task_visualization_revision"),
    )
    op.create_index(
        "ix_ai_task_visualization_results_updated",
        "ai_task_visualization_results",
        [sa.text("updated_at DESC"), sa.text("task_id DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_task_visualization_results_updated",
        table_name="ai_task_visualization_results",
    )
    op.drop_table("ai_task_visualization_results")
