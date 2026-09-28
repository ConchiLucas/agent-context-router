"""Allow Personal Utils Hub ensure action for project-start scripts.

Revision ID: 20260906_0083
Revises: 20260906_0082
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260906_0083"
down_revision: str | None = "20260906_0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_managed_scripts_action", "managed_scripts", type_="check")
    op.create_check_constraint(
        "ck_managed_scripts_action",
        "managed_scripts",
        "action_key IN ('native_stack_start', 'host_runtime_ensure', "
        "'shared_config_ensure', 'personal_utils_ensure', 'restore_shared_files', "
        "'sync_scripts', 'sync_documents', 'sync_deploy')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM managed_scripts WHERE action_key = 'personal_utils_ensure'")
    op.drop_constraint("ck_managed_scripts_action", "managed_scripts", type_="check")
    op.create_check_constraint(
        "ck_managed_scripts_action",
        "managed_scripts",
        "action_key IN ('native_stack_start', 'host_runtime_ensure', "
        "'shared_config_ensure', 'restore_shared_files', 'sync_scripts', "
        "'sync_documents', 'sync_deploy')",
    )
