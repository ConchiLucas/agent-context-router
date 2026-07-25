"""Add a stable project reference to MCP tasks.

Revision ID: 20260724_0010
Revises: 20260724_0009
Create Date: 2026-07-24
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision: str = "20260724_0010"
down_revision: str | None = "20260724_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # This is an immutable task snapshot, not a live relational link. Keeping it free
    # of a foreign key preserves trace identity after project deletion and also lets
    # degraded startup create tasks for an in-memory default project.
    op.add_column(
        "mcp_tasks",
        sa.Column("project_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_mcp_tasks_project_id_id",
        "mcp_tasks",
        ["project_id", "id"],
    )
    _backfill_project_ids()


def _backfill_project_ids() -> None:
    connection = op.get_bind()
    projects = connection.execute(
        sa.text("SELECT id, agents_path FROM document_projects")
    ).fetchall()
    for project_id, agents_path in projects:
        normalized_path = str(Path(str(agents_path)).expanduser())
        project_key = hashlib.sha256(normalized_path.encode()).hexdigest()
        connection.execute(
            sa.text(
                """
                UPDATE mcp_tasks
                SET project_id = :project_id
                WHERE project_id IS NULL
                  AND project_key = :project_key
                """
            ),
            {
                "project_id": project_id,
                "project_key": project_key,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_mcp_tasks_project_id_id", table_name="mcp_tasks")
    op.drop_column("mcp_tasks", "project_id")
