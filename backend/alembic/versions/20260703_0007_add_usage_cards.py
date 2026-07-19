"""add usage cards

Revision ID: 20260703_0007
Revises: 20260629_0006
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260703_0007"
down_revision: str | None = "20260629_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("usage_cards"):
        op.create_table(
            "usage_cards",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("slug", sa.String(length=160), nullable=False),
            sa.Column("title", sa.String(length=240), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("content_markdown", sa.Text(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("is_builtin", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )

    index_name = op.f("ix_usage_cards_slug")
    if not _has_index("usage_cards", index_name):
        op.create_index(index_name, "usage_cards", ["slug"], unique=False)


def downgrade() -> None:
    if _has_table("usage_cards"):
        index_name = op.f("ix_usage_cards_slug")
        if _has_index("usage_cards", index_name):
            op.drop_index(index_name, table_name="usage_cards")
        op.drop_table("usage_cards")
