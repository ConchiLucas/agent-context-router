"""Create persistent document projects.

Revision ID: 20260721_0003
Revises: 20260720_0002
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_0003"
down_revision: str | None = "20260720_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_projects",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("agents_path", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agents_path", name="uq_document_projects_agents_path"),
    )
    op.create_index(
        "ix_document_projects_enabled_created_at",
        "document_projects",
        ["enabled", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_projects_enabled_created_at",
        table_name="document_projects",
    )
    op.drop_table("document_projects")
