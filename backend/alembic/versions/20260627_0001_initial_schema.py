"""initial schema

Revision ID: 20260627_0001
Revises:
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260627_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("root_path", sa.String(length=1024), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_projects_slug"), "projects", ["slug"], unique=False)

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=240), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("doc_type", sa.String(length=80), nullable=False),
        sa.Column("area", sa.String(length=120), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_area"), "documents", ["area"], unique=False)
    op.create_index(op.f("ix_documents_doc_type"), "documents", ["doc_type"], unique=False)
    op.create_index(op.f("ix_documents_project_id"), "documents", ["project_id"], unique=False)
    op.create_index(op.f("ix_documents_status"), "documents", ["status"], unique=False)

    op.create_table(
        "traces",
        sa.Column("id", sa.String(length=120), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("cwd", sa.String(length=1024), nullable=True),
        sa.Column("agent_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_traces_project_id"), "traces", ["project_id"], unique=False)

    op.create_table(
        "trace_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trace_id"], ["traces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_trace_events_event_type"),
        "trace_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(op.f("ix_trace_events_trace_id"), "trace_events", ["trace_id"], unique=False)

    op.create_table(
        "retrieval_hits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=120), nullable=False),
        sa.Column("document_id", sa.String(length=240), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("was_returned", sa.Boolean(), nullable=False),
        sa.Column("feedback", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["trace_id"], ["traces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_retrieval_hits_document_id"),
        "retrieval_hits",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_retrieval_hits_feedback"),
        "retrieval_hits",
        ["feedback"],
        unique=False,
    )
    op.create_index(
        op.f("ix_retrieval_hits_trace_id"),
        "retrieval_hits",
        ["trace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_retrieval_hits_trace_id"), table_name="retrieval_hits")
    op.drop_index(op.f("ix_retrieval_hits_feedback"), table_name="retrieval_hits")
    op.drop_index(op.f("ix_retrieval_hits_document_id"), table_name="retrieval_hits")
    op.drop_table("retrieval_hits")
    op.drop_index(op.f("ix_trace_events_trace_id"), table_name="trace_events")
    op.drop_index(op.f("ix_trace_events_event_type"), table_name="trace_events")
    op.drop_table("trace_events")
    op.drop_index(op.f("ix_traces_project_id"), table_name="traces")
    op.drop_table("traces")
    op.drop_index(op.f("ix_documents_status"), table_name="documents")
    op.drop_index(op.f("ix_documents_project_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_doc_type"), table_name="documents")
    op.drop_index(op.f("ix_documents_area"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_projects_slug"), table_name="projects")
    op.drop_table("projects")
