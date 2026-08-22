"""Persist interface forwarding parameter evidence.

Revision ID: 20260822_0055
Revises: 20260822_0054
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260822_0055"
down_revision: str | None = "20260822_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_request_plans",
        sa.Column(
            "parameter_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column(
        "interface_forwarding_request_plans",
        "parameter_evidence",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("interface_forwarding_request_plans", "parameter_evidence")
