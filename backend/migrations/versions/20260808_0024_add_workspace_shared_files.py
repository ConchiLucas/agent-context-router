"""Store the canonical workspace documents and deployment files.

Revision ID: 20260808_0024
Revises: 20260802_0023
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260808_0024"
down_revision: str | None = "20260802_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_shared_files",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("workspace_id", sa.String(32), nullable=False),
        sa.Column("file_type", sa.String(16), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("executable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
            "file_type IN ('document','deploy')",
            name="ck_workspace_shared_files_type",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "file_type",
            "relative_path",
            name="uq_workspace_shared_files_owner_path",
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_shared_files")
