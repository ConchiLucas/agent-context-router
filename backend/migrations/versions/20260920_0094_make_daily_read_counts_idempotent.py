"""Make daily browser read counters idempotent for retries and revisions.

Revision ID: 20260920_0094
Revises: 20260920_0093
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260920_0094"
down_revision: str | None = "20260920_0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_logs",
        sa.Column("browser_last_observed_capture_id", sa.String(128)),
    )
    op.execute(
        """UPDATE interface_forwarding_logs
        SET browser_last_observed_capture_id=browser_capture_id
        WHERE browser_capture_day IS NOT NULL"""
    )


def downgrade() -> None:
    op.drop_column("interface_forwarding_logs", "browser_last_observed_capture_id")
