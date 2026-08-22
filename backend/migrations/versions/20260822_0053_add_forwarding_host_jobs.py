"""Add short-lived Host Runner jobs for interface forwarding.

Revision ID: 20260822_0053
Revises: 20260822_0052
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260822_0053"
down_revision: str | None = "20260822_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interface_forwarding_host_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_request_plans.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("runner_id", sa.String(64)),
        sa.Column("lease_token_hash", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("status_code", sa.Integer()),
        sa.Column("response_body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "response_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("response_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_type", sa.String(120)),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("leased_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'leased', 'completed', 'failed')",
            name="ck_interface_forwarding_host_job_status",
        ),
        sa.CheckConstraint(
            "response_bytes >= 0 AND duration_ms >= 0",
            name="ck_interface_forwarding_host_job_sizes",
        ),
    )
    op.create_index(
        "ix_interface_forwarding_host_jobs_status_created",
        "interface_forwarding_host_jobs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("interface_forwarding_host_jobs")
