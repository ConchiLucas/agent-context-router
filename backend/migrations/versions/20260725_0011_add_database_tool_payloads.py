"""Add bounded database MCP tool payload snapshots.

Revision ID: 20260725_0011
Revises: 20260724_0010
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260725_0011"
down_revision: str | None = "20260724_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_database_tool_payloads",
        sa.Column("tool_call_id", sa.BigInteger(), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "response_status",
            sa.String(length=24),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("request_bytes", sa.Integer(), nullable=True),
        sa.Column("response_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "request_truncated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "response_truncated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "capture_version",
            sa.SmallInteger(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("capture_error_code", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            """
            response_status IN (
                'pending',
                'ok',
                'error',
                'cancelled',
                'interrupted',
                'capture_failed',
                'expired'
            )
            """,
            name="ck_mcp_database_tool_payloads_status",
        ),
        sa.CheckConstraint(
            "request_bytes IS NULL OR request_bytes >= 0",
            name="ck_mcp_database_tool_payloads_request_bytes",
        ),
        sa.CheckConstraint(
            "response_bytes IS NULL OR response_bytes >= 0",
            name="ck_mcp_database_tool_payloads_response_bytes",
        ),
        sa.CheckConstraint(
            "capture_version >= 1",
            name="ck_mcp_database_tool_payloads_capture_version",
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id"],
            ["mcp_tool_calls.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tool_call_id"),
    )
    op.create_index(
        "ix_mcp_database_tool_payloads_expires_at",
        "mcp_database_tool_payloads",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_database_tool_payloads_expires_at",
        table_name="mcp_database_tool_payloads",
    )
    op.drop_table("mcp_database_tool_payloads")
