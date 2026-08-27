"""Add workspace interface qualifier terms and per-interface qualifiers.

Revision ID: 20260827_0069
Revises: 20260827_0068
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260827_0069"
down_revision: str | None = "20260827_0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_intent_profiles",
        sa.Column(
            "qualifiers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "interface_forwarding_intent_profiles",
        sa.Column("qualifier_source", sa.String(24), nullable=False, server_default="generated"),
    )
    op.add_column(
        "interface_forwarding_intent_profiles",
        sa.Column("qualifier_confidence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_interface_forwarding_qualifier_source",
        "interface_forwarding_intent_profiles",
        "qualifier_source IN ('generated', 'manual')",
    )
    op.create_check_constraint(
        "ck_interface_forwarding_qualifier_confidence",
        "interface_forwarding_intent_profiles",
        "qualifier_confidence BETWEEN 0 AND 100",
    )

    op.create_table(
        "interface_forwarding_qualifier_terms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dimension_key", sa.String(80), nullable=False),
        sa.Column("dimension_label", sa.String(120), nullable=False),
        sa.Column("value_key", sa.String(120), nullable=False),
        sa.Column("value_label", sa.String(160), nullable=False),
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
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
        sa.UniqueConstraint(
            "workspace_id",
            "dimension_key",
            "value_key",
            name="uq_interface_forwarding_qualifier_term",
        ),
    )
    op.create_index(
        "ix_interface_forwarding_qualifier_terms_workspace",
        "interface_forwarding_qualifier_terms",
        ["workspace_id", "dimension_key", "value_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interface_forwarding_qualifier_terms_workspace",
        table_name="interface_forwarding_qualifier_terms",
    )
    op.drop_table("interface_forwarding_qualifier_terms")
    op.drop_constraint(
        "ck_interface_forwarding_qualifier_confidence",
        "interface_forwarding_intent_profiles",
        type_="check",
    )
    op.drop_constraint(
        "ck_interface_forwarding_qualifier_source",
        "interface_forwarding_intent_profiles",
        type_="check",
    )
    op.drop_column("interface_forwarding_intent_profiles", "qualifier_confidence")
    op.drop_column("interface_forwarding_intent_profiles", "qualifier_source")
    op.drop_column("interface_forwarding_intent_profiles", "qualifiers")
