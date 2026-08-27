"""Add interface business semantics, CRUD classification, and table effects.

Revision ID: 20260826_0067
Revises: 20260826_0066
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_0067"
down_revision: str | None = "20260826_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_interfaces",
        sa.Column("operation_id", sa.String(500), nullable=False, server_default=""),
    )
    op.add_column(
        "interface_forwarding_interfaces",
        sa.Column("crud_type", sa.String(16), nullable=False, server_default="unknown"),
    )
    op.create_check_constraint(
        "ck_interface_forwarding_crud_type",
        "interface_forwarding_interfaces",
        "crud_type IN ('create', 'read', 'update', 'delete', 'unknown')",
    )

    op.create_table(
        "interface_forwarding_intent_profiles",
        sa.Column(
            "interface_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_interfaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("business_entity", sa.String(240), nullable=False, server_default=""),
        sa.Column("business_action", sa.String(240), nullable=False, server_default=""),
        sa.Column("business_scenario", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "positive_examples",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "negative_examples",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source", sa.String(24), nullable=False, server_default="generated"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manual_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "source IN ('generated', 'manual')",
            name="ck_interface_forwarding_intent_source",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="ck_interface_forwarding_intent_confidence",
        ),
    )

    op.create_table(
        "interface_forwarding_table_effects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "interface_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_interfaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("database_key", sa.String(160), nullable=False, server_default=""),
        sa.Column("schema_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("table_name", sa.String(240), nullable=False),
        sa.Column("effect_type", sa.String(24), nullable=False),
        sa.Column(
            "response_contribution",
            sa.String(24),
            nullable=False,
            server_default="none",
        ),
        sa.Column("source_file", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_class", sa.String(240), nullable=False, server_default=""),
        sa.Column("source_method", sa.String(240), nullable=False, server_default=""),
        sa.Column("sql_statement_id", sa.String(500), nullable=False, server_default=""),
        sa.Column(
            "call_path",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("evidence_type", sa.String(32), nullable=False, server_default="source_code"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "effect_type IN ('select', 'insert', 'update', 'delete', 'soft_delete', 'upsert')",
            name="ck_interface_forwarding_table_effect_type",
        ),
        sa.CheckConstraint(
            "response_contribution IN "
            "('returned', 'filter_only', 'internal_only', 'unknown', 'none')",
            name="ck_interface_forwarding_response_contribution",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="ck_interface_forwarding_table_effect_confidence",
        ),
        sa.UniqueConstraint(
            "interface_id",
            "database_key",
            "schema_name",
            "table_name",
            "effect_type",
            name="uq_interface_forwarding_table_effect",
        ),
    )
    op.create_index(
        "ix_interface_forwarding_table_effects_interface",
        "interface_forwarding_table_effects",
        ["interface_id", "effect_type"],
    )
    op.create_index(
        "ix_interface_forwarding_table_effects_table",
        "interface_forwarding_table_effects",
        ["database_key", "schema_name", "table_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interface_forwarding_table_effects_table",
        table_name="interface_forwarding_table_effects",
    )
    op.drop_index(
        "ix_interface_forwarding_table_effects_interface",
        table_name="interface_forwarding_table_effects",
    )
    op.drop_table("interface_forwarding_table_effects")
    op.drop_table("interface_forwarding_intent_profiles")
    op.drop_constraint(
        "ck_interface_forwarding_crud_type",
        "interface_forwarding_interfaces",
        type_="check",
    )
    op.drop_column("interface_forwarding_interfaces", "crud_type")
    op.drop_column("interface_forwarding_interfaces", "operation_id")
