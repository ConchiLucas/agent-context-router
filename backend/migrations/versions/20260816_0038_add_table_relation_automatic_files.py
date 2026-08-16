"""Persist table-relation automatic whitelist file assignments.

Revision ID: 20260816_0038
Revises: 20260815_0037
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_0038"
down_revision: str | None = "20260815_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "table_relation_builds",
        sa.Column("automatic_file_count", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_table_relation_builds_automatic_file_count",
        "table_relation_builds",
        "automatic_file_count IS NULL OR automatic_file_count >= 0",
    )
    op.create_table(
        "table_relation_automatic_files",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("database_key", sa.String(length=64), nullable=False),
        sa.Column("generation_id", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("rule_code", sa.String(length=64), nullable=False),
        sa.Column("statement_bytes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(source_path) BETWEEN 1 AND 1000",
            name="ck_table_relation_automatic_files_path_length",
        ),
        sa.CheckConstraint(
            "statement_bytes >= 0",
            name="ck_table_relation_automatic_files_statement_bytes",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["document_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_table_relation_automatic_files_active",
        "table_relation_automatic_files",
        ["workspace_id", "project_id", "database_key", "generation_id"],
    )
    op.create_index(
        "ix_table_relation_automatic_files_rule",
        "table_relation_automatic_files",
        ["workspace_id", "rule_code"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_table_relation_automatic_files_rule",
        table_name="table_relation_automatic_files",
    )
    op.drop_index(
        "ix_table_relation_automatic_files_active",
        table_name="table_relation_automatic_files",
    )
    op.drop_table("table_relation_automatic_files")
    op.drop_constraint(
        "ck_table_relation_builds_automatic_file_count",
        "table_relation_builds",
        type_="check",
    )
    op.drop_column("table_relation_builds", "automatic_file_count")
