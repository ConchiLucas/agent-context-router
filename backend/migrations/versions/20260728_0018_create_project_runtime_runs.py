"""Create project runtime execution records.

Revision ID: 20260728_0018
Revises: 20260728_0017
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260728_0018"
down_revision: str | None = "20260728_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_runtime_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("materialized_path", sa.Text(), nullable=False),
        sa.Column("project_root", sa.Text(), nullable=False),
        sa.Column("entry_file", sa.Text(), nullable=False),
        sa.Column("log_path", sa.Text(), nullable=False),
        sa.Column(
            "changed_files",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('fast', 'full')",
            name="ck_project_runtime_runs_mode",
        ),
        sa.CheckConstraint(
            "trigger IN ('ui', 'mcp')",
            name="ck_project_runtime_runs_trigger",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_project_runtime_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["document_projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_runtime_runs_project_created",
        "project_runtime_runs",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_project_runtime_runs_status_created",
        "project_runtime_runs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_runtime_runs_status_created",
        table_name="project_runtime_runs",
    )
    op.drop_index(
        "ix_project_runtime_runs_project_created",
        table_name="project_runtime_runs",
    )
    op.drop_table("project_runtime_runs")
