"""Store the labeled correct interface for prompt comparison rows.

Revision ID: 20260906_0085
Revises: 20260906_0084
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0085"
down_revision: str | None = "20260906_0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_prompt_matches",
        sa.Column("expected_interface_id", sa.String(120), nullable=True),
    )
    op.add_column(
        "interface_prompt_matches",
        sa.Column("expected_method", sa.String(16), nullable=False, server_default=""),
    )
    op.add_column(
        "interface_prompt_matches",
        sa.Column("expected_path", sa.String(600), nullable=False, server_default=""),
    )
    op.add_column(
        "interface_prompt_matches",
        sa.Column("expected_title", sa.String(300), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("interface_prompt_matches", "expected_title")
    op.drop_column("interface_prompt_matches", "expected_path")
    op.drop_column("interface_prompt_matches", "expected_method")
    op.drop_column("interface_prompt_matches", "expected_interface_id")
