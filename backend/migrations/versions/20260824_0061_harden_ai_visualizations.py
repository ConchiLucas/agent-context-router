"""Harden AI visualization records and task correlation.

Revision ID: 20260824_0061
Revises: 20260824_0060
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260824_0061"
down_revision: str | None = "20260824_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_data_query_records",
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("mcp_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "ai_data_query_records",
        sa.Column(
            "tool_call_id",
            sa.BigInteger(),
            sa.ForeignKey("mcp_tool_calls.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "ai_data_query_records",
        sa.Column("idempotency_key", sa.String(128), nullable=True),
    )
    op.add_column(
        "ai_data_query_records",
        sa.Column(
            "execution_status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "ai_data_query_records",
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ai_data_query_records",
        sa.Column("result_card_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ai_data_query_records",
        sa.Column("result_row_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ai_data_query_records",
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ai_data_query_records",
        sa.Column("error_summary", sa.String(1000), nullable=True),
    )
    op.add_column(
        "ai_data_query_records",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        "UPDATE ai_data_query_records SET idempotency_key = id WHERE idempotency_key IS NULL"
    )
    op.alter_column("ai_data_query_records", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_ai_data_query_records_idempotency",
        "ai_data_query_records",
        ["idempotency_key"],
    )
    op.create_check_constraint(
        "ck_ai_data_query_execution_status",
        "ai_data_query_records",
        "execution_status IN ('pending', 'succeeded', 'failed')",
    )
    op.create_check_constraint(
        "ck_ai_data_query_result_card_count",
        "ai_data_query_records",
        "result_card_count IS NULL OR result_card_count >= 0",
    )
    op.create_check_constraint(
        "ck_ai_data_query_result_row_count",
        "ai_data_query_records",
        "result_row_count IS NULL OR result_row_count >= 0",
    )
    op.create_check_constraint(
        "ck_ai_data_query_duration_ms",
        "ai_data_query_records",
        "duration_ms IS NULL OR duration_ms >= 0",
    )
    op.create_index(
        "ix_ai_data_query_records_workspace_environment_created",
        "ai_data_query_records",
        ["workspace_id", "environment", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_ai_data_query_records_task_created",
        "ai_data_query_records",
        ["task_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_data_query_records_task_created", table_name="ai_data_query_records")
    op.drop_index(
        "ix_ai_data_query_records_workspace_environment_created",
        table_name="ai_data_query_records",
    )
    op.drop_constraint(
        "ck_ai_data_query_duration_ms",
        "ai_data_query_records",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_data_query_result_row_count",
        "ai_data_query_records",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_data_query_result_card_count",
        "ai_data_query_records",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_data_query_execution_status",
        "ai_data_query_records",
        type_="check",
    )
    op.drop_constraint(
        "uq_ai_data_query_records_idempotency",
        "ai_data_query_records",
        type_="unique",
    )
    for name in (
        "updated_at",
        "error_summary",
        "duration_ms",
        "result_row_count",
        "result_card_count",
        "executed_at",
        "execution_status",
        "idempotency_key",
        "tool_call_id",
        "task_id",
    ):
        op.drop_column("ai_data_query_records", name)
