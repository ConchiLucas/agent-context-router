"""Add table-level update sites for table relations.

Revision ID: 20260818_0038
Revises: 20260818_0037
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_0038"
down_revision: str | None = "20260818_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Insert sites and update sites are independent lists hung on the table,
    # not two filters over one persist table. The same method can both insert
    # and later update (``saveOrUpdate`` then ``update`` in ``createAndPublish``),
    # and a unique constraint on (table, file, method) would have forced one of
    # those calls off the page.
    op.create_table(
        "workspace_table_update_sites",
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
            "kind IN ('batch_update','save_or_update','update')",
            name="ck_workspace_table_update_sites_kind",
        ),
        sa.CheckConstraint(
            "file_path <> '' AND left(file_path, 1) <> '/' AND method_name <> ''",
            name="ck_workspace_table_update_sites_location",
        ),
        sa.CheckConstraint(
            "length(snippet) BETWEEN 1 AND 2000",
            name="ck_workspace_table_update_sites_snippet",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_workspace_table_update_sites_position",
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
            name="uq_workspace_table_update_sites_order",
        ),
        sa.UniqueConstraint(
            "generation_id",
            "database_key",
            "schema_name",
            "table_name",
            "file_path",
            "method_name",
            name="uq_workspace_table_update_sites_call",
        ),
    )
    op.create_index(
        "ix_workspace_table_update_sites_table",
        "workspace_table_update_sites",
        ["generation_id", "database_key", "schema_name", "table_name", "position"],
    )
    # ``update`` now belongs on the update list. Leaving it in the insert-site
    # check would let a seed put an update under the insert button.
    op.drop_constraint(
        "ck_workspace_table_write_sites_kind",
        "workspace_table_write_sites",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_table_write_sites_kind",
        "workspace_table_write_sites",
        "kind IN ('batch_insert','save_or_update','insert')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_workspace_table_write_sites_kind",
        "workspace_table_write_sites",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_table_write_sites_kind",
        "workspace_table_write_sites",
        "kind IN ('batch_insert','save_or_update','insert','update')",
    )
    op.drop_index(
        "ix_workspace_table_update_sites_table",
        table_name="workspace_table_update_sites",
    )
    op.drop_table("workspace_table_update_sites")
