"""Route c12-data forwarding through the c12-mtp /data gateway prefix.

Revision ID: 20260822_0052
Revises: 20260822_0051
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260822_0052"
down_revision: str | None = "20260822_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """UPDATE interface_forwarding_services AS data
        SET invocation_mode='gateway', gateway_service_id=mtp.id,
            gateway_path_prefix='data'
        FROM interface_forwarding_services AS mtp
        WHERE data.workspace_id=mtp.workspace_id
          AND lower(data.name)='c12-data'
          AND lower(mtp.name)='c12-mtp'"""
    )


def downgrade() -> None:
    op.execute(
        """UPDATE interface_forwarding_services
        SET gateway_path_prefix=''
        WHERE lower(name)='c12-data' AND invocation_mode='gateway'"""
    )
