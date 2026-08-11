"""Allow UI project updates to run through the host Runtime Runner.

Revision ID: 20260810_0027
Revises: 20260809_0026
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0027"
down_revision: str | None = "20260809_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("runtime_operations", "task_id", existing_type=sa.BigInteger(), nullable=True)
    op.drop_constraint("ck_runtime_operations_kind", "runtime_operations", type_="check")
    op.create_check_constraint(
        "ck_runtime_operations_kind",
        "runtime_operations",
        "kind IN ('apply_changes','start_workspace','project_update')",
    )
    op.drop_constraint("ck_runtime_operations_trigger", "runtime_operations", type_="check")
    op.create_check_constraint(
        "ck_runtime_operations_trigger",
        "runtime_operations",
        "trigger IN ('mcp','api','ui')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM runtime_operations WHERE task_id IS NULL")
    op.drop_constraint("ck_runtime_operations_trigger", "runtime_operations", type_="check")
    op.create_check_constraint(
        "ck_runtime_operations_trigger",
        "runtime_operations",
        "trigger IN ('mcp','api')",
    )
    op.drop_constraint("ck_runtime_operations_kind", "runtime_operations", type_="check")
    op.create_check_constraint(
        "ck_runtime_operations_kind",
        "runtime_operations",
        "kind IN ('apply_changes','start_workspace')",
    )
    op.alter_column("runtime_operations", "task_id", existing_type=sa.BigInteger(), nullable=False)
