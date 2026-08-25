"""Add task intent execution contract.

Revision ID: 20260825_0063
Revises: 20260824_0062
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_0063"
down_revision: str | None = "20260824_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_tasks",
        sa.Column(
            "intent_type",
            sa.String(32),
            nullable=False,
            server_default="task_execute",
        ),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column(
            "intent_error_signal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column("intent_summary", sa.String(1000), nullable=True),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column(
            "intent_source",
            sa.String(32),
            nullable=False,
            server_default="compatibility_default",
        ),
    )
    op.create_check_constraint(
        "ck_mcp_tasks_intent_type",
        "mcp_tasks",
        "intent_type IN ('interface_execute', 'data_query', 'task_execute', "
        "'bug_investigate', 'bug_fix')",
    )
    op.create_check_constraint(
        "ck_mcp_tasks_intent_source",
        "mcp_tasks",
        "intent_source IN ('agent_declared', 'compatibility_default', 'system_default')",
    )
    op.create_check_constraint(
        "ck_mcp_tasks_error_signal_intent",
        "mcp_tasks",
        "NOT intent_error_signal OR intent_type IN ('bug_investigate', 'bug_fix')",
    )
    op.create_index("ix_mcp_tasks_intent_type", "mcp_tasks", ["intent_type"])


def downgrade() -> None:
    op.drop_index("ix_mcp_tasks_intent_type", table_name="mcp_tasks")
    op.drop_constraint("ck_mcp_tasks_error_signal_intent", "mcp_tasks", type_="check")
    op.drop_constraint("ck_mcp_tasks_intent_source", "mcp_tasks", type_="check")
    op.drop_constraint("ck_mcp_tasks_intent_type", "mcp_tasks", type_="check")
    op.drop_column("mcp_tasks", "intent_source")
    op.drop_column("mcp_tasks", "intent_summary")
    op.drop_column("mcp_tasks", "intent_error_signal")
    op.drop_column("mcp_tasks", "intent_type")
