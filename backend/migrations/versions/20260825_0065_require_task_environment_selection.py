"""Require a source for every task-owned environment.

Revision ID: 20260825_0065
Revises: 20260825_0064
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260825_0065"
down_revision: str | None = "20260825_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_mcp_tasks_database_environment", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        """
        (
            database_environment IS NULL
            AND database_environment_revision IS NULL
            AND database_environment_selection IS NULL
        )
        OR (
            database_environment IS NOT NULL
            AND database_environment ~ '^[a-z][a-z0-9_-]{0,31}$'
            AND database_environment_revision IS NOT NULL
            AND database_environment_revision > 0
            AND database_environment_selection IS NOT NULL
            AND database_environment_selection IN (
                'workspace_default', 'task_explicit', 'task_description'
            )
        )
        """,
    )


def downgrade() -> None:
    op.drop_constraint("ck_mcp_tasks_database_environment", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        """
        (
            database_environment IS NULL
            AND database_environment_revision IS NULL
            AND database_environment_selection IS NULL
        )
        OR (
            database_environment IS NOT NULL
            AND database_environment ~ '^[a-z][a-z0-9_-]{0,31}$'
            AND database_environment_revision IS NOT NULL
            AND database_environment_revision > 0
            AND database_environment_selection IN (
                'workspace_default', 'task_explicit', 'task_description'
            )
        )
        """,
    )
