"""Retain the rolled-back runtime-operation revision marker.

Revision ID: 20260812_0029
Revises: 20260811_0028

This repository no longer ships the experimental endpoint-write feature that
originally occupied revisions 0029-0031. Existing local databases can still be
at those revision identifiers, so the markers remain as intentional no-ops.
"""

from collections.abc import Sequence

revision: str = "20260812_0029"
down_revision: str | None = "20260811_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
