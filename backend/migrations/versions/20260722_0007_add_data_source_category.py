"""Add independent data source categories.

Revision ID: 20260722_0007
Revises: 20260722_0006
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0007"
down_revision: str | None = "20260722_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "data_sources",
        sa.Column(
            "category",
            sa.String(length=60),
            server_default=sa.text("'本机电脑'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("data_sources", "category")
