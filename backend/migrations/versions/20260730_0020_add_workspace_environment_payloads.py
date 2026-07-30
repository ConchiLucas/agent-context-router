"""Add workspace environment JSON payloads.

Revision ID: 20260730_0020
Revises: 20260730_0019
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260730_0020"
down_revision: str | None = "20260730_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_environment_payloads",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "environment IN ('test','uat')",
            name="ck_workspace_environment_payloads_environment",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace_database_environment_configs.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "environment"),
    )


def downgrade() -> None:
    op.drop_table("workspace_environment_payloads")
