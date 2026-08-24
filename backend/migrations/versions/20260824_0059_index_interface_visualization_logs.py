"""Index interface request logs for the visualization list.

Revision ID: 20260824_0059
Revises: 20260824_0058
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260824_0059"
down_revision: str | None = "20260824_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_interface_forwarding_logs_workspace_created",
        "interface_forwarding_logs",
        ["workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interface_forwarding_logs_workspace_created",
        table_name="interface_forwarding_logs",
    )
