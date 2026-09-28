"""Add generic caller correlation context to MCP tool traces."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20260915_0090"
down_revision = "20260914_0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mcp_tool_calls", sa.Column("trace_context", JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_mcp_tool_calls_trace_context_object",
        "mcp_tool_calls",
        "trace_context IS NULL OR jsonb_typeof(trace_context) = 'object'",
    )
    op.execute(
        """
        CREATE INDEX ix_mcp_tool_calls_trace_run_item
        ON mcp_tool_calls (
            task_id,
            (trace_context ->> 'run_id'),
            (trace_context ->> 'item_id'),
            id
        )
        WHERE trace_context IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_tool_calls_trace_run_item", table_name="mcp_tool_calls")
    op.drop_constraint(
        "ck_mcp_tool_calls_trace_context_object",
        "mcp_tool_calls",
        type_="check",
    )
    op.drop_column("mcp_tool_calls", "trace_context")
