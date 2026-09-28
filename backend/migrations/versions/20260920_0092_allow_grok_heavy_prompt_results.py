"""Allow Grok Heavy interface-prompt client results.

Revision ID: 20260920_0092
Revises: 20260919_0091
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260920_0092"
down_revision: str | None = "20260919_0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CONSTRAINT_NAME = "ck_interface_prompt_client_results_client"
_CLIENTS_BEFORE = "('codex', 'codex-root', 'codex-astra', 'cursor', 'antigravity')"
_CLIENTS_AFTER = (
    "('codex', 'codex-root', 'codex-astra', 'cursor', 'antigravity', 'grok-heavy')"
)


def upgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "interface_prompt_client_results",
        type_="check",
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "interface_prompt_client_results",
        f"client IN {_CLIENTS_AFTER}",
    )


def downgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "interface_prompt_client_results",
        type_="check",
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "interface_prompt_client_results",
        f"client IN {_CLIENTS_BEFORE}",
    )
