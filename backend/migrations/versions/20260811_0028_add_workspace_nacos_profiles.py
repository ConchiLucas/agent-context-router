"""Add task-scoped Nacos middleware profiles.

Revision ID: 20260811_0028
Revises: 20260810_0027
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260811_0028"
down_revision: str | None = "20260810_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_nacos_profiles",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("profile_key", sa.String(length=8), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("namespace_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("password", sa.Text(), nullable=False, server_default=""),
        sa.Column("request_timeout_ms", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column(
            "components",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "profile_key IN ('default','test','uat')",
            name="ck_workspace_nacos_profiles_key",
        ),
        sa.CheckConstraint(
            "request_timeout_ms BETWEEN 500 AND 30000",
            name="ck_workspace_nacos_profiles_timeout",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(components) = 'array' AND jsonb_array_length(components) > 0",
            name="ck_workspace_nacos_profiles_components",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "profile_key"),
    )


def downgrade() -> None:
    op.drop_table("workspace_nacos_profiles")
