"""Add Apache Doris as a data source engine.

Revision ID: 20260821_0041
Revises: 20260820_0040
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0041"
down_revision: str | None = "20260820_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_data_sources_engine", "data_sources", type_="check")
    op.create_check_constraint(
        "ck_data_sources_engine",
        "data_sources",
        "engine IN ('mysql','mariadb','doris','postgresql','sqlserver','sqlite','oracle','clickhouse')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_data_sources_engine", "data_sources", type_="check")
    op.create_check_constraint(
        "ck_data_sources_engine",
        "data_sources",
        "engine IN ('mysql','mariadb','postgresql','sqlserver','sqlite','oracle','clickhouse')",
    )
