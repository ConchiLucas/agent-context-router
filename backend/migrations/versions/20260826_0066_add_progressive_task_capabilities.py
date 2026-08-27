"""Add progressive task capabilities and code-change intent.

Revision ID: 20260826_0066
Revises: 20260825_0065
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_0066"
down_revision: str | None = "20260825_0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_mcp_tasks_intent_type", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_intent_type",
        "mcp_tasks",
        "intent_type IN ('interface_execute', 'data_query', 'task_execute', "
        "'bug_investigate', 'bug_fix', 'code_change')",
    )
    op.add_column(
        "mcp_tasks",
        sa.Column(
            "workflow_stage",
            sa.String(32),
            nullable=False,
            server_default="prepared",
        ),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column(
            "capability_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_mcp_tasks_capability_revision",
        "mcp_tasks",
        "capability_revision >= 1",
    )
    op.create_table(
        "mcp_task_capability_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("evidence_call_id", sa.BigInteger(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("revision >= 1", name="ck_mcp_task_capability_events_revision"),
        sa.ForeignKeyConstraint(["task_id"], ["mcp_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["evidence_call_id"],
            ["mcp_tool_calls.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "capability",
            name="uq_mcp_task_capability_events_task_capability",
        ),
    )
    op.create_index(
        "ix_mcp_task_capability_events_task_id_id",
        "mcp_task_capability_events",
        ["task_id", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_task_capability_events_task_id_id",
        table_name="mcp_task_capability_events",
    )
    op.drop_table("mcp_task_capability_events")
    op.drop_constraint("ck_mcp_tasks_capability_revision", "mcp_tasks", type_="check")
    op.drop_column("mcp_tasks", "capability_revision")
    op.drop_column("mcp_tasks", "workflow_stage")
    op.drop_constraint("ck_mcp_tasks_intent_type", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_intent_type",
        "mcp_tasks",
        "intent_type IN ('interface_execute', 'data_query', 'task_execute', "
        "'bug_investigate', 'bug_fix')",
    )
