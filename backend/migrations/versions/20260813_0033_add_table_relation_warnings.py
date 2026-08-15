"""Add structured table relation analyzer warnings.

Revision ID: 20260813_0033
Revises: 20260813_0032
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0033"
down_revision: str | None = "20260813_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "table_relation_builds",
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_table_relation_builds_warning_count",
        "table_relation_builds",
        "warning_count >= 0",
    )
    op.execute(
        "UPDATE table_relation_builds SET warning_count = jsonb_array_length(warnings)"
    )
    op.create_table(
        "table_relation_warnings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("database_key", sa.String(length=64), nullable=False),
        sa.Column("generation_id", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("expression", sa.Text(), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "occurrence_count > 0",
            name="ck_table_relation_warnings_occurrence_count",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["document_projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_table_relation_warnings_active",
        "table_relation_warnings",
        ["workspace_id", "project_id", "database_key", "generation_id"],
    )
    op.create_index(
        "ix_table_relation_warnings_code",
        "table_relation_warnings",
        ["workspace_id", "code"],
    )


def downgrade() -> None:
    op.drop_index("ix_table_relation_warnings_code", table_name="table_relation_warnings")
    op.drop_index("ix_table_relation_warnings_active", table_name="table_relation_warnings")
    op.drop_table("table_relation_warnings")
    op.drop_constraint(
        "ck_table_relation_builds_warning_count",
        "table_relation_builds",
        type_="check",
    )
    op.drop_column("table_relation_builds", "warning_count")
