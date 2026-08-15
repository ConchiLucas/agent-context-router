"""Retain the rolled-back table-relation revision marker.

Revision ID: 20260812_0031
Revises: 20260812_0030
"""

from collections.abc import Sequence

revision: str = "20260812_0031"
down_revision: str | None = "20260812_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
