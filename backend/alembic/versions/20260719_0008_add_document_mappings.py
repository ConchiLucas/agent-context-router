"""add document mappings

Revision ID: 20260719_0008
Revises: 20260703_0007
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260719_0008"
down_revision: str | None = "20260703_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    project_columns = _column_names("projects")
    if "docs_path" not in project_columns:
        op.add_column("projects", sa.Column("docs_path", sa.String(length=1024)))
    if "last_synced_at" not in project_columns:
        op.add_column("projects", sa.Column("last_synced_at", sa.DateTime(timezone=True)))
    if "last_sync_status" not in project_columns:
        op.add_column(
            "projects",
            sa.Column(
                "last_sync_status",
                sa.String(length=40),
                server_default="never",
                nullable=False,
            ),
        )
    if "last_sync_summary" not in project_columns:
        op.add_column(
            "projects",
            sa.Column(
                "last_sync_summary",
                sa.JSON(),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
        )

    docs_path_index = op.f("ix_projects_docs_path")
    if not _has_index("projects", docs_path_index):
        op.create_index(docs_path_index, "projects", ["docs_path"], unique=True)

    document_columns = _column_names("documents")
    if "is_reachable" not in document_columns:
        op.add_column(
            "documents",
            sa.Column(
                "is_reachable",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
        )
    if "graph_depth" not in document_columns:
        op.add_column("documents", sa.Column("graph_depth", sa.Integer()))

    reachable_index = op.f("ix_documents_is_reachable")
    if not _has_index("documents", reachable_index):
        op.create_index(reachable_index, "documents", ["is_reachable"], unique=False)
    depth_index = op.f("ix_documents_graph_depth")
    if not _has_index("documents", depth_index):
        op.create_index(depth_index, "documents", ["graph_depth"], unique=False)


def downgrade() -> None:
    depth_index = op.f("ix_documents_graph_depth")
    if _has_index("documents", depth_index):
        op.drop_index(depth_index, table_name="documents")
    reachable_index = op.f("ix_documents_is_reachable")
    if _has_index("documents", reachable_index):
        op.drop_index(reachable_index, table_name="documents")

    document_columns = _column_names("documents")
    if "graph_depth" in document_columns:
        op.drop_column("documents", "graph_depth")
    if "is_reachable" in document_columns:
        op.drop_column("documents", "is_reachable")

    docs_path_index = op.f("ix_projects_docs_path")
    if _has_index("projects", docs_path_index):
        op.drop_index(docs_path_index, table_name="projects")

    project_columns = _column_names("projects")
    for column_name in (
        "last_sync_summary",
        "last_sync_status",
        "last_synced_at",
        "docs_path",
    ):
        if column_name in project_columns:
            op.drop_column("projects", column_name)
