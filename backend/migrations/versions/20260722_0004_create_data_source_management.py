"""Create data source management tables.

Revision ID: 20260722_0004
Revises: 20260721_0003
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0004"
down_revision: str | None = "20260721_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("connection_config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("config_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "engine IN ('mysql','mariadb','postgresql','sqlserver','sqlite','oracle','clickhouse')",
            name="ck_data_sources_engine",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_data_sources_name"),
    )
    op.create_table(
        "data_source_databases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("data_source_id", sa.String(length=32), nullable=False),
        sa.Column("remote_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column(
            "namespace_type", sa.String(length=16), server_default="database", nullable=False
        ),
        sa.Column("available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("system_database", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "namespace_type IN ('database','schema','file')",
            name="ck_data_source_databases_namespace_type",
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "data_source_id", "remote_name", name="uq_data_source_databases_source_name"
        ),
    )
    op.create_index(
        "ix_data_source_databases_source",
        "data_source_databases",
        ["data_source_id", "remote_name"],
    )
    op.create_table(
        "project_databases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("database_id", sa.String(length=32), nullable=False),
        sa.Column("alias", sa.String(length=120), server_default="", nullable=False),
        sa.Column("purpose", sa.Text(), server_default="", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("readonly", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("allowed_schemas", sa.JSON(), nullable=False),
        sa.Column("max_rows", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("max_result_bytes", sa.Integer(), server_default="2000000", nullable=False),
        sa.Column("query_timeout_ms", sa.Integer(), server_default="15000", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("max_rows > 0", name="ck_project_databases_max_rows"),
        sa.CheckConstraint("max_result_bytes > 0", name="ck_project_databases_max_result_bytes"),
        sa.CheckConstraint("query_timeout_ms > 0", name="ck_project_databases_query_timeout_ms"),
        sa.ForeignKeyConstraint(["project_id"], ["document_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["database_id"], ["data_source_databases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "database_id", name="uq_project_databases_project_database"
        ),
    )
    op.create_index("ix_project_databases_project", "project_databases", ["project_id", "enabled"])
    op.create_index("ix_project_databases_database", "project_databases", ["database_id"])


def downgrade() -> None:
    op.drop_index("ix_project_databases_database", table_name="project_databases")
    op.drop_index("ix_project_databases_project", table_name="project_databases")
    op.drop_table("project_databases")
    op.drop_index("ix_data_source_databases_source", table_name="data_source_databases")
    op.drop_table("data_source_databases")
    op.drop_table("data_sources")
