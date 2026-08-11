"""Add the Context Router MCP usage system guide.

Revision ID: 20260809_0026
Revises: 20260808_0025
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260809_0026"
down_revision: str | None = "20260808_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    system_guides = sa.table(
        "system_guides",
        sa.column("id", sa.String(32)),
        sa.column("guide_key", sa.String(64)),
        sa.column("document", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("include_in_prepare", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        system_guides,
        [
            {
                "id": "9e31b63c2cf74f03bd1f8dcdc4210d2a",
                "guide_key": "context-router-mcp-usage",
                "document": {
                    "schema_version": 1,
                    "key": "context-router-mcp-usage",
                    "title": "Context Router MCP 使用指南",
                    "summary": (
                        "说明 MCP 接入、上下文准备、文档读取、数据库查询和"
                        "工作空间部署的标准调用方式。"
                    ),
                    "sections": [
                        {
                            "title": "接入 MCP",
                            "rules": [
                                "优先使用工作空间中的 MCP 接入面板生成客户端配置",
                                "本机默认 MCP 地址为 http://127.0.0.1:49173/mcp",
                                "连接成功后应看到 Context Router 提供的上下文、数据库和运行工具",
                            ],
                        },
                        {
                            "title": "每个新任务先 prepare",
                            "steps": [
                                "新会话或新任务只调用一次 prepare_task_context",
                                (
                                    "传入当前任务描述、cwd 和 agent_name；需要固定 TEST 或 UAT 时"
                                    "再传 environment"
                                ),
                                (
                                    "保存返回的 task_id，并在该任务后续所有文档、数据库和"
                                    "运行工具中复用"
                                ),
                                (
                                    "先遵循 system_guides.required；catalog 中的其他指南可用 "
                                    "read_context_document 读取"
                                ),
                            ],
                        },
                        {
                            "title": "查找和读取文档",
                            "steps": [
                                "目标明确时，直接读取 prepare 返回树中的 document_id",
                                "目标不明确或文档树较大时，先调用 search_context_documents",
                                "根据搜索结果的 document_id 和 section 调用 read_context_document",
                                "不要猜测文档路径，也不要绕过 prepare 使用其他任务的 task_id",
                            ],
                        },
                        {
                            "title": "查询数据库",
                            "steps": [
                                "只使用 prepare 返回并授权给当前任务的数据库 alias",
                                "不确定表、字段或索引时，先调用 search_database_objects",
                                "再用 execute_database_query 执行单条有界只读 SQL",
                                (
                                    "environment_config 可能包含敏感配置，只用于当前任务，"
                                    "不写入日志、文档或回答"
                                ),
                            ],
                        },
                        {
                            "title": "启动和更新工作空间",
                            "steps": [
                                (
                                    "用户要求启动服务时调用 start_workspace；该操作启动当前"
                                    "工作空间全部已登记项目"
                                ),
                                (
                                    "修改已登记项目代码后，调用一次 apply_workspace_changes，"
                                    "并传 task_id 和真实的工作空间相对变更路径"
                                ),
                                (
                                    "调用 get_workspace_operation 轮询，直到 succeeded、failed、"
                                    "cancelled 或 interrupted"
                                ),
                                "不要自行拼接部署命令、容器名或端口映射",
                            ],
                        },
                        {
                            "title": "重新 prepare 的情况",
                            "rules": [
                                "进入新的会话或手中没有当前 task_id",
                                "工作空间环境或配置 revision 已改变",
                                "从文档阅读目录切换到主目录以使用数据库或部署能力",
                                "cwd 已切换到另一个工作空间",
                            ],
                        },
                    ],
                },
                "include_in_prepare": True,
                "sort_order": 20,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM system_guides WHERE guide_key = :guide_key").bindparams(
            guide_key="context-router-mcp-usage"
        )
    )
