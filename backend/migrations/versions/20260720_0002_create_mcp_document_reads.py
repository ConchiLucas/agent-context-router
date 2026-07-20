"""Create MCP document read history.

Revision ID: 20260720_0002
Revises: 20260720_0001
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_0002"
down_revision: str | None = "20260720_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_document_read_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["mcp_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_document_read_calls_task_id_id",
        "mcp_document_read_calls",
        ["task_id", "id"],
    )

    op.create_table(
        "mcp_document_read_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("read_call_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("document_id", sa.String(length=20), nullable=False),
        sa.Column("document_path", sa.Text(), nullable=True),
        sa.Column("requested_section", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('ok', 'error')", name="ck_mcp_read_item_status"),
        sa.ForeignKeyConstraint(
            ["read_call_id"],
            ["mcp_document_read_calls.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "read_call_id",
            "position",
            name="uq_mcp_document_read_items_call_position",
        ),
    )
    op.create_index(
        "ix_mcp_document_read_items_call_position",
        "mcp_document_read_items",
        ["read_call_id", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_document_read_items_call_position",
        table_name="mcp_document_read_items",
    )
    op.drop_table("mcp_document_read_items")
    op.drop_index(
        "ix_mcp_document_read_calls_task_id_id",
        table_name="mcp_document_read_calls",
    )
    op.drop_table("mcp_document_read_calls")
