"""Store the forwarding identity role in request logs.

Revision ID: 20260822_0050
Revises: 20260822_0049
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0050"
down_revision: str | None = "20260822_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_logs",
        sa.Column("identity_role", sa.String(160), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("interface_forwarding_logs", "identity_role")
