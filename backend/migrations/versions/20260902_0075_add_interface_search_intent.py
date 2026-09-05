"""Add a read-only interface search task intent.

Revision ID: 20260902_0075
Revises: 20260902_0074
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260902_0075"
down_revision: str | None = "20260902_0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_mcp_tasks_intent_type", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_intent_type",
        "mcp_tasks",
        "intent_type IN ('interface_search', 'interface_execute', 'data_query', "
        "'task_execute', 'bug_investigate', 'bug_fix')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE mcp_tasks SET intent_type='task_execute' "
        "WHERE intent_type='interface_search'"
    )
    op.drop_constraint("ck_mcp_tasks_intent_type", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_intent_type",
        "mcp_tasks",
        "intent_type IN ('interface_execute', 'data_query', 'task_execute', "
        "'bug_investigate', 'bug_fix')",
    )
