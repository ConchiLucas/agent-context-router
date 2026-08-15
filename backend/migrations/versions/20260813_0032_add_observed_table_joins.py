"""Add SQL observed table joins.

Revision ID: 20260813_0032
Revises: 20260812_0031
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_0032"
down_revision: str | None = "20260812_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "table_relation_builds",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("database_key", sa.String(length=64), nullable=False),
        sa.Column("generation_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("sql_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("statement_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('building','ready','failed')",
            name="ck_table_relation_builds_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(warnings) = 'array'",
            name="ck_table_relation_builds_warnings",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["document_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "project_id", "database_key"),
    )
    op.create_table(
        "table_join_relations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("database_key", sa.String(length=64), nullable=False),
        sa.Column("table_a_schema", sa.String(length=255), nullable=False),
        sa.Column("table_a_name", sa.String(length=255), nullable=False),
        sa.Column("table_b_schema", sa.String(length=255), nullable=False),
        sa.Column("table_b_name", sa.String(length=255), nullable=False),
        sa.Column("relation_kind", sa.String(length=32), nullable=False),
        sa.Column("directed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generation_id", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "relation_kind = 'observed_join'",
            name="ck_table_join_relations_kind",
        ),
        sa.CheckConstraint("directed = FALSE", name="ck_table_join_relations_undirected"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["document_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "database_key",
            "table_a_schema",
            "table_a_name",
            "table_b_schema",
            "table_b_name",
            name="uq_table_join_relation_identity",
        ),
    )
    op.create_index(
        "ix_table_join_relations_a",
        "table_join_relations",
        ["workspace_id", "database_key", "table_a_schema", "table_a_name"],
    )
    op.create_index(
        "ix_table_join_relations_b",
        "table_join_relations",
        ["workspace_id", "database_key", "table_b_schema", "table_b_name"],
    )
    op.create_table(
        "table_join_column_pairs",
        sa.Column("relation_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("column_a_name", sa.String(length=255), nullable=False),
        sa.Column("column_b_name", sa.String(length=255), nullable=False),
        sa.CheckConstraint("position > 0", name="ck_table_join_column_pairs_position"),
        sa.ForeignKeyConstraint(["relation_id"], ["table_join_relations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("relation_id", "position"),
    )
    op.create_table(
        "table_join_evidences",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("relation_id", sa.String(length=64), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("join_expression", sa.Text(), nullable=False),
        sa.Column("sql_statement", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "source_kind = 'sql_file'",
            name="ck_table_join_evidences_source_kind",
        ),
        sa.ForeignKeyConstraint(["relation_id"], ["table_join_relations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("table_join_evidences")
    op.drop_table("table_join_column_pairs")
    op.drop_index("ix_table_join_relations_b", table_name="table_join_relations")
    op.drop_index("ix_table_join_relations_a", table_name="table_join_relations")
    op.drop_table("table_join_relations")
    op.drop_table("table_relation_builds")
