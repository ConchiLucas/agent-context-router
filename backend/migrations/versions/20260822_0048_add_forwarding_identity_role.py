"""Add a display role to interface forwarding identities.

Revision ID: 20260822_0048
Revises: 20260822_0047
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0048"
down_revision: str | None = "20260822_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_identities",
        sa.Column("role_name", sa.String(160), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("interface_forwarding_identities", "role_name")
