"""Separate project source roots from document entry paths.

Revision ID: 20260727_0016
Revises: 20260726_0015
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

import sqlalchemy as sa

from alembic import op

revision: str = "20260727_0016"
down_revision: str | None = "20260726_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_projects",
        sa.Column("document_relative_path", sa.Text(), nullable=True),
    )

    connection = op.get_bind()
    projects = connection.execute(
        sa.text(
            """
            SELECT project.id, project.agents_path, workspace.root_path
            FROM document_projects AS project
            JOIN workspaces AS workspace ON workspace.id = project.workspace_id
            ORDER BY project.created_at, project.id
            """
        )
    ).fetchall()
    for project_id, agents_path, workspace_root_path in projects:
        try:
            document_relative_path = PurePosixPath(str(agents_path)).relative_to(
                PurePosixPath(str(workspace_root_path))
            )
        except ValueError as exc:
            raise RuntimeError(
                f"项目 {project_id} 的 AGENTS.md 不在所属工作空间内，无法迁移"
            ) from exc
        if document_relative_path.name != "AGENTS.md":
            raise RuntimeError(f"项目 {project_id} 的入口文件不是 AGENTS.md，无法迁移")
        connection.execute(
            sa.text(
                """
                UPDATE document_projects
                SET document_relative_path = :document_relative_path
                WHERE id = :project_id
                """
            ),
            {
                "project_id": project_id,
                "document_relative_path": document_relative_path.as_posix(),
            },
        )

    op.alter_column(
        "document_projects",
        "document_relative_path",
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_document_projects_workspace_document_relative_path",
        "document_projects",
        ["workspace_id", "document_relative_path"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_document_projects_workspace_document_relative_path",
        "document_projects",
        type_="unique",
    )
    op.drop_column("document_projects", "document_relative_path")
