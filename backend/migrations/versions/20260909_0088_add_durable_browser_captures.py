"""Persist browser observations independently of interface matching."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20260909_0088"
down_revision = "20260909_0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("interface_forwarding_logs", "request_url", type_=sa.Text())
    op.create_table(
        "browser_interface_captures",
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("capture_id", sa.String(128), primary_key=True),
        sa.Column("environment_key", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("match_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False, server_default=""),
        sa.Column(
            "log_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_logs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_browser_captures_pending",
        "browser_interface_captures",
        ["workspace_id", "match_status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("browser_interface_captures")
    # Keep the widened URL column: narrowing it could destroy existing long URLs.
