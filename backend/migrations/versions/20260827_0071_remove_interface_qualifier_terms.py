"""Archive workspace interface qualifier terms outside the runtime schema.

Revision ID: 20260827_0071
Revises: 20260827_0070
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260827_0071"
down_revision: str | None = "20260827_0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table(
        "interface_forwarding_qualifier_terms",
        "archived_interface_forwarding_qualifier_terms",
    )
    op.alter_column(
        "interface_forwarding_intent_profiles",
        "qualifiers",
        new_column_name="archived_qualifiers",
    )
    op.alter_column(
        "interface_forwarding_intent_profiles",
        "qualifier_source",
        new_column_name="archived_qualifier_source",
    )
    op.alter_column(
        "interface_forwarding_intent_profiles",
        "qualifier_confidence",
        new_column_name="archived_qualifier_confidence",
    )


def downgrade() -> None:
    op.alter_column(
        "interface_forwarding_intent_profiles",
        "archived_qualifiers",
        new_column_name="qualifiers",
    )
    op.alter_column(
        "interface_forwarding_intent_profiles",
        "archived_qualifier_source",
        new_column_name="qualifier_source",
    )
    op.alter_column(
        "interface_forwarding_intent_profiles",
        "archived_qualifier_confidence",
        new_column_name="qualifier_confidence",
    )
    op.rename_table(
        "archived_interface_forwarding_qualifier_terms",
        "interface_forwarding_qualifier_terms",
    )
