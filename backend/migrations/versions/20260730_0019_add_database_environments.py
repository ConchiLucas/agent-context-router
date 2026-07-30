"""Add workspace database environment mappings.

Revision ID: 20260730_0019
Revises: 20260728_0018
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260730_0019"
down_revision: str | None = "20260728_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_database_environment_configs",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("active_environment", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
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
            "active_environment IN ('test','uat')",
            name="ck_workspace_database_environment_configs_active",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_workspace_database_environment_configs_revision",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
    )

    op.create_table(
        "project_database_environment_mappings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("logical_name", sa.String(length=120), nullable=False),
        sa.Column("mcp_alias", sa.String(length=64), nullable=False),
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
            "mcp_alias ~ '^[a-z][a-z0-9_-]{0,63}$'",
            name="ck_project_database_environment_mappings_alias",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["document_projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_project_database_environment_mappings_workspace_alias",
        "project_database_environment_mappings",
        ["workspace_id", sa.text("lower(mcp_alias)")],
        unique=True,
    )
    op.create_index(
        "ix_project_database_environment_mappings_workspace_project",
        "project_database_environment_mappings",
        ["workspace_id", "project_id"],
    )

    op.create_table(
        "project_database_environment_targets",
        sa.Column("mapping_id", sa.String(length=32), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("project_database_id", sa.String(length=32), nullable=False),
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
            "environment IN ('test','uat')",
            name="ck_project_database_environment_targets_environment",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_id"],
            ["project_database_environment_mappings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_database_id"],
            ["project_databases.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("mapping_id", "environment"),
        sa.UniqueConstraint(
            "project_database_id",
            "environment",
            name="uq_project_database_environment_targets_link_environment",
        ),
    )
    op.create_index(
        "ix_project_database_environment_targets_environment",
        "project_database_environment_targets",
        ["environment", "mapping_id"],
    )

    op.add_column(
        "mcp_tasks",
        sa.Column("database_environment", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column("database_environment_revision", sa.Integer(), nullable=True),
    )
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


def downgrade() -> None:
    op.drop_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        type_="check",
    )
    op.drop_column("mcp_tasks", "database_environment_revision")
    op.drop_column("mcp_tasks", "database_environment")

    op.drop_index(
        "ix_project_database_environment_targets_environment",
        table_name="project_database_environment_targets",
    )
    op.drop_table("project_database_environment_targets")
    op.drop_index(
        "ix_project_database_environment_mappings_workspace_project",
        table_name="project_database_environment_mappings",
    )
    op.drop_index(
        "uq_project_database_environment_mappings_workspace_alias",
        table_name="project_database_environment_mappings",
    )
    op.drop_table("project_database_environment_mappings")
    op.drop_table("workspace_database_environment_configs")
