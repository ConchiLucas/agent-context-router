"""Add controller metadata to imported interfaces.

Revision ID: 20260822_0046
Revises: 20260822_0045
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0046"
down_revision: str | None = "20260822_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_interfaces",
        sa.Column("controller_name", sa.String(240), nullable=False, server_default=""),
    )
    op.add_column(
        "interface_forwarding_interfaces",
        sa.Column("controller_description", sa.Text(), nullable=False, server_default=""),
    )
    op.execute(
        """UPDATE interface_forwarding_interfaces
        SET controller_name='BtAttachmentController',
            controller_description='附件管理'
        WHERE path IN ('/admin/attachment/upload', '/admin/attachment/downLoad')"""
    )


def downgrade() -> None:
    op.drop_column("interface_forwarding_interfaces", "controller_description")
    op.drop_column("interface_forwarding_interfaces", "controller_name")
