"""remove document chunks

Revision ID: 20260627_0003
Revises: 20260627_0002
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260627_0003"
down_revision: str | None = "20260627_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _drop_fk_constraints_for_column(table_name: str, column_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_foreign_keys(table_name):
        if column_name in constraint.get("constrained_columns", []) and constraint.get("name"):
            op.drop_constraint(constraint["name"], table_name, type_="foreignkey")


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if any(index["name"] == index_name for index in inspector.get_indexes(table_name)):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    tables = _table_names()

    if "retrieval_hits" in tables and _has_column("retrieval_hits", "chunk_id"):
        _drop_fk_constraints_for_column("retrieval_hits", "chunk_id")
        _drop_index_if_exists("retrieval_hits", op.f("ix_retrieval_hits_chunk_id"))
        op.drop_column("retrieval_hits", "chunk_id")

    if "document_chunks" in tables:
        op.drop_table("document_chunks")


def downgrade() -> None:
    tables = _table_names()

    if "document_chunks" not in tables:
        op.create_table(
            "document_chunks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=240), nullable=False),
            sa.Column("heading_path", sa.JSON(), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("token_estimate", sa.Integer(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_document_chunks_document_id"),
            "document_chunks",
            ["document_id"],
            unique=False,
        )

    if "retrieval_hits" in tables and not _has_column("retrieval_hits", "chunk_id"):
        op.add_column(
            "retrieval_hits",
            sa.Column("chunk_id", sa.String(length=36), nullable=True),
        )
        op.create_foreign_key(
            "retrieval_hits_chunk_id_fkey",
            "retrieval_hits",
            "document_chunks",
            ["chunk_id"],
            ["id"],
        )
        op.create_index(
            op.f("ix_retrieval_hits_chunk_id"),
            "retrieval_hits",
            ["chunk_id"],
            unique=False,
        )
