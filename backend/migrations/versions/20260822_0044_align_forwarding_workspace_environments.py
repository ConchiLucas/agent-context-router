"""Align forwarding environments with the Workspace registry.

Revision ID: 20260822_0044
Revises: 20260822_0043
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0044"
down_revision: str | None = "20260822_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_environments",
        sa.Column("environment_key", sa.String(32), nullable=True),
    )
    op.execute(
        """
        UPDATE interface_forwarding_environments AS forwarding
        SET environment_key = workspace.environment_key,
            name = workspace.display_name
        FROM workspace_environments AS workspace
        WHERE workspace.workspace_id = forwarding.workspace_id
          AND lower(workspace.environment_key) = lower(forwarding.name)
        """
    )
    # Old standalone forwarding environments have no valid meaning after this
    # change. Removing them also removes their identities through the existing
    # cascade instead of silently binding them to an unrelated Workspace key.
    op.execute("DELETE FROM interface_forwarding_environments WHERE environment_key IS NULL")
    op.alter_column(
        "interface_forwarding_environments",
        "environment_key",
        existing_type=sa.String(32),
        nullable=False,
    )
    op.drop_constraint(
        "uq_interface_forwarding_environment_name",
        "interface_forwarding_environments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_interface_forwarding_environment_key",
        "interface_forwarding_environments",
        ["workspace_id", "environment_key"],
    )
    op.create_foreign_key(
        "fk_interface_forwarding_workspace_environment",
        "interface_forwarding_environments",
        "workspace_environments",
        ["workspace_id", "environment_key"],
        ["workspace_id", "environment_key"],
        ondelete="CASCADE",
    )
    op.alter_column(
        "interface_forwarding_environments",
        "base_url",
        existing_type=sa.String(1000),
        server_default="",
    )
    for column_name in ("nickname", "login_password", "role_code", "role_name"):
        op.drop_column("interface_forwarding_identities", column_name)
    op.execute(
        """CREATE UNIQUE INDEX uq_interface_forwarding_identity_account
        ON interface_forwarding_identities (environment_id, lower(login_account))"""
    )


def downgrade() -> None:
    op.drop_index(
        "uq_interface_forwarding_identity_account",
        table_name="interface_forwarding_identities",
    )
    op.add_column(
        "interface_forwarding_identities",
        sa.Column("role_name", sa.String(160), nullable=False, server_default=""),
    )
    op.add_column(
        "interface_forwarding_identities",
        sa.Column("role_code", sa.String(160), nullable=False, server_default=""),
    )
    op.add_column(
        "interface_forwarding_identities",
        sa.Column("login_password", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "interface_forwarding_identities",
        sa.Column("nickname", sa.String(160), nullable=False, server_default=""),
    )
    op.drop_constraint(
        "fk_interface_forwarding_workspace_environment",
        "interface_forwarding_environments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_interface_forwarding_environment_key",
        "interface_forwarding_environments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_interface_forwarding_environment_name",
        "interface_forwarding_environments",
        ["workspace_id", "name"],
    )
    op.drop_column("interface_forwarding_environments", "environment_key")
