"""Archive rolled-back progressive routing and interface-quality features.

Revision ID: 20260827_0072
Revises: 20260827_0071
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0072"
down_revision: str | None = "20260827_0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_tasks",
        sa.Column("archived_routing_intent_type", sa.String(32), nullable=True),
    )
    op.execute(
        """UPDATE mcp_tasks
           SET archived_routing_intent_type=intent_type,
               intent_type=CASE
                 WHEN intent_type='interface_discovery' THEN 'task_execute'
                 WHEN intent_type='code_change' THEN 'task_execute'
                 ELSE intent_type
               END
           WHERE intent_type IN ('interface_discovery', 'code_change')"""
    )
    op.drop_constraint("ck_mcp_tasks_intent_type", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_intent_type",
        "mcp_tasks",
        "intent_type IN ('interface_execute', 'data_query', 'task_execute', "
        "'bug_investigate', 'bug_fix')",
    )

    op.alter_column(
        "mcp_tasks",
        "workflow_stage",
        new_column_name="archived_workflow_stage",
    )
    op.alter_column(
        "mcp_tasks",
        "capability_revision",
        new_column_name="archived_capability_revision",
    )
    op.rename_table(
        "mcp_task_capability_events",
        "archived_mcp_task_capability_events",
    )

    op.alter_column(
        "interface_forwarding_request_plans",
        "intent_match_score",
        new_column_name="archived_intent_match_score",
    )
    op.alter_column(
        "interface_forwarding_request_plans",
        "intent_match_evidence",
        new_column_name="archived_intent_match_evidence",
    )
    op.alter_column(
        "interface_forwarding_request_plans",
        "search_event_id",
        new_column_name="archived_search_event_id",
    )
    op.alter_column(
        "interface_forwarding_logs",
        "intent_match_score",
        new_column_name="archived_intent_match_score",
    )
    op.alter_column(
        "interface_forwarding_logs",
        "intent_match_evidence",
        new_column_name="archived_intent_match_evidence",
    )
    op.alter_column(
        "interface_forwarding_logs",
        "validation_status",
        new_column_name="archived_validation_status",
    )
    op.alter_column(
        "interface_forwarding_logs",
        "validation_result",
        new_column_name="archived_validation_result",
    )
    op.rename_table(
        "interface_forwarding_response_rules",
        "archived_interface_forwarding_response_rules",
    )
    op.rename_table(
        "interface_forwarding_search_events",
        "archived_interface_forwarding_search_events",
    )


def downgrade() -> None:
    op.rename_table(
        "archived_interface_forwarding_search_events",
        "interface_forwarding_search_events",
    )
    op.rename_table(
        "archived_interface_forwarding_response_rules",
        "interface_forwarding_response_rules",
    )
    op.alter_column(
        "interface_forwarding_logs",
        "archived_validation_result",
        new_column_name="validation_result",
    )
    op.alter_column(
        "interface_forwarding_logs",
        "archived_validation_status",
        new_column_name="validation_status",
    )
    op.alter_column(
        "interface_forwarding_logs",
        "archived_intent_match_evidence",
        new_column_name="intent_match_evidence",
    )
    op.alter_column(
        "interface_forwarding_logs",
        "archived_intent_match_score",
        new_column_name="intent_match_score",
    )
    op.alter_column(
        "interface_forwarding_request_plans",
        "archived_search_event_id",
        new_column_name="search_event_id",
    )
    op.alter_column(
        "interface_forwarding_request_plans",
        "archived_intent_match_evidence",
        new_column_name="intent_match_evidence",
    )
    op.alter_column(
        "interface_forwarding_request_plans",
        "archived_intent_match_score",
        new_column_name="intent_match_score",
    )

    op.rename_table(
        "archived_mcp_task_capability_events",
        "mcp_task_capability_events",
    )
    op.alter_column(
        "mcp_tasks",
        "archived_capability_revision",
        new_column_name="capability_revision",
    )
    op.alter_column(
        "mcp_tasks",
        "archived_workflow_stage",
        new_column_name="workflow_stage",
    )

    op.drop_constraint("ck_mcp_tasks_intent_type", "mcp_tasks", type_="check")
    op.execute(
        """UPDATE mcp_tasks
           SET intent_type=archived_routing_intent_type
           WHERE archived_routing_intent_type IS NOT NULL"""
    )
    op.create_check_constraint(
        "ck_mcp_tasks_intent_type",
        "mcp_tasks",
        "intent_type IN ('interface_discovery', 'interface_execute', 'data_query', "
        "'task_execute', 'bug_investigate', 'bug_fix', 'code_change')",
    )
    op.drop_column("mcp_tasks", "archived_routing_intent_type")
