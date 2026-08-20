"""Add table-level write sites for table relations.

Revision ID: 20260818_0037
Revises: 20260817_0036
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_0037"
down_revision: str | None = "20260817_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Where this table is actually persisted. This is not the same question as
    # the relation code sites, which hang on an edge and say how a parent key is
    # assigned. A ``batchInsert`` of cargo is one write of ``highway_cargo`` even
    # when it fills four foreign keys, and aggregating those edge sites would
    # list the same method four times — or, worse, list a child-table insert
    # against the parent table the edge also names.
    op.create_table(
        "workspace_table_write_sites",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("generation_id", sa.String(length=32), nullable=False),
        sa.Column("database_key", sa.String(length=64), nullable=False),
        sa.Column("schema_name", sa.String(length=255), nullable=False),
        sa.Column("table_name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("method_name", sa.String(length=255), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('batch_insert','save_or_update','insert','update')",
            name="ck_workspace_table_write_sites_kind",
        ),
        sa.CheckConstraint(
            "file_path <> '' AND left(file_path, 1) <> '/' AND method_name <> ''",
            name="ck_workspace_table_write_sites_location",
        ),
        sa.CheckConstraint(
            "length(snippet) BETWEEN 1 AND 2000",
            name="ck_workspace_table_write_sites_snippet",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_workspace_table_write_sites_position",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["workspace_table_relation_generations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id", "database_key", "schema_name", "table_name"],
            [
                "workspace_table_relation_tables.generation_id",
                "workspace_table_relation_tables.database_key",
                "workspace_table_relation_tables.schema_name",
                "workspace_table_relation_tables.table_name",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_id",
            "database_key",
            "schema_name",
            "table_name",
            "position",
            name="uq_workspace_table_write_sites_order",
        ),
        sa.UniqueConstraint(
            "generation_id",
            "database_key",
            "schema_name",
            "table_name",
            "file_path",
            "method_name",
            name="uq_workspace_table_write_sites_call",
        ),
    )
    op.create_index(
        "ix_workspace_table_write_sites_table",
        "workspace_table_write_sites",
        ["generation_id", "database_key", "schema_name", "table_name", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_table_write_sites_table",
        table_name="workspace_table_write_sites",
    )
    op.drop_table("workspace_table_write_sites")
