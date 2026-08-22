"""Disable raw c12-data Controller forwarding until explicit MTP mappings exist.

Revision ID: 20260822_0054
Revises: 20260822_0053
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260822_0054"
down_revision: str | None = "20260822_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """UPDATE interface_forwarding_services
        SET invocation_mode='disabled', gateway_service_id=NULL,
            gateway_path_prefix=''
        WHERE lower(name)='c12-data'"""
    )


def downgrade() -> None:
    op.execute(
        """UPDATE interface_forwarding_services AS data
        SET invocation_mode='gateway', gateway_service_id=mtp.id,
            gateway_path_prefix='data'
        FROM interface_forwarding_services AS mtp
        WHERE data.workspace_id=mtp.workspace_id
          AND lower(data.name)='c12-data'
          AND lower(mtp.name)='c12-mtp'"""
    )
