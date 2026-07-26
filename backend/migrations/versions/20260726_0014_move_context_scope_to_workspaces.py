"""Move MCP context ownership from projects to workspaces.

Revision ID: 20260726_0014
Revises: 20260726_0013
Create Date: 2026-07-26
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision: str = "20260726_0014"
down_revision: str | None = "20260726_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_project_kind_and_remove_project_enabled()
    _move_database_aliases_to_workspace_scope()
    _add_workspace_task_snapshots()


def _add_project_kind_and_remove_project_enabled() -> None:
    op.add_column(
        "document_projects",
        sa.Column(
            "project_kind",
            sa.String(length=16),
            server_default=sa.text("'backend'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_document_projects_project_kind",
        "document_projects",
        "project_kind IN ('frontend','backend')",
    )
    op.drop_index(
        "ix_document_projects_workspace_enabled_created_at",
        table_name="document_projects",
    )
    op.drop_index(
        "ix_document_projects_enabled_created_at",
        table_name="document_projects",
    )
    op.create_index(
        "ix_document_projects_workspace_kind_created_at",
        "document_projects",
        ["workspace_id", "project_kind", "created_at"],
    )
    op.drop_column("document_projects", "enabled")


def _move_database_aliases_to_workspace_scope() -> None:
    op.add_column(
        "project_databases",
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE project_databases AS link
            SET workspace_id = project.workspace_id
            FROM document_projects AS project
            WHERE project.id = link.project_id
            """
        )
    )
    missing_workspace = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM project_databases
            WHERE workspace_id IS NULL
            """
        )
    ).scalar_one()
    if int(missing_workspace) > 0:
        raise RuntimeError("存在无法归属到工作空间的项目数据库关联")

    conflicts = connection.execute(
        sa.text(
            """
            SELECT workspace_id, lower(mcp_alias), COUNT(*)
            FROM project_databases
            WHERE mcp_alias IS NOT NULL
            GROUP BY workspace_id, lower(mcp_alias)
            HAVING COUNT(*) > 1
            ORDER BY workspace_id, lower(mcp_alias)
            """
        )
    ).fetchall()
    if conflicts:
        workspace_id, mcp_alias, _ = conflicts[0]
        raise RuntimeError(
            f"工作空间内存在重复 MCP 数据库别名：workspace_id={workspace_id}, mcp_alias={mcp_alias}"
        )

    op.alter_column("project_databases", "workspace_id", nullable=False)
    op.create_foreign_key(
        "fk_project_databases_workspace_id",
        "project_databases",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index(
        "uq_project_databases_project_mcp_alias",
        table_name="project_databases",
    )
    op.create_index(
        "uq_project_databases_workspace_mcp_alias",
        "project_databases",
        ["workspace_id", sa.text("lower(mcp_alias)")],
        unique=True,
        postgresql_where=sa.text("mcp_alias IS NOT NULL"),
    )
    op.create_index(
        "ix_project_databases_workspace",
        "project_databases",
        ["workspace_id", "enabled"],
    )


def _add_workspace_task_snapshots() -> None:
    op.add_column(
        "mcp_tasks",
        sa.Column(
            "scope",
            sa.String(length=16),
            server_default=sa.text("'project'"),
            nullable=False,
        ),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column("workspace_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column("workspace_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column("active_project_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column("active_project_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "mcp_tasks",
        sa.Column("active_project_kind", sa.String(length=16), nullable=True),
    )

    connection = op.get_bind()
    projects = connection.execute(
        sa.text(
            """
            SELECT
                project.id,
                project.agents_path,
                project.name,
                project.project_kind,
                workspace.id,
                workspace.name,
                workspace.root_path
            FROM document_projects AS project
            JOIN workspaces AS workspace ON workspace.id = project.workspace_id
            ORDER BY project.created_at, project.id
            """
        )
    ).fetchall()
    for (
        project_id,
        agents_path,
        project_name,
        project_kind,
        workspace_id,
        workspace_name,
        workspace_root_path,
    ) in projects:
        workspace_key = _stable_path_key(str(workspace_root_path))
        parameters = {
            "workspace_id": workspace_id,
            "workspace_key": workspace_key,
            "workspace_name": workspace_name,
            "active_project_id": project_id,
            "active_project_name": project_name,
            "active_project_kind": project_kind,
            "project_id": project_id,
            "project_key": _stable_path_key(str(agents_path)),
        }
        connection.execute(
            sa.text(
                """
                UPDATE mcp_tasks
                SET workspace_id = :workspace_id,
                    workspace_key = :workspace_key,
                    workspace_name = :workspace_name,
                    active_project_id = :active_project_id,
                    active_project_name = :active_project_name,
                    active_project_kind = :active_project_kind
                WHERE project_id = :project_id
                   OR (
                        project_id IS NULL
                        AND workspace_id IS NULL
                        AND project_key = :project_key
                   )
                """
            ),
            parameters,
        )

    op.create_check_constraint(
        "ck_mcp_tasks_scope",
        "mcp_tasks",
        "scope IN ('project','workspace')",
    )
    op.create_check_constraint(
        "ck_mcp_tasks_workspace_snapshot",
        "mcp_tasks",
        """
        scope = 'project'
        OR (
            workspace_id IS NOT NULL
            AND workspace_key IS NOT NULL
            AND workspace_name IS NOT NULL
        )
        """,
    )
    op.create_check_constraint(
        "ck_mcp_tasks_active_project_kind",
        "mcp_tasks",
        """
        active_project_kind IS NULL
        OR active_project_kind IN ('frontend','backend')
        """,
    )
    op.create_index(
        "ix_mcp_tasks_workspace_id_id",
        "mcp_tasks",
        ["workspace_id", "id"],
    )


def _stable_path_key(path: str) -> str:
    normalized_path = str(Path(path).expanduser())
    return hashlib.sha256(normalized_path.encode()).hexdigest()


def downgrade() -> None:
    op.drop_index("ix_mcp_tasks_workspace_id_id", table_name="mcp_tasks")
    op.drop_constraint(
        "ck_mcp_tasks_active_project_kind",
        "mcp_tasks",
        type_="check",
    )
    op.drop_constraint(
        "ck_mcp_tasks_workspace_snapshot",
        "mcp_tasks",
        type_="check",
    )
    op.drop_constraint("ck_mcp_tasks_scope", "mcp_tasks", type_="check")
    op.drop_column("mcp_tasks", "active_project_kind")
    op.drop_column("mcp_tasks", "active_project_name")
    op.drop_column("mcp_tasks", "active_project_id")
    op.drop_column("mcp_tasks", "workspace_name")
    op.drop_column("mcp_tasks", "workspace_key")
    op.drop_column("mcp_tasks", "workspace_id")
    op.drop_column("mcp_tasks", "scope")

    op.drop_index(
        "ix_project_databases_workspace",
        table_name="project_databases",
    )
    op.drop_index(
        "uq_project_databases_workspace_mcp_alias",
        table_name="project_databases",
    )
    op.create_index(
        "uq_project_databases_project_mcp_alias",
        "project_databases",
        ["project_id", sa.text("lower(mcp_alias)")],
        unique=True,
        postgresql_where=sa.text("mcp_alias IS NOT NULL"),
    )
    op.drop_constraint(
        "fk_project_databases_workspace_id",
        "project_databases",
        type_="foreignkey",
    )
    op.drop_column("project_databases", "workspace_id")

    op.add_column(
        "document_projects",
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.drop_index(
        "ix_document_projects_workspace_kind_created_at",
        table_name="document_projects",
    )
    op.create_index(
        "ix_document_projects_workspace_enabled_created_at",
        "document_projects",
        ["workspace_id", "enabled", "created_at"],
    )
    op.create_index(
        "ix_document_projects_enabled_created_at",
        "document_projects",
        ["enabled", "created_at"],
    )
    op.drop_constraint(
        "ck_document_projects_project_kind",
        "document_projects",
        type_="check",
    )
    op.drop_column("document_projects", "project_kind")
