"""Deduplicate browser network captures across offline retries.

Revision ID: 20260909_0087
Revises: 20260906_0086
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260909_0087"
down_revision: str | None = "20260906_0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_logs",
        sa.Column("browser_capture_id", sa.String(128)),
    )
    op.create_index(
        "uq_interface_forwarding_logs_browser_capture",
        "interface_forwarding_logs",
        ["workspace_id", "browser_capture_id"],
        unique=True,
        postgresql_where=sa.text("browser_capture_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_interface_forwarding_logs_browser_capture",
        table_name="interface_forwarding_logs",
    )
    op.drop_column("interface_forwarding_logs", "browser_capture_id")
