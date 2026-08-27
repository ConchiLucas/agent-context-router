"""Add automatic interface-search quality and outcome events.

Revision ID: 20260827_0070
Revises: 20260827_0069
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260827_0070"
down_revision: str | None = "20260827_0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interface_forwarding_search_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("mcp_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("environment_key", sa.String(32), nullable=False),
        sa.Column(
            "tool_call_id",
            sa.BigInteger(),
            sa.ForeignKey("mcp_tool_calls.id", ondelete="SET NULL"),
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column(
            "parsed_intent",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("returned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("match_confidence", sa.String(16), nullable=False),
        sa.Column(
            "result_ranking",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "recommended_interface_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_interfaces.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "selected_interface_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_interfaces.id", ondelete="SET NULL"),
        ),
        sa.Column("selected_rank", sa.Integer()),
        sa.Column("selected_at", sa.DateTime(timezone=True)),
        sa.Column(
            "execution_log_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_logs.id", ondelete="SET NULL"),
        ),
        sa.Column("execution_success", sa.Boolean()),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "match_confidence IN ('high', 'medium', 'low')",
            name="ck_interface_forwarding_search_confidence",
        ),
        sa.CheckConstraint(
            "selected_rank IS NULL OR selected_rank > 0",
            name="ck_interface_forwarding_search_selected_rank",
        ),
    )
    op.create_index(
        "ix_interface_forwarding_search_task_created",
        "interface_forwarding_search_events",
        ["task_id", "created_at"],
    )
    op.create_index(
        "ix_interface_forwarding_search_workspace_created",
        "interface_forwarding_search_events",
        ["workspace_id", "created_at"],
    )
    op.add_column(
        "interface_forwarding_request_plans",
        sa.Column(
            "search_event_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_search_events.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    op.drop_column("interface_forwarding_request_plans", "search_event_id")
    op.drop_index(
        "ix_interface_forwarding_search_workspace_created",
        table_name="interface_forwarding_search_events",
    )
    op.drop_index(
        "ix_interface_forwarding_search_task_created",
        table_name="interface_forwarding_search_events",
    )
    op.drop_table("interface_forwarding_search_events")
