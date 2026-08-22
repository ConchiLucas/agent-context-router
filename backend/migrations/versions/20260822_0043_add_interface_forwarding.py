"""Add workspace-scoped interface forwarding management.

Revision ID: 20260822_0043
Revises: 20260822_0042
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260822_0043"
down_revision: str | None = "20260822_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interface_forwarding_services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("workspace_id", "name", name="uq_interface_forwarding_service_name"),
    )
    op.create_table(
        "interface_forwarding_interfaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "service_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("method", sa.String(12), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "request_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "response_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "service_id", "path", "method", name="uq_interface_forwarding_endpoint"
        ),
    )
    op.create_index(
        "ix_interface_forwarding_interfaces_workspace",
        "interface_forwarding_interfaces",
        ["workspace_id"],
    )
    op.create_table(
        "interface_forwarding_environments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "workspace_id", "name", name="uq_interface_forwarding_environment_name"
        ),
    )
    op.create_table(
        "interface_forwarding_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "environment_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_environments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nickname", sa.String(160), nullable=False),
        sa.Column("login_account", sa.String(240), nullable=False, server_default=""),
        sa.Column("login_password", sa.Text(), nullable=False, server_default=""),
        sa.Column("role_code", sa.String(160), nullable=False, server_default=""),
        sa.Column("role_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("request_header", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "interface_forwarding_params",
        sa.Column(
            "interface_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_interfaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "environment_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_environments.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "identity_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_identities.id", ondelete="SET NULL"),
        ),
        sa.Column("request_body", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("response_body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "interface_forwarding_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "interface_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_interfaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("environment_name", sa.String(120), nullable=False),
        sa.Column("identity_name", sa.String(160)),
        sa.Column("request_url", sa.String(2000), nullable=False),
        sa.Column("request_body", sa.Text(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_interface_forwarding_logs_interface_created",
        "interface_forwarding_logs",
        ["interface_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("interface_forwarding_logs")
    op.drop_table("interface_forwarding_params")
    op.drop_table("interface_forwarding_identities")
    op.drop_table("interface_forwarding_environments")
    op.drop_table("interface_forwarding_interfaces")
    op.drop_table("interface_forwarding_services")
