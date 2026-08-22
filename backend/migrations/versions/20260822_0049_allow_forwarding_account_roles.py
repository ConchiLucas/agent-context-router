"""Allow one forwarding account to have multiple roles per address.

Revision ID: 20260822_0049
Revises: 20260822_0048
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260822_0049"
down_revision: str | None = "20260822_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "uq_interface_forwarding_identity_account",
        table_name="interface_forwarding_identities",
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_interface_forwarding_identity_account_role
        ON interface_forwarding_identities
        (environment_id, lower(login_account), lower(role_name))"""
    )


def downgrade() -> None:
    op.drop_index(
        "uq_interface_forwarding_identity_account_role",
        table_name="interface_forwarding_identities",
    )
    op.execute(
        """DELETE FROM interface_forwarding_identities
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY environment_id, lower(login_account)
                    ORDER BY created_at, id
                ) AS position
                FROM interface_forwarding_identities
            ) AS ranked
            WHERE position > 1
        )"""
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_interface_forwarding_identity_account
        ON interface_forwarding_identities (environment_id, lower(login_account))"""
    )
