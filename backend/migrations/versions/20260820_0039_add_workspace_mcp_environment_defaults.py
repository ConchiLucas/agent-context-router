"""Add per-tool Workspace MCP environment defaults.

Revision ID: 20260820_0039
Revises: 20260818_0038
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0039"
down_revision: str | None = "20260818_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_mcp_environment_defaults",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("default_environment", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(tool_name = 'prepare_task_context' "
            "AND default_environment IN ('test','uat')) OR "
            "(tool_name = 'read_middleware_context' "
            "AND default_environment IN ('local','test','uat')) OR "
            "(tool_name IN ('read_table_relations','search_relation_tables') "
            "AND default_environment IN ('test','uat'))",
            name="ck_workspace_mcp_environment_defaults_tool_environment",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "tool_name"),
    )

    op.drop_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        type_="check",
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
                'task_explicit',
                'tool_default'
            )
        )
        """,
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE mcp_tasks
        SET database_environment_selection = 'task_explicit'
        WHERE database_environment_selection = 'tool_default'
        """
    )
    op.drop_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        type_="check",
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
    op.drop_table("workspace_mcp_environment_defaults")
