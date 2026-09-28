"""Persist prompt-to-interface match records for the prompt lab.

Revision ID: 20260906_0084
Revises: 20260906_0083
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0084"
down_revision: str | None = "20260906_0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interface_prompt_matches",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("workspace_id", sa.String(120), nullable=False),
        sa.Column("environment_key", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("first_interface_id", sa.String(120), nullable=True),
        sa.Column("candidates", postgresql.JSONB(), nullable=False),
        sa.Column("remaining_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("search_id", sa.String(120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "differing_dimensions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("length(prompt) > 0", name="ck_interface_prompt_matches_prompt"),
        sa.CheckConstraint(
            "verdict IN ('resolved', 'needs_selection', 'no_candidate')",
            name="ck_interface_prompt_matches_verdict",
        ),
        sa.CheckConstraint(
            "remaining_count >= 0",
            name="ck_interface_prompt_matches_remaining",
        ),
    )
    op.create_index(
        "ix_interface_prompt_matches_workspace_created",
        "interface_prompt_matches",
        ["workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interface_prompt_matches_workspace_created",
        table_name="interface_prompt_matches",
    )
    op.drop_table("interface_prompt_matches")
