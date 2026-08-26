"""Bind environment and database contexts to MCP tasks.

Revision ID: 20260825_0064
Revises: 20260825_0063
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260825_0064"
down_revision: str | None = "20260825_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_environments",
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_workspace_environments_aliases_array",
        "workspace_environments",
        "jsonb_typeof(aliases) = 'array'",
    )
    op.execute(
        """
        UPDATE workspace_environments
        SET aliases = CASE environment_key
            WHEN 'local' THEN '["local", "本地", "本地环境"]'::jsonb
            WHEN 'test' THEN '["test", "测试", "测试环境"]'::jsonb
            WHEN 'uat' THEN '["uat", "验收", "验收环境", "预发布", "预发布环境"]'::jsonb
            ELSE jsonb_build_array(environment_key, display_name)
        END
        """
    )

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

    op.create_table(
        "mcp_database_contexts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("environment_revision", sa.Integer(), nullable=False),
        sa.Column("database_alias", sa.String(length=64), nullable=False),
        sa.Column("project_database_link_id", sa.String(length=32), nullable=False),
        sa.Column("physical_database", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "environment_revision > 0",
            name="ck_mcp_database_contexts_environment_revision",
        ),
        sa.CheckConstraint(
            "database_alias ~ '^[a-z][a-z0-9_-]{0,63}$'",
            name="ck_mcp_database_contexts_alias",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["mcp_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_database_contexts_task_expires",
        "mcp_database_contexts",
        ["task_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_database_contexts_task_expires",
        table_name="mcp_database_contexts",
    )
    op.drop_table("mcp_database_contexts")
    op.drop_constraint("ck_mcp_tasks_database_environment", "mcp_tasks", type_="check")
    op.execute(
        """
        UPDATE mcp_tasks
        SET database_environment_selection = 'task_explicit'
        WHERE database_environment_selection = 'task_description'
        """
    )
    op.create_check_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        """
        (database_environment IS NULL AND database_environment_revision IS NULL
         AND database_environment_selection IS NULL)
        OR
        (database_environment IS NOT NULL AND database_environment_revision > 0
         AND database_environment_selection IN ('workspace_default', 'task_explicit'))
        """,
    )
    op.drop_constraint(
        "ck_workspace_environments_aliases_array",
        "workspace_environments",
        type_="check",
    )
    op.drop_column("workspace_environments", "aliases")
