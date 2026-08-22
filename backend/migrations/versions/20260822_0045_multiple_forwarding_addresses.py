"""Allow multiple named forwarding addresses per Workspace environment.

Revision ID: 20260822_0045
Revises: 20260822_0044
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260822_0045"
down_revision: str | None = "20260822_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_interface_forwarding_environment_key",
        "interface_forwarding_environments",
        type_="unique",
    )
    op.execute("UPDATE interface_forwarding_environments SET name='默认地址'")
    op.execute(
        """CREATE UNIQUE INDEX uq_interface_forwarding_address_name
        ON interface_forwarding_environments
        (workspace_id, environment_key, lower(name))"""
    )


def downgrade() -> None:
    op.drop_index(
        "uq_interface_forwarding_address_name",
        table_name="interface_forwarding_environments",
    )
    op.execute(
        """DELETE FROM interface_forwarding_environments
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY workspace_id, environment_key
                    ORDER BY created_at, id
                ) AS position
                FROM interface_forwarding_environments
            ) AS ranked
            WHERE position > 1
        )"""
    )
    op.execute(
        """UPDATE interface_forwarding_environments AS forwarding
        SET name=workspace.display_name
        FROM workspace_environments AS workspace
        WHERE workspace.workspace_id=forwarding.workspace_id
          AND workspace.environment_key=forwarding.environment_key"""
    )
    op.create_unique_constraint(
        "uq_interface_forwarding_environment_key",
        "interface_forwarding_environments",
        ["workspace_id", "environment_key"],
    )
