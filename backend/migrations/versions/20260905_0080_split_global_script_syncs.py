"""Allow typed document and deploy sync actions for managed scripts.

Revision ID: 20260905_0080
Revises: 20260905_0079
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260905_0080"
down_revision: str | None = "20260905_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_managed_scripts_action", "managed_scripts", type_="check")
    op.create_check_constraint(
        "ck_managed_scripts_action",
        "managed_scripts",
        "action_key IN ('native_stack_start', 'host_runtime_ensure', "
        "'restore_shared_files', 'sync_scripts', 'sync_documents', 'sync_deploy')",
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM managed_scripts "
        "WHERE action_key IN ('sync_documents', 'sync_deploy')"
    )
    op.drop_constraint("ck_managed_scripts_action", "managed_scripts", type_="check")
    op.create_check_constraint(
        "ck_managed_scripts_action",
        "managed_scripts",
        "action_key IN ('native_stack_start', 'host_runtime_ensure', "
        "'restore_shared_files', 'sync_scripts')",
    )
