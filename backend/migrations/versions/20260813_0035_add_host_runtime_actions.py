"""Add allowlisted host runtime actions.

Revision ID: 20260813_0035
Revises: 20260812_0030
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0035"
down_revision: str | None = "20260812_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _constraint_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {item["name"] for item in inspector.get_check_constraints(table) if item.get("name")}


def upgrade() -> None:
    columns = _column_names("runtime_operations")
    if "environment" not in columns:
        op.add_column(
            "runtime_operations",
            sa.Column(
                "environment",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'local'"),
            ),
        )
    if "action" not in columns:
        op.add_column(
            "runtime_operations",
            sa.Column("action", sa.String(length=64), nullable=True),
        )

    operation_constraints = _constraint_names("runtime_operations")
    if "ck_runtime_operations_environment" not in operation_constraints:
        op.create_check_constraint(
            "ck_runtime_operations_environment",
            "runtime_operations",
            "environment IN ('local','test','uat')",
        )
    op.create_check_constraint(
        "ck_runtime_operations_action",
        "runtime_operations",
        "(kind = 'host_action' AND action IN "
        "('pzh.ensure-host-runtime','pzh.status-host-runtime')) OR "
        "(kind <> 'host_action' AND action IS NULL)",
    )
    if "ck_runtime_operations_kind" in operation_constraints:
        op.drop_constraint("ck_runtime_operations_kind", "runtime_operations", type_="check")
    op.create_check_constraint(
        "ck_runtime_operations_kind",
        "runtime_operations",
        "kind IN ('apply_changes','start_workspace','project_update','host_action')",
    )
    if "ck_runtime_operation_steps_mode" in _constraint_names("runtime_operation_steps"):
        op.drop_constraint(
            "ck_runtime_operation_steps_mode", "runtime_operation_steps", type_="check"
        )
    op.create_check_constraint(
        "ck_runtime_operation_steps_mode",
        "runtime_operation_steps",
        "mode IN ('start','fast','full','host')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM runtime_operations WHERE kind = 'host_action'")
    op.drop_constraint("ck_runtime_operation_steps_mode", "runtime_operation_steps", type_="check")
    op.create_check_constraint(
        "ck_runtime_operation_steps_mode",
        "runtime_operation_steps",
        "mode IN ('start','fast','full')",
    )
    op.drop_constraint("ck_runtime_operations_kind", "runtime_operations", type_="check")
    op.create_check_constraint(
        "ck_runtime_operations_kind",
        "runtime_operations",
        "kind IN ('apply_changes','start_workspace','project_update')",
    )
    op.drop_constraint("ck_runtime_operations_action", "runtime_operations", type_="check")
    op.drop_constraint("ck_runtime_operations_environment", "runtime_operations", type_="check")
    op.drop_column("runtime_operations", "action")
    op.drop_column("runtime_operations", "environment")
