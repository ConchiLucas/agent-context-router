"""Add the PostgreSQL document search index.

Revision ID: 20260725_0012
Revises: 20260725_0011
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260725_0012"
down_revision: str | None = "20260725_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pg_trgm can be shared by other application features. The downgrade therefore
    # deliberately leaves the extension installed.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "document_search_index_states",
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("index_version", sa.String(length=64), nullable=False),
        sa.Column("index_format_version", sa.SmallInteger(), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "index_version ~ '^[0-9a-f]{64}$'",
            name="ck_document_search_states_index_version",
        ),
        sa.CheckConstraint(
            "index_format_version >= 1",
            name="ck_document_search_states_format_version",
        ),
        sa.CheckConstraint(
            "document_count >= 0",
            name="ck_document_search_states_document_count",
        ),
        sa.CheckConstraint(
            "chunk_count >= 0",
            name="ck_document_search_states_chunk_count",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["document_projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id"),
    )

    op.create_table(
        "document_search_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("index_version", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column(
            "section_path",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column("section_ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "section_readable",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "index_version ~ '^[0-9a-f]{64}$'",
            name="ck_document_search_chunks_index_version",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_document_search_chunks_content_hash",
        ),
        sa.CheckConstraint(
            "section_ordinal >= 0",
            name="ck_document_search_chunks_section_ordinal",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_document_search_chunks_chunk_index",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["document_projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "document_id",
            "section_ordinal",
            "chunk_index",
            name="uq_document_search_chunks_position",
        ),
    )
    op.create_index(
        "ix_document_search_chunks_search_vector",
        "document_search_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_document_search_chunks_search_text_trgm",
        "document_search_chunks",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_document_search_chunks_project_version_document",
        "document_search_chunks",
        ["project_id", "index_version", "document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_search_chunks_project_version_document",
        table_name="document_search_chunks",
    )
    op.drop_index(
        "ix_document_search_chunks_search_text_trgm",
        table_name="document_search_chunks",
        postgresql_using="gin",
    )
    op.drop_index(
        "ix_document_search_chunks_search_vector",
        table_name="document_search_chunks",
        postgresql_using="gin",
    )
    op.drop_table("document_search_chunks")
    op.drop_table("document_search_index_states")
