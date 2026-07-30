"""Add task-level database environment selection mode.

Revision ID: 20260730_0021
Revises: 20260730_0020
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260730_0021"
down_revision: str | None = "20260730_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_tasks",
        sa.Column(
            "database_environment_selection",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.drop_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        type_="check",
    )
    # The 0019 check used nullable boolean expressions, so PostgreSQL could
    # accept legacy rows where only one side of the environment snapshot was
    # NULL. Normalize those partial snapshots before installing the stricter
    # three-field constraint.
    op.execute(
        """
        UPDATE mcp_tasks
        SET database_environment = NULL,
            database_environment_revision = NULL
        WHERE (database_environment IS NULL)
           <> (database_environment_revision IS NULL)
        """
    )
    op.execute(
        """
        UPDATE mcp_tasks
        SET database_environment_selection = 'workspace_default'
        WHERE database_environment IS NOT NULL
          AND database_environment_revision IS NOT NULL
        """
    )
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
            AND database_environment IN ('test','uat')
            AND database_environment_revision IS NOT NULL
            AND database_environment_revision > 0
            AND database_environment_selection IS NOT NULL
            AND database_environment_selection IN (
                'workspace_default',
                'task_explicit'
            )
        )
        """,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        type_="check",
    )
    op.drop_column("mcp_tasks", "database_environment_selection")
    op.create_check_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        """
        (
            database_environment IS NULL
            AND database_environment_revision IS NULL
        )
        OR (
            database_environment IN ('test','uat')
            AND database_environment_revision > 0
        )
        """,
    )
