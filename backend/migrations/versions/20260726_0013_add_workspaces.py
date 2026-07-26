"""Add workspace ownership for document projects.

Revision ID: 20260726_0013
Revises: 20260725_0012
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

import sqlalchemy as sa

from alembic import op

revision: str = "20260726_0013"
down_revision: str | None = "20260725_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "workspace_type",
            sa.String(length=60),
            server_default=sa.text("'公司项目'"),
            nullable=False,
        ),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("root_path", name="uq_workspaces_root_path"),
    )
    op.create_index(
        "ix_workspaces_enabled_created_at",
        "workspaces",
        ["enabled", "created_at"],
    )

    op.add_column(
        "document_projects",
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "document_projects",
        sa.Column("relative_path", sa.Text(), nullable=True),
    )

    connection = op.get_bind()
    projects = list(
        connection.execute(
            sa.text(
                """
                SELECT id, name, project_type, agents_path, created_at, updated_at
                FROM document_projects
                ORDER BY created_at, id
                """
            )
        ).mappings()
    )
    for project in projects:
        root_path = str(PurePosixPath(str(project["agents_path"])).parent)
        connection.execute(
            sa.text(
                """
                INSERT INTO workspaces
                    (id, name, workspace_type, root_path, enabled, created_at, updated_at)
                VALUES
                    (:id, :name, :workspace_type, :root_path, true, :created_at, :updated_at)
                """
            ),
            {
                "id": project["id"],
                "name": project["name"],
                "workspace_type": project["project_type"],
                "root_path": root_path,
                "created_at": project["created_at"],
                "updated_at": project["updated_at"],
            },
        )
        connection.execute(
            sa.text(
                """
                UPDATE document_projects
                SET workspace_id = :workspace_id, relative_path = '.'
                WHERE id = :project_id
                """
            ),
            {
                "workspace_id": project["id"],
                "project_id": project["id"],
            },
        )

    op.alter_column("document_projects", "workspace_id", nullable=False)
    op.alter_column("document_projects", "relative_path", nullable=False)
    op.create_foreign_key(
        "fk_document_projects_workspace_id",
        "document_projects",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_document_projects_workspace_relative_path",
        "document_projects",
        ["workspace_id", "relative_path"],
    )
    op.create_index(
        "ix_document_projects_workspace_enabled_created_at",
        "document_projects",
        ["workspace_id", "enabled", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_projects_workspace_enabled_created_at",
        table_name="document_projects",
    )
    op.drop_constraint(
        "uq_document_projects_workspace_relative_path",
        "document_projects",
        type_="unique",
    )
    op.drop_constraint(
        "fk_document_projects_workspace_id",
        "document_projects",
        type_="foreignkey",
    )
    op.drop_column("document_projects", "relative_path")
    op.drop_column("document_projects", "workspace_id")
    op.drop_index("ix_workspaces_enabled_created_at", table_name="workspaces")
    op.drop_table("workspaces")
