"""Store a short confusion note for prompt comparison rows.

Revision ID: 20260906_0086
Revises: 20260906_0085
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0086"
down_revision: str | None = "20260906_0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_prompt_matches",
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("interface_prompt_matches", "note")
