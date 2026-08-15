"""Add project-scoped SQL whitelist for table relation scans.

Revision ID: 20260815_0037
Revises: 20260814_0036
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260815_0037"
down_revision: str | None = "20260814_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "table_relation_sql_whitelist",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "length(source_path) BETWEEN 1 AND 1000",
            name="ck_table_relation_sql_whitelist_path_length",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["document_projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("workspace_id", "project_id", "source_path"),
    )
    op.create_index(
        "ix_table_relation_sql_whitelist_project",
        "table_relation_sql_whitelist",
        ["workspace_id", "project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_table_relation_sql_whitelist_project",
        table_name="table_relation_sql_whitelist",
    )
    op.drop_table("table_relation_sql_whitelist")
