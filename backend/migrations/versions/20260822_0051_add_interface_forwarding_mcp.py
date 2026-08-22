"""Add task-scoped interface-forwarding MCP plans and routing metadata.

Revision ID: 20260822_0051
Revises: 20260822_0050
Create Date: 2026-08-22
"""
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260822_0051"
down_revision: str | None = "20260822_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interface_forwarding_services",
        sa.Column("invocation_mode", sa.String(16), nullable=False, server_default="direct"),
    )
    op.add_column(
        "interface_forwarding_services",
        sa.Column("gateway_service_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "interface_forwarding_services",
        sa.Column("gateway_path_prefix", sa.String(500), nullable=False, server_default=""),
    )
    op.create_foreign_key(
        "fk_interface_forwarding_gateway_service",
        "interface_forwarding_services",
        "interface_forwarding_services",
        ["gateway_service_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_interface_forwarding_invocation_mode",
        "interface_forwarding_services",
        "invocation_mode IN ('direct', 'gateway', 'disabled')",
    )

    op.add_column(
        "interface_forwarding_interfaces",
        sa.Column("operation_kind", sa.String(16), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "interface_forwarding_interfaces",
        sa.Column(
            "request_contract",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_interface_forwarding_operation_kind",
        "interface_forwarding_interfaces",
        "operation_kind IN ('read', 'write', 'destructive', 'unknown')",
    )
    op.execute(
        """UPDATE interface_forwarding_interfaces
        SET request_contract=jsonb_build_object(
              'path', jsonb_build_object('type', 'object', 'properties', '{}'::jsonb),
              'query', jsonb_build_object('type', 'object', 'properties', '{}'::jsonb),
              'body', COALESCE(request_schema, '{}'::jsonb)
            ),
            operation_kind=CASE
              WHEN name LIKE '%取消订阅%' THEN 'write'
              WHEN name ~ '^(删除|批量删除|取消|驳回|停用|禁用|撤销|清除)' THEN 'destructive'
              WHEN name ~ '^(新增|保存|更新|修改|创建|上传|提交|确认|启用|同步|导入|发货|调度)' THEN 'write'
              WHEN method IN ('GET', 'HEAD', 'OPTIONS') THEN 'read'
              WHEN name ~ '^(查询|分页查询|获取|统计|下载|预览|校验|检查|搜索|列出|按.+查询)' THEN 'read'
              ELSE 'unknown'
            END"""
    )
    op.execute(
        """UPDATE interface_forwarding_services AS data
        SET invocation_mode='gateway', gateway_service_id=mtp.id,
            gateway_path_prefix='data'
        FROM interface_forwarding_services AS mtp
        WHERE data.workspace_id=mtp.workspace_id
          AND lower(data.name)='c12-data'
          AND lower(mtp.name)='c12-mtp'"""
    )

    op.create_table(
        "interface_forwarding_request_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("mcp_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column("environment_key", sa.String(32), nullable=False),
        sa.Column(
            "address_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_environments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.String(36),
            sa.ForeignKey("interface_forwarding_identities.id", ondelete="SET NULL"),
        ),
        sa.Column("operation_kind", sa.String(16), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(64), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_interface_forwarding_plans_task_created",
        "interface_forwarding_request_plans",
        ["task_id", "created_at"],
    )

    for _name, column in (
        (
            "task_id",
            sa.Column(
                "task_id", sa.BigInteger(), sa.ForeignKey("mcp_tasks.id", ondelete="SET NULL")
            ),
        ),
        (
            "tool_call_id",
            sa.Column(
                "tool_call_id",
                sa.BigInteger(),
                sa.ForeignKey("mcp_tool_calls.id", ondelete="SET NULL"),
            ),
        ),
        (
            "plan_id",
            sa.Column(
                "plan_id",
                sa.String(36),
                sa.ForeignKey("interface_forwarding_request_plans.id", ondelete="SET NULL"),
            ),
        ),
        ("environment_key", sa.Column("environment_key", sa.String(32))),
        (
            "address_id",
            sa.Column(
                "address_id",
                sa.String(36),
                sa.ForeignKey("interface_forwarding_environments.id", ondelete="SET NULL"),
            ),
        ),
        (
            "identity_id",
            sa.Column(
                "identity_id",
                sa.String(36),
                sa.ForeignKey("interface_forwarding_identities.id", ondelete="SET NULL"),
            ),
        ),
        ("request_sha256", sa.Column("request_sha256", sa.String(64))),
        (
            "response_bytes",
            sa.Column("response_bytes", sa.Integer(), nullable=False, server_default="0"),
        ),
        (
            "response_truncated",
            sa.Column(
                "response_truncated", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        ),
    ):
        op.add_column("interface_forwarding_logs", column)
    op.create_index(
        "ix_interface_forwarding_logs_task_created",
        "interface_forwarding_logs",
        ["task_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interface_forwarding_logs_task_created", table_name="interface_forwarding_logs"
    )
    for name in (
        "response_truncated",
        "response_bytes",
        "request_sha256",
        "identity_id",
        "address_id",
        "environment_key",
        "plan_id",
        "tool_call_id",
        "task_id",
    ):
        op.drop_column("interface_forwarding_logs", name)
    op.drop_index(
        "ix_interface_forwarding_plans_task_created",
        table_name="interface_forwarding_request_plans",
    )
    op.drop_table("interface_forwarding_request_plans")
    op.drop_constraint(
        "ck_interface_forwarding_operation_kind", "interface_forwarding_interfaces", type_="check"
    )
    op.drop_column("interface_forwarding_interfaces", "request_contract")
    op.drop_column("interface_forwarding_interfaces", "operation_kind")
    op.drop_constraint(
        "ck_interface_forwarding_invocation_mode", "interface_forwarding_services", type_="check"
    )
    op.drop_constraint(
        "fk_interface_forwarding_gateway_service",
        "interface_forwarding_services",
        type_="foreignkey",
    )
    op.drop_column("interface_forwarding_services", "gateway_path_prefix")
    op.drop_column("interface_forwarding_services", "gateway_service_id")
    op.drop_column("interface_forwarding_services", "invocation_mode")
