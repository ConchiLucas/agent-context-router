"""Create project runtime configuration files.

Revision ID: 20260728_0017
Revises: 20260727_0016
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260728_0017"
down_revision: str | None = "20260727_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_runtime_files",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "executable",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
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
        sa.CheckConstraint(
            "mode IN ('fast', 'full')",
            name="ck_project_runtime_files_mode",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["document_projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "mode",
            "relative_path",
            name="uq_project_runtime_files_project_mode_path",
        ),
    )
    op.create_index(
        "ix_project_runtime_files_project_mode_order",
        "project_runtime_files",
        ["project_id", "mode", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_runtime_files_project_mode_order",
        table_name="project_runtime_files",
    )
    op.drop_table("project_runtime_files")
