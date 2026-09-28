"""Persist audited blind interface-prompt client results."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20260914_0089"
down_revision = "20260909_0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interface_prompt_client_results",
        sa.Column(
            "prompt_match_id",
            sa.String(36),
            sa.ForeignKey("interface_prompt_matches.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("client", sa.String(32), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("batch_id", sa.String(32), nullable=False),
        sa.Column("model", sa.String(160), nullable=False, server_default=""),
        sa.Column("reasoning_effort", sa.String(64), nullable=False, server_default=""),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "client IN ('codex', 'codex-root', 'codex-astra', 'cursor', 'antigravity')",
            name="ck_interface_prompt_client_results_client",
        ),
    )
    op.create_index(
        "ix_interface_prompt_client_results_client",
        "interface_prompt_client_results",
        ["client", "prompt_match_id"],
    )


def downgrade() -> None:
    op.drop_table("interface_prompt_client_results")
