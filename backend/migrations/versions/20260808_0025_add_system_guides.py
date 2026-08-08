"""Add centrally managed system usage guides.

Revision ID: 20260808_0025
Revises: 20260808_0024
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260808_0025"
down_revision: str | None = "20260808_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = op.create_table(
        "system_guides",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("guide_key", sa.String(64), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "include_in_prepare",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
        sa.CheckConstraint("sort_order >= 0", name="ck_system_guides_sort_order"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guide_key", name="uq_system_guides_key"),
    )
    op.bulk_insert(
        table,
        [
            {
                "id": "7f9c6f9b748c4ca18be1ca1822f3e43d",
                "guide_key": "workspace-directory-access",
                "document": {
                    "schema_version": 1,
                    "key": "workspace-directory-access",
                    "title": "工作空间目录使用规则",
                    "summary": "说明主目录与文档阅读目录的权限、同步和切换规则。",
                    "sections": [
                        {
                            "title": "主目录",
                            "rules": [
                                "主目录是文档和部署文件的唯一维护目录",
                                "可以使用文档、数据库和部署工具",
                                "可以执行主目录与数据库之间的全量覆盖",
                            ],
                        },
                        {
                            "title": "文档阅读目录",
                            "rules": [
                                "与主目录归属于同一张工作空间卡片",
                                "可以读取主目录的共享文档",
                                "不能使用数据库、部署和共享文件覆盖功能",
                            ],
                        },
                        {
                            "title": "切换与同步",
                            "rules": [
                                "阅读目录需要数据库或部署能力时，切换到主目录并重新 prepare",
                                "不要把主目录文档和部署脚本复制到阅读目录",
                                "本机路径只维护在 Context Router 的 workspaces.local.yaml 中",
                            ],
                        },
                    ],
                },
                "include_in_prepare": True,
                "sort_order": 10,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("system_guides")
