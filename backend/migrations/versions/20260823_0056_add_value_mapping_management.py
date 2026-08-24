"""Add business value mapping management.

Revision ID: 20260823_0056
Revises: 20260822_0055
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260823_0056"
down_revision: str | None = "20260822_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interface_value_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column(
            "resolver_type",
            sa.String(32),
            nullable=False,
            server_default="database_column",
        ),
        sa.Column("database_alias", sa.String(64), nullable=False),
        sa.Column("schema_name", sa.String(128)),
        sa.Column("table_name", sa.String(128), nullable=False),
        sa.Column("value_column", sa.String(128), nullable=False),
        sa.Column(
            "search_columns",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "display_columns",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "filter_conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("status IN ('draft','published')", name="ck_value_mapping_status"),
        sa.CheckConstraint(
            "resolver_type='database_column'",
            name="ck_value_mapping_resolver_type",
        ),
        sa.CheckConstraint("version >= 1", name="ck_value_mapping_version"),
    )
    op.create_index(
        "ix_interface_value_mappings_workspace_status",
        "interface_value_mappings",
        ["workspace_id", "status", "updated_at"],
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_interface_value_mappings_workspace_key_lower
           ON interface_value_mappings (workspace_id, lower(value_key))"""
    )

    op.create_table(
        "interface_value_mapping_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mapping_id",
            sa.String(36),
            sa.ForeignKey("interface_value_mappings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.String(160), nullable=False),
    )
    op.create_index(
        "ix_interface_value_mapping_aliases_mapping",
        "interface_value_mapping_aliases",
        ["mapping_id"],
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_interface_value_mapping_aliases_workspace_alias_lower
           ON interface_value_mapping_aliases (workspace_id, lower(alias))"""
    )

    op.create_table(
        "interface_value_mapping_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "mapping_id",
            sa.String(36),
            sa.ForeignKey("interface_value_mappings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "interface_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_interfaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("location", sa.String(16), nullable=False),
        sa.Column("parameter_path", sa.String(240), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint(
            "location IN ('path','query','body')",
            name="ck_value_mapping_binding_location",
        ),
        sa.UniqueConstraint(
            "interface_id",
            "location",
            "parameter_path",
            name="uq_interface_value_mapping_bindings_parameter",
        ),
    )
    op.create_index(
        "ix_interface_value_mapping_bindings_mapping",
        "interface_value_mapping_bindings",
        ["mapping_id"],
    )


def downgrade() -> None:
    op.drop_table("interface_value_mapping_bindings")
    op.drop_index(
        "uq_interface_value_mapping_aliases_workspace_alias_lower",
        table_name="interface_value_mapping_aliases",
    )
    op.drop_table("interface_value_mapping_aliases")
    op.drop_index(
        "uq_interface_value_mappings_workspace_key_lower",
        table_name="interface_value_mappings",
    )
    op.drop_table("interface_value_mappings")
