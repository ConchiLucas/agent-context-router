"""Add the Workspace document search index.

Revision ID: 20260726_0015
Revises: 20260726_0014
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260726_0015"
down_revision: str | None = "20260726_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_document_search_index_states",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
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
            name="ck_workspace_document_search_states_version",
        ),
        sa.CheckConstraint(
            "index_format_version >= 1",
            name="ck_workspace_document_search_states_format",
        ),
        sa.CheckConstraint(
            "document_count >= 0",
            name="ck_workspace_document_search_states_documents",
        ),
        sa.CheckConstraint(
            "chunk_count >= 0",
            name="ck_workspace_document_search_states_chunks",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
    )

    op.create_table(
        "workspace_document_search_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
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
            name="ck_workspace_document_search_chunks_version",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_workspace_document_search_chunks_hash",
        ),
        sa.CheckConstraint(
            "section_ordinal >= 0",
            name="ck_workspace_document_search_chunks_section",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_workspace_document_search_chunks_index",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "document_id",
            "section_ordinal",
            "chunk_index",
            name="uq_workspace_document_search_chunks_position",
        ),
    )
    op.create_index(
        "ix_workspace_document_search_chunks_vector",
        "workspace_document_search_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_workspace_document_search_chunks_trgm",
        "workspace_document_search_chunks",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_workspace_document_search_chunks_scope",
        "workspace_document_search_chunks",
        ["workspace_id", "index_version", "document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_document_search_chunks_scope",
        table_name="workspace_document_search_chunks",
    )
    op.drop_index(
        "ix_workspace_document_search_chunks_trgm",
        table_name="workspace_document_search_chunks",
        postgresql_using="gin",
    )
    op.drop_index(
        "ix_workspace_document_search_chunks_vector",
        table_name="workspace_document_search_chunks",
        postgresql_using="gin",
    )
    op.drop_table("workspace_document_search_chunks")
    op.drop_table("workspace_document_search_index_states")
