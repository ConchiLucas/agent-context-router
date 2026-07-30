"""Remove business-entity enabled flags.

Revision ID: 20260730_0022
Revises: 20260730_0021
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260730_0022"
down_revision: str | None = "20260730_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_workspaces_enabled_created_at", table_name="workspaces")
    op.drop_index("ix_project_databases_project", table_name="project_databases")
    op.drop_index("ix_project_databases_workspace", table_name="project_databases")

    op.drop_column("workspace_database_environment_configs", "enabled")
    op.drop_column("project_databases", "enabled")
    op.drop_column("data_sources", "enabled")
    op.drop_column("workspaces", "enabled")

    op.create_index(
        "ix_workspaces_created_at",
        "workspaces",
        ["created_at"],
    )
    op.create_index(
        "ix_project_databases_project",
        "project_databases",
        ["project_id"],
    )
    op.create_index(
        "ix_project_databases_workspace",
        "project_databases",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_databases_workspace", table_name="project_databases")
    op.drop_index("ix_project_databases_project", table_name="project_databases")
    op.drop_index("ix_workspaces_created_at", table_name="workspaces")

    op.add_column(
        "workspaces",
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "data_sources",
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "project_databases",
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "workspace_database_environment_configs",
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_project_databases_project",
        "project_databases",
        ["project_id", "enabled"],
    )
    op.create_index(
        "ix_project_databases_workspace",
        "project_databases",
        ["workspace_id", "enabled"],
    )
    op.create_index(
        "ix_workspaces_enabled_created_at",
        "workspaces",
        ["enabled", "created_at"],
    )
