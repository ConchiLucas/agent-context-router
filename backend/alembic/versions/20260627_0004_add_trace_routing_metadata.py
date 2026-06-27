"""add trace routing metadata

Revision ID: 20260627_0004
Revises: 20260627_0003
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260627_0004"
down_revision: str | None = "20260627_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _has_column("traces", "area"):
        op.add_column("traces", sa.Column("area", sa.String(length=120), nullable=True))
    if not _has_index("traces", op.f("ix_traces_area")):
        op.create_index(op.f("ix_traces_area"), "traces", ["area"], unique=False)

    if not _has_column("traces", "entrypoint_path"):
        op.add_column(
            "traces",
            sa.Column("entrypoint_path", sa.String(length=1024), nullable=True),
        )
    if not _has_column("traces", "entrypoint_rule"):
        op.add_column("traces", sa.Column("entrypoint_rule", sa.Text(), nullable=True))
    if not _has_column("traces", "route_hint"):
        op.add_column("traces", sa.Column("route_hint", sa.String(length=240), nullable=True))

    if not _has_column("traces", "source"):
        op.add_column("traces", sa.Column("source", sa.String(length=80), nullable=True))
    if not _has_index("traces", op.f("ix_traces_source")):
        op.create_index(op.f("ix_traces_source"), "traces", ["source"], unique=False)


def downgrade() -> None:
    if _has_index("traces", op.f("ix_traces_source")):
        op.drop_index(op.f("ix_traces_source"), table_name="traces")
    if _has_column("traces", "source"):
        op.drop_column("traces", "source")

    if _has_column("traces", "route_hint"):
        op.drop_column("traces", "route_hint")
    if _has_column("traces", "entrypoint_rule"):
        op.drop_column("traces", "entrypoint_rule")
    if _has_column("traces", "entrypoint_path"):
        op.drop_column("traces", "entrypoint_path")

    if _has_index("traces", op.f("ix_traces_area")):
        op.drop_index(op.f("ix_traces_area"), table_name="traces")
    if _has_column("traces", "area"):
        op.drop_column("traces", "area")
