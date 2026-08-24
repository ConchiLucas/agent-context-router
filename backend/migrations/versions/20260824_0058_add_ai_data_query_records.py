"""Add AI data visualization query records.

Revision ID: 20260824_0058
Revises: 20260824_0057
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260824_0058"
down_revision: str | None = "20260824_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_data_query_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("database_key", sa.String(64), nullable=False),
        sa.Column("schema_name", sa.String(255), nullable=False),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("keyword", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("length(trim(source)) > 0", name="ck_ai_data_query_source"),
        sa.CheckConstraint("length(trim(environment)) > 0", name="ck_ai_data_query_environment"),
        sa.CheckConstraint("length(trim(database_key)) > 0", name="ck_ai_data_query_database"),
        sa.CheckConstraint("length(trim(table_name)) > 0", name="ck_ai_data_query_table"),
        sa.CheckConstraint("length(trim(keyword)) > 0", name="ck_ai_data_query_keyword"),
    )
    op.create_index(
        "ix_ai_data_query_records_created_at",
        "ai_data_query_records",
        [sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_ai_data_query_records_workspace_created_at",
        "ai_data_query_records",
        ["workspace_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_data_query_records_workspace_created_at",
        table_name="ai_data_query_records",
    )
    op.drop_index(
        "ix_ai_data_query_records_created_at",
        table_name="ai_data_query_records",
    )
    op.drop_table("ai_data_query_records")
