"""Add SQL preprocessor audit evidence.

Revision ID: 20260813_0034
Revises: 20260813_0033
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_0034"
down_revision: str | None = "20260813_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "table_join_evidences",
        sa.Column("preprocess_profile_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "table_join_evidences",
        sa.Column("preprocess_profile_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "table_join_evidences",
        sa.Column("preprocess_candidate_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "table_join_evidences",
        sa.Column(
            "applied_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "table_join_evidences",
        sa.Column("template_derived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_table_join_evidences_applied_rules",
        "table_join_evidences",
        "jsonb_typeof(applied_rules) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_table_join_evidences_applied_rules",
        "table_join_evidences",
        type_="check",
    )
    op.drop_column("table_join_evidences", "template_derived")
    op.drop_column("table_join_evidences", "applied_rules")
    op.drop_column("table_join_evidences", "preprocess_candidate_id")
    op.drop_column("table_join_evidences", "preprocess_profile_hash")
    op.drop_column("table_join_evidences", "preprocess_profile_id")
