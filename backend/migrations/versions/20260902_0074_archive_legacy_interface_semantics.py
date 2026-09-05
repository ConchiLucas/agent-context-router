"""Archive legacy interface semantics outside the active runtime schema.

Revision ID: 20260902_0074
Revises: 20260902_0073
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260902_0074"
down_revision: str | None = "20260902_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_intent_profiles",
        sa.Column(
            "legacy_interface_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE interface_forwarding_intent_profiles AS profile
        SET legacy_interface_fields = jsonb_build_object(
            'crud_type', interface.crud_type,
            'controller_description', interface.controller_description
        )
        FROM interface_forwarding_interfaces AS interface
        WHERE interface.id = profile.interface_id
        """
    )
    op.rename_table(
        "interface_forwarding_intent_profiles",
        "archived_interface_forwarding_intent_profiles",
    )
    op.drop_constraint(
        "ck_interface_forwarding_crud_type",
        "interface_forwarding_interfaces",
        type_="check",
    )
    op.drop_column("interface_forwarding_interfaces", "crud_type")
    op.drop_column("interface_forwarding_interfaces", "controller_description")


def downgrade() -> None:
    op.add_column(
        "interface_forwarding_interfaces",
        sa.Column(
            "controller_description",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "interface_forwarding_interfaces",
        sa.Column(
            "crud_type",
            sa.String(16),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.execute(
        """
        UPDATE interface_forwarding_interfaces AS interface
        SET crud_type = COALESCE(
                archive.legacy_interface_fields->>'crud_type',
                'unknown'
            ),
            controller_description = COALESCE(
                archive.legacy_interface_fields->>'controller_description',
                ''
            )
        FROM archived_interface_forwarding_intent_profiles AS archive
        WHERE archive.interface_id = interface.id
        """
    )
    op.create_check_constraint(
        "ck_interface_forwarding_crud_type",
        "interface_forwarding_interfaces",
        "crud_type IN ('create', 'read', 'update', 'delete', 'unknown')",
    )
    op.rename_table(
        "archived_interface_forwarding_intent_profiles",
        "interface_forwarding_intent_profiles",
    )
    op.drop_column(
        "interface_forwarding_intent_profiles",
        "legacy_interface_fields",
    )
