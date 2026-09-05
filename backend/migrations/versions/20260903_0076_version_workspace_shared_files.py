"""Version workspace shared files and include workspace scripts.

Revision ID: 20260903_0076
Revises: 20260902_0075
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_0076"
down_revision: str | None = "20260902_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_shared_file_sets",
        sa.Column("workspace_id", sa.String(32), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "revision"),
    )
    op.create_index(
        "uq_workspace_shared_file_sets_current",
        "workspace_shared_file_sets",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.add_column(
        "workspace_shared_files",
        sa.Column("revision", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "workspace_shared_files",
        sa.Column("content_sha256", sa.String(64), nullable=True),
    )
    op.drop_constraint(
        "uq_workspace_shared_files_owner_path",
        "workspace_shared_files",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_workspace_shared_files_revision_path",
        "workspace_shared_files",
        ["workspace_id", "revision", "file_type", "relative_path"],
    )
    op.drop_constraint(
        "ck_workspace_shared_files_type",
        "workspace_shared_files",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_shared_files_type",
        "workspace_shared_files",
        "file_type IN ('document','deploy','script','host_runtime')",
    )
    op.execute(
        """INSERT INTO workspace_shared_file_sets
           (workspace_id, revision, digest, is_current)
           SELECT DISTINCT workspace_id, 1, NULL, true
           FROM workspace_shared_files"""
    )
    op.create_foreign_key(
        "fk_workspace_shared_files_set",
        "workspace_shared_files",
        "workspace_shared_file_sets",
        ["workspace_id", "revision"],
        ["workspace_id", "revision"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.execute(
        """DELETE FROM workspace_shared_files f
           USING workspace_shared_file_sets s
           WHERE f.workspace_id = s.workspace_id
             AND f.revision = s.revision
             AND NOT s.is_current"""
    )
    op.drop_constraint(
        "fk_workspace_shared_files_set",
        "workspace_shared_files",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_workspace_shared_files_revision_path",
        "workspace_shared_files",
        type_="unique",
    )
    op.execute("UPDATE workspace_shared_files SET revision = 1")
    op.create_unique_constraint(
        "uq_workspace_shared_files_owner_path",
        "workspace_shared_files",
        ["workspace_id", "file_type", "relative_path"],
    )
    op.drop_constraint(
        "ck_workspace_shared_files_type",
        "workspace_shared_files",
        type_="check",
    )
    op.execute("DELETE FROM workspace_shared_files WHERE file_type IN ('script','host_runtime')")
    op.create_check_constraint(
        "ck_workspace_shared_files_type",
        "workspace_shared_files",
        "file_type IN ('document','deploy')",
    )
    op.drop_column("workspace_shared_files", "content_sha256")
    op.drop_column("workspace_shared_files", "revision")
    op.drop_index("uq_workspace_shared_file_sets_current", table_name="workspace_shared_file_sets")
    op.drop_table("workspace_shared_file_sets")
