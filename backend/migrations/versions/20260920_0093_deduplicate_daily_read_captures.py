"""Store one representative browser sample per read interface and local day.

Revision ID: 20260920_0093
Revises: 20260920_0092
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260920_0093"
down_revision: str | None = "20260920_0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_logs",
        sa.Column("browser_capture_day", sa.Date()),
    )
    op.add_column(
        "interface_forwarding_logs",
        sa.Column("browser_observed_count", sa.Integer()),
    )
    op.add_column(
        "interface_forwarding_logs",
        sa.Column("browser_success_count", sa.Integer()),
    )
    op.add_column(
        "interface_forwarding_logs",
        sa.Column("browser_first_seen_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "interface_forwarding_logs",
        sa.Column("browser_last_seen_at", sa.DateTime(timezone=True)),
    )
    op.create_check_constraint(
        "ck_interface_forwarding_logs_browser_counts",
        "interface_forwarding_logs",
        "browser_observed_count IS NULL OR "
        "(browser_observed_count >= 1 "
        "AND browser_success_count BETWEEN 0 AND browser_observed_count)",
    )
    op.create_index(
        "uq_interface_forwarding_logs_daily_read_capture",
        "interface_forwarding_logs",
        ["workspace_id", "environment_key", "interface_id", "browser_capture_day"],
        unique=True,
        postgresql_where=sa.text("browser_capture_day IS NOT NULL"),
    )
    op.create_index(
        "ix_browser_interface_captures_log_id",
        "browser_interface_captures",
        ["log_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_browser_interface_captures_log_id",
        table_name="browser_interface_captures",
    )
    op.drop_index(
        "uq_interface_forwarding_logs_daily_read_capture",
        table_name="interface_forwarding_logs",
    )
    op.drop_constraint(
        "ck_interface_forwarding_logs_browser_counts",
        "interface_forwarding_logs",
        type_="check",
    )
    op.drop_column("interface_forwarding_logs", "browser_last_seen_at")
    op.drop_column("interface_forwarding_logs", "browser_first_seen_at")
    op.drop_column("interface_forwarding_logs", "browser_success_count")
    op.drop_column("interface_forwarding_logs", "browser_observed_count")
    op.drop_column("interface_forwarding_logs", "browser_capture_day")
