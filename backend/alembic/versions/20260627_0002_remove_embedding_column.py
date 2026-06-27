"""remove embedding column

Revision ID: 20260627_0002
Revises: 20260627_0001
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260627_0002"
down_revision: str | None = "20260627_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_column("document_chunks", "embedding"):
        op.drop_column("document_chunks", "embedding")


def downgrade() -> None:
    if _has_table("document_chunks") and not _has_column("document_chunks", "embedding"):
        op.add_column("document_chunks", sa.Column("embedding", sa.JSON(), nullable=True))
