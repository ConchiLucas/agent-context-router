"""Add interface discovery intent and execution validation evidence.

Revision ID: 20260827_0068
Revises: 20260826_0067
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260827_0068"
down_revision: str | None = "20260826_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_mcp_tasks_intent_type", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_intent_type",
        "mcp_tasks",
        "intent_type IN ('interface_discovery', 'interface_execute', 'data_query', "
        "'task_execute', 'bug_investigate', 'bug_fix', 'code_change')",
    )

    op.add_column(
        "interface_forwarding_request_plans",
        sa.Column("intent_match_score", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "interface_forwarding_request_plans",
        sa.Column(
            "intent_match_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.add_column(
        "interface_forwarding_logs",
        sa.Column("intent_match_score", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "interface_forwarding_logs",
        sa.Column(
            "intent_match_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "interface_forwarding_logs",
        sa.Column(
            "validation_status",
            sa.String(24),
            nullable=False,
            server_default="not_configured",
        ),
    )
    op.add_column(
        "interface_forwarding_logs",
        sa.Column(
            "validation_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_interface_forwarding_logs_validation_status",
        "interface_forwarding_logs",
        "validation_status IN ('passed', 'warning', 'failed', 'not_configured')",
    )

    op.create_table(
        "interface_forwarding_response_rules",
        sa.Column(
            "interface_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_interfaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "success_code_paths",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "success_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "message_paths",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "data_paths",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "required_result_paths",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source", sa.String(24), nullable=False, server_default="generated"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "source IN ('generated', 'manual')",
            name="ck_interface_forwarding_response_rule_source",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="ck_interface_forwarding_response_rule_confidence",
        ),
    )


def downgrade() -> None:
    op.drop_table("interface_forwarding_response_rules")
    op.drop_constraint(
        "ck_interface_forwarding_logs_validation_status",
        "interface_forwarding_logs",
        type_="check",
    )
    op.drop_column("interface_forwarding_logs", "validation_result")
    op.drop_column("interface_forwarding_logs", "validation_status")
    op.drop_column("interface_forwarding_logs", "intent_match_evidence")
    op.drop_column("interface_forwarding_logs", "intent_match_score")
    op.drop_column("interface_forwarding_request_plans", "intent_match_evidence")
    op.drop_column("interface_forwarding_request_plans", "intent_match_score")
    op.drop_constraint("ck_mcp_tasks_intent_type", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_intent_type",
        "mcp_tasks",
        "intent_type IN ('interface_execute', 'data_query', 'task_execute', "
        "'bug_investigate', 'bug_fix', 'code_change')",
    )
