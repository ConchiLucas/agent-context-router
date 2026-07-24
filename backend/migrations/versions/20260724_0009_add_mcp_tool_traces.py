"""Add generic MCP tool-call traces.

Revision ID: 20260724_0009
Revises: 20260722_0008
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260724_0009"
down_revision: str | None = "20260722_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_tool_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_tool_call_id", sa.BigInteger(), nullable=True),
        sa.Column("server_name", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("request_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "source IN ('server','gateway','reported','legacy')",
            name="ck_mcp_tool_calls_source",
        ),
        sa.CheckConstraint(
            "status IN ('running','ok','error','cancelled')",
            name="ck_mcp_tool_calls_status",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_mcp_tool_calls_duration_ms",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["mcp_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_tool_call_id"],
            ["mcp_tool_calls.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_tool_calls_task_id_id",
        "mcp_tool_calls",
        ["task_id", "id"],
    )
    op.create_index(
        "ix_mcp_tool_calls_server_tool",
        "mcp_tool_calls",
        ["server_name", "tool_name"],
    )

    op.add_column(
        "mcp_document_read_calls",
        sa.Column("tool_call_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_mcp_document_read_calls_tool_call_id",
        "mcp_document_read_calls",
        "mcp_tool_calls",
        ["tool_call_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_mcp_document_read_calls_tool_call_id",
        "mcp_document_read_calls",
        ["tool_call_id"],
        unique=True,
        postgresql_where=sa.text("tool_call_id IS NOT NULL"),
    )

    op.add_column(
        "mcp_database_calls",
        sa.Column("tool_call_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_mcp_database_calls_tool_call_id",
        "mcp_database_calls",
        "mcp_tool_calls",
        ["tool_call_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_mcp_database_calls_tool_call_id",
        "mcp_database_calls",
        ["tool_call_id"],
        unique=True,
        postgresql_where=sa.text("tool_call_id IS NOT NULL"),
    )

    _backfill_legacy_calls()


def _backfill_legacy_calls() -> None:
    """Keep legacy read/database history visible without inventing a prepare span."""

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT
                event_type,
                event_id,
                task_id,
                status,
                duration_ms,
                created_at
            FROM (
                SELECT
                    'document_read' AS event_type,
                    read_call.id AS event_id,
                    read_call.task_id,
                    'ok' AS status,
                    NULL::integer AS duration_ms,
                    read_call.created_at
                FROM mcp_document_read_calls AS read_call
                UNION ALL
                SELECT
                    'database_call' AS event_type,
                    database_call.id AS event_id,
                    database_call.task_id,
                    database_call.status,
                    database_call.duration_ms,
                    database_call.created_at
                FROM mcp_database_calls AS database_call
            ) AS event
            ORDER BY task_id, created_at, event_type, event_id
            """
        )
    ).fetchall()

    for event_type, event_id, task_id, status, duration_ms, created_at in rows:
        tool_name = (
            "read_context_document"
            if event_type == "document_read"
            else connection.execute(
                sa.text(
                    """
                    SELECT operation
                    FROM mcp_database_calls
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            ).scalar_one()
        )
        if tool_name == "search_objects":
            tool_name = "search_database_objects"
        elif tool_name == "execute_query":
            tool_name = "execute_database_query"

        tool_call_id = connection.execute(
            sa.text(
                """
                INSERT INTO mcp_tool_calls (
                    task_id,
                    server_name,
                    tool_name,
                    source,
                    status,
                    started_at,
                    finished_at,
                    duration_ms,
                    result_summary
                )
                VALUES (
                    :task_id,
                    'context-router',
                    :tool_name,
                    'legacy',
                    :status,
                    :created_at,
                    :created_at,
                    :duration_ms,
                    jsonb_build_object('legacy', true)
                )
                RETURNING id
                """
            ),
            {
                "task_id": task_id,
                "tool_name": tool_name,
                "status": status,
                "created_at": created_at,
                "duration_ms": duration_ms,
            },
        ).scalar_one()
        table_name = (
            "mcp_document_read_calls" if event_type == "document_read" else "mcp_database_calls"
        )
        connection.execute(
            sa.text(f"UPDATE {table_name} SET tool_call_id = :tool_call_id WHERE id = :event_id"),
            {"tool_call_id": tool_call_id, "event_id": event_id},
        )


def downgrade() -> None:
    op.drop_index(
        "uq_mcp_database_calls_tool_call_id",
        table_name="mcp_database_calls",
    )
    op.drop_constraint(
        "fk_mcp_database_calls_tool_call_id",
        "mcp_database_calls",
        type_="foreignkey",
    )
    op.drop_column("mcp_database_calls", "tool_call_id")

    op.drop_index(
        "uq_mcp_document_read_calls_tool_call_id",
        table_name="mcp_document_read_calls",
    )
    op.drop_constraint(
        "fk_mcp_document_read_calls_tool_call_id",
        "mcp_document_read_calls",
        type_="foreignkey",
    )
    op.drop_column("mcp_document_read_calls", "tool_call_id")

    op.drop_index("ix_mcp_tool_calls_server_tool", table_name="mcp_tool_calls")
    op.drop_index("ix_mcp_tool_calls_task_id_id", table_name="mcp_tool_calls")
    op.drop_table("mcp_tool_calls")
