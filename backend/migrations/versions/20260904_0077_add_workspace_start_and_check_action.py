"""Add the Panzhihua start-and-check host action.

Revision ID: 20260904_0077
Revises: 20260903_0076
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260904_0077"
down_revision: str | None = "20260903_0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_runtime_operations_action",
        "runtime_operations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_runtime_operations_action",
        "runtime_operations",
        "(kind = 'host_action' AND action IN "
        "('pzh.ensure-host-runtime','pzh.status-host-runtime','pzh.start-and-check')) OR "
        "(kind <> 'host_action' AND action IS NULL)",
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM runtime_operations "
        "WHERE kind = 'host_action' AND action = 'pzh.start-and-check'"
    )
    op.drop_constraint(
        "ck_runtime_operations_action",
        "runtime_operations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_runtime_operations_action",
        "runtime_operations",
        "(kind = 'host_action' AND action IN "
        "('pzh.ensure-host-runtime','pzh.status-host-runtime')) OR "
        "(kind <> 'host_action' AND action IS NULL)",
    )
