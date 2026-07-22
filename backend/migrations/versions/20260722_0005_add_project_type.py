"""Add project type for project tabs.

Revision ID: 20260722_0005
Revises: 20260722_0004
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0005"
down_revision: str | None = "20260722_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_projects",
        sa.Column(
            "project_type",
            sa.String(length=60),
            server_default=sa.text("'未分类'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("document_projects", "project_type")
