"""Add Workspace runtime orchestration and Host Runner state.

Revision ID: 20260802_0023
Revises: 20260730_0022
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260802_0023"
down_revision: str | None = "20260730_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_runtime_files",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("workspace_id", sa.String(32), nullable=False),
        sa.Column("profile", sa.String(16), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("executable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("profile = 'start'", name="ck_workspace_runtime_files_profile"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "profile", "relative_path", name="uq_workspace_runtime_files_owner_path"
        ),
    )
    op.create_index(
        "ix_workspace_runtime_files_owner_order",
        "workspace_runtime_files",
        ["workspace_id", "profile", "sort_order"],
    )
    op.create_table(
        "workspace_runtime_policies",
        sa.Column("workspace_id", sa.String(32), nullable=False),
        sa.Column(
            "project_order",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "workspace_paths",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_table(
        "runtime_operations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "changed_files",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("current_step", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("runner_id", sa.String(64), nullable=True),
        sa.Column("lease_token_hash", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('apply_changes','start_workspace')", name="ck_runtime_operations_kind"
        ),
        sa.CheckConstraint("trigger IN ('mcp','api')", name="ck_runtime_operations_trigger"),
        sa.CheckConstraint(
            "status IN "
            "('queued','leased','running','succeeded','failed','cancelled','interrupted')",
            name="ck_runtime_operations_status",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["mcp_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_operations_workspace_created",
        "runtime_operations",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_runtime_operations_status_created", "runtime_operations", ["status", "created_at"]
    )
    op.create_index(
        "uq_runtime_operations_active_workspace",
        "runtime_operations",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','leased','running')"),
    )
    op.create_table(
        "runtime_operation_steps",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("operation_id", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("owner_type", sa.String(16), nullable=False),
        sa.Column("owner_id", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("snapshot_relative_path", sa.Text(), nullable=False),
        sa.Column("entry_file", sa.Text(), server_default=sa.text("'deploy.sh'"), nullable=False),
        sa.Column(
            "changed_files",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("log_relative_path", sa.Text(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "owner_type IN ('workspace','project')", name="ck_runtime_operation_steps_owner"
        ),
        sa.CheckConstraint(
            "mode IN ('start','fast','full')", name="ck_runtime_operation_steps_mode"
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','skipped','cancelled')",
            name="ck_runtime_operation_steps_status",
        ),
        sa.ForeignKeyConstraint(["operation_id"], ["runtime_operations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", "sequence", name="uq_runtime_operation_steps_sequence"),
    )
    op.create_index(
        "ix_runtime_operation_steps_operation",
        "runtime_operation_steps",
        ["operation_id", "sequence"],
    )
    op.create_index(
        "uq_runtime_operation_steps_active_project",
        "runtime_operation_steps",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("owner_type = 'project' AND status IN ('queued','running')"),
    )
    op.create_table(
        "runtime_runner_instances",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column(
            "capabilities",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('online','offline')", name="ck_runtime_runner_instances_status"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("runtime_runner_instances")
    op.drop_index("uq_runtime_operation_steps_active_project", table_name="runtime_operation_steps")
    op.drop_index("ix_runtime_operation_steps_operation", table_name="runtime_operation_steps")
    op.drop_table("runtime_operation_steps")
    op.drop_index("uq_runtime_operations_active_workspace", table_name="runtime_operations")
    op.drop_index("ix_runtime_operations_status_created", table_name="runtime_operations")
    op.drop_index("ix_runtime_operations_workspace_created", table_name="runtime_operations")
    op.drop_table("runtime_operations")
    op.drop_table("workspace_runtime_policies")
    op.drop_index("ix_workspace_runtime_files_owner_order", table_name="workspace_runtime_files")
    op.drop_table("workspace_runtime_files")
