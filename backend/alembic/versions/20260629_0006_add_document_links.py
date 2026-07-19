"""add document links

Revision ID: 20260629_0006
Revises: 20260627_0005
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260629_0006"
down_revision: str | None = "20260627_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("document_links"):
        op.create_table(
            "document_links",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_document_id", sa.String(length=240), nullable=False),
            sa.Column("target_document_id", sa.String(length=240), nullable=True),
            sa.Column("target_path", sa.String(length=1024), nullable=False),
            sa.Column("label", sa.String(length=500), nullable=False),
            sa.Column("relation_type", sa.String(length=80), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["source_document_id"],
                ["documents.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["target_document_id"],
                ["documents.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    for column_name in ("source_document_id", "target_document_id", "relation_type"):
        index_name = op.f(f"ix_document_links_{column_name}")
        if not _has_index("document_links", index_name):
            op.create_index(index_name, "document_links", [column_name], unique=False)


def downgrade() -> None:
    if _has_table("document_links"):
        for column_name in ("relation_type", "target_document_id", "source_document_id"):
            index_name = op.f(f"ix_document_links_{column_name}")
            if _has_index("document_links", index_name):
                op.drop_index(index_name, table_name="document_links")
        op.drop_table("document_links")
