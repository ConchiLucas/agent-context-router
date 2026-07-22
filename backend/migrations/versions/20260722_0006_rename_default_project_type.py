"""Rename the default project type to company projects.

Revision ID: 20260722_0006
Revises: 20260722_0005
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0006"
down_revision: str | None = "20260722_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE document_projects SET project_type = '公司项目' WHERE project_type = '未分类'"
        )
    )
    op.alter_column(
        "document_projects",
        "project_type",
        server_default=sa.text("'公司项目'"),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE document_projects SET project_type = '未分类' WHERE project_type = '公司项目'"
        )
    )
    op.alter_column(
        "document_projects",
        "project_type",
        server_default=sa.text("'未分类'"),
    )
