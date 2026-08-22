"""Map every forwarding address to an imported interface service.

Revision ID: 20260822_0047
Revises: 20260822_0046
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0047"
down_revision: str | None = "20260822_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_environments",
        sa.Column("service_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_interface_forwarding_address_service",
        "interface_forwarding_environments",
        "interface_forwarding_services",
        ["service_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.execute(
        """UPDATE interface_forwarding_environments AS address
        SET service_id=service.id
        FROM interface_forwarding_services AS service
        WHERE service.workspace_id=address.workspace_id
          AND (
            (lower(service.name)='c12-portal' AND address.base_url ~* '/portal/?$')
            OR (lower(service.name)='c12-mtp' AND address.base_url ~* '/mtp/?$')
            OR (lower(service.name)='c12-data' AND address.base_url ~* '/data/?$')
          )"""
    )
    op.drop_index(
        "uq_interface_forwarding_address_name",
        table_name="interface_forwarding_environments",
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_interface_forwarding_address_service_name
        ON interface_forwarding_environments
        (workspace_id, environment_key, service_id, lower(name))"""
    )
    op.create_index(
        "ix_interface_forwarding_address_service",
        "interface_forwarding_environments",
        ["service_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interface_forwarding_address_service",
        table_name="interface_forwarding_environments",
    )
    op.drop_index(
        "uq_interface_forwarding_address_service_name",
        table_name="interface_forwarding_environments",
    )
    op.execute(
        """DELETE FROM interface_forwarding_environments
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY workspace_id, environment_key, lower(name)
                    ORDER BY created_at, id
                ) AS position
                FROM interface_forwarding_environments
            ) AS ranked
            WHERE position > 1
        )"""
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_interface_forwarding_address_name
        ON interface_forwarding_environments
        (workspace_id, environment_key, lower(name))"""
    )
    op.drop_constraint(
        "fk_interface_forwarding_address_service",
        "interface_forwarding_environments",
        type_="foreignkey",
    )
    op.drop_column("interface_forwarding_environments", "service_id")
