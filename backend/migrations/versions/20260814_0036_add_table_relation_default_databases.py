"""Add workspace defaults for table relation databases.

Revision ID: 20260814_0036
Revises: 20260813_0035
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260814_0036"
down_revision: str | None = "20260813_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_table_relation_configs",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_workspace_table_relation_configs_revision",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_table(
        "workspace_table_relation_default_databases",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("project_database_id", sa.String(length=32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["document_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["project_database_id"], ["project_databases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("workspace_id", "project_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "project_database_id",
            name="uq_workspace_table_relation_default_database",
        ),
    )
    op.create_index(
        "ix_workspace_table_relation_defaults_database",
        "workspace_table_relation_default_databases",
        ["project_database_id"],
    )
    op.add_column(
        "table_relation_builds",
        sa.Column("config_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_table_relation_builds_config_revision",
        "table_relation_builds",
        "config_revision >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_table_relation_builds_config_revision",
        "table_relation_builds",
        type_="check",
    )
    op.drop_column("table_relation_builds", "config_revision")
    op.drop_index(
        "ix_workspace_table_relation_defaults_database",
        table_name="workspace_table_relation_default_databases",
    )
    op.drop_table("workspace_table_relation_default_databases")
    op.drop_table("workspace_table_relation_configs")
