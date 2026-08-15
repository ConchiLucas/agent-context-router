"""Retain the rolled-back endpoint-write revision marker.

Revision ID: 20260812_0030
Revises: 20260812_0029
"""

from collections.abc import Sequence

revision: str = "20260812_0030"
down_revision: str | None = "20260812_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
