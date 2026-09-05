"""Persist structured runtime step readiness.

Revision ID: 20260905_0078
Revises: 20260904_0077
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260905_0078"
down_revision: str | None = "20260904_0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runtime_operation_steps",
        sa.Column("readiness_result", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runtime_operation_steps", "readiness_result")
