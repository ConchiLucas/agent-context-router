from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

import psycopg
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

from context_router.config import Settings
from context_router.mcp_server import (
    APPLY_WORKSPACE_TOOL_DESCRIPTION,
    APPLY_WORKSPACE_TOOL_NAME,
    DISCOVER_TASK_TOOLS_TOOL_DESCRIPTION,
    DISCOVER_TASK_TOOLS_TOOL_NAME,
    EXECUTE_DATABASE_TOOL_DESCRIPTION,
    EXECUTE_DATABASE_TOOL_NAME,
    EXECUTE_FORWARDING_REQUEST_TOOL_DESCRIPTION,
    EXECUTE_FORWARDING_REQUEST_TOOL_NAME,
    EXECUTE_MAPPED_DATA_QUERY_TOOL_DESCRIPTION,
    EXECUTE_MAPPED_DATA_QUERY_TOOL_NAME,
    GET_WORKSPACE_OPERATION_TOOL_DESCRIPTION,
    GET_WORKSPACE_OPERATION_TOOL_NAME,
    INSPECT_CONTAINER_ERRORS_TOOL_DESCRIPTION,
    INSPECT_CONTAINER_ERRORS_TOOL_NAME,
    INVOKE_TASK_TOOL_DESCRIPTION,
    INVOKE_TASK_TOOL_NAME,
    LIST_TASK_CONTAINERS_TOOL_DESCRIPTION,
    LIST_TASK_CONTAINERS_TOOL_NAME,
    MCP_SERVER_NAME,
    PREPARE_FORWARDING_REQUEST_TOOL_DESCRIPTION,
    PREPARE_FORWARDING_REQUEST_TOOL_NAME,
    PREPARE_TOOL_DESCRIPTION,
    PREPARE_TOOL_NAME,
    READ_FORWARDING_REQUEST_HISTORY_TOOL_DESCRIPTION,
    READ_FORWARDING_REQUEST_HISTORY_TOOL_NAME,
    READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION,
    READ_MIDDLEWARE_CONTEXT_TOOL_NAME,
    READ_TABLE_RELATIONS_TOOL_DESCRIPTION,
    READ_TABLE_RELATIONS_TOOL_NAME,
    READ_TASK_CONTEXT_TOOL_DESCRIPTION,
    READ_TASK_CONTEXT_TOOL_NAME,
    READ_TOOL_DESCRIPTION,
    READ_TOOL_NAME,
    RESOLVE_DATABASE_TARGET_TOOL_DESCRIPTION,
    RESOLVE_DATABASE_TARGET_TOOL_NAME,
    RESOLVE_VALUE_CANDIDATES_TOOL_DESCRIPTION,
    RESOLVE_VALUE_CANDIDATES_TOOL_NAME,
    SAVE_DATA_VISUALIZATION_QUERY_TOOL_DESCRIPTION,
    SAVE_DATA_VISUALIZATION_QUERY_TOOL_NAME,
    SAVE_TASK_VISUALIZATION_RESULT_TOOL_DESCRIPTION,
    SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME,
    SEARCH_CONTEXT_TOOL_DESCRIPTION,
    SEARCH_CONTEXT_TOOL_NAME,
    SEARCH_DATABASE_TOOL_DESCRIPTION,
    SEARCH_DATABASE_TOOL_NAME,
    SEARCH_FORWARDING_INTERFACES_TOOL_DESCRIPTION,
    SEARCH_FORWARDING_INTERFACES_TOOL_NAME,
    SEARCH_RELATION_TABLES_TOOL_DESCRIPTION,
    SEARCH_RELATION_TABLES_TOOL_NAME,
    SEARCH_VALUE_MAPPINGS_TOOL_DESCRIPTION,
    SEARCH_VALUE_MAPPINGS_TOOL_NAME,
    START_WORKSPACE_TOOL_DESCRIPTION,
    START_WORKSPACE_TOOL_NAME,
)
from context_router.schemas.mcp_integration import (
    McpClientConfig,
    McpIntegrationInfo,
    McpIntegrationReadiness,
    McpIntegrationTestResult,
    McpIntegrationTestStage,
    McpServiceInfo,
    McpToolInfo,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

TEST_AGENT_NAME = "connection-test"
TEST_TASK_NAME = "验证 MCP 接入"

StageAction = Callable[[], Coroutine[Any, Any, str]]


class McpIntegrationError(ValueError):
    pass


class McpIntegrationService:
    def __init__(self, settings: Settings, registry: ProjectRegistry) -> None:
        self._settings = settings
        self._registry = registry

    def get_info(self) -> McpIntegrationInfo:
        public_url = self._settings.public_mcp_url.rstrip("/")
        workspace_count = len(self._registry.list_workspace_ids())
        database_configured = bool(
            self._settings.database_url and self._settings.database_url.strip()
        )
        return McpIntegrationInfo(
            service=McpServiceInfo(
                name=MCP_SERVER_NAME,
                transport="Streamable HTTP",
                url=public_url,
            ),
            tools=[
                McpToolInfo(name=PREPARE_TOOL_NAME, description=PREPARE_TOOL_DESCRIPTION),
                McpToolInfo(
                    name=READ_TASK_CONTEXT_TOOL_NAME,
                    description=READ_TASK_CONTEXT_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=READ_MIDDLEWARE_CONTEXT_TOOL_NAME,
                    description=READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=SEARCH_CONTEXT_TOOL_NAME,
                    description=SEARCH_CONTEXT_TOOL_DESCRIPTION,
                ),
                McpToolInfo(name=READ_TOOL_NAME, description=READ_TOOL_DESCRIPTION),
                McpToolInfo(
                    name=RESOLVE_DATABASE_TARGET_TOOL_NAME,
                    description=RESOLVE_DATABASE_TARGET_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=SEARCH_DATABASE_TOOL_NAME,
                    description=SEARCH_DATABASE_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=EXECUTE_DATABASE_TOOL_NAME,
                    description=EXECUTE_DATABASE_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=SAVE_DATA_VISUALIZATION_QUERY_TOOL_NAME,
                    description=SAVE_DATA_VISUALIZATION_QUERY_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME,
                    description=SAVE_TASK_VISUALIZATION_RESULT_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=LIST_TASK_CONTAINERS_TOOL_NAME,
                    description=LIST_TASK_CONTAINERS_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=INSPECT_CONTAINER_ERRORS_TOOL_NAME,
                    description=INSPECT_CONTAINER_ERRORS_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=READ_TABLE_RELATIONS_TOOL_NAME,
                    description=READ_TABLE_RELATIONS_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=SEARCH_RELATION_TABLES_TOOL_NAME,
                    description=SEARCH_RELATION_TABLES_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=SEARCH_VALUE_MAPPINGS_TOOL_NAME,
                    description=SEARCH_VALUE_MAPPINGS_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=RESOLVE_VALUE_CANDIDATES_TOOL_NAME,
                    description=RESOLVE_VALUE_CANDIDATES_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=EXECUTE_MAPPED_DATA_QUERY_TOOL_NAME,
                    description=EXECUTE_MAPPED_DATA_QUERY_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=SEARCH_FORWARDING_INTERFACES_TOOL_NAME,
                    description=SEARCH_FORWARDING_INTERFACES_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=READ_FORWARDING_REQUEST_HISTORY_TOOL_NAME,
                    description=READ_FORWARDING_REQUEST_HISTORY_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=PREPARE_FORWARDING_REQUEST_TOOL_NAME,
                    description=PREPARE_FORWARDING_REQUEST_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=EXECUTE_FORWARDING_REQUEST_TOOL_NAME,
                    description=EXECUTE_FORWARDING_REQUEST_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=DISCOVER_TASK_TOOLS_TOOL_NAME,
                    description=DISCOVER_TASK_TOOLS_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=INVOKE_TASK_TOOL_NAME,
                    description=INVOKE_TASK_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=APPLY_WORKSPACE_TOOL_NAME,
                    description=APPLY_WORKSPACE_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=START_WORKSPACE_TOOL_NAME,
                    description=START_WORKSPACE_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=GET_WORKSPACE_OPERATION_TOOL_NAME,
                    description=GET_WORKSPACE_OPERATION_TOOL_DESCRIPTION,
                ),
            ],
            clients=[
                McpClientConfig(
                    client="codex",
                    title="Codex",
                    config_path="~/.codex/config.toml",
                    project_config_path=".codex/config.toml",
                    config=(
                        f'[mcp_servers.context_router]\nurl = "{public_url}"\n'
                        'http_headers = { "X-Agent-Name" = "codex" }\n'
                        "enabled = true"
                    ),
                ),
                McpClientConfig(
                    client="gemini",
                    title="Gemini CLI",
                    config_path="~/.gemini/settings.json",
                    project_config_path=".gemini/settings.json",
                    config=json.dumps(
                        {
                            "mcpServers": {
                                "context-router": {
                                    "httpUrl": public_url,
                                    "headers": {"X-Agent-Name": "gemini"},
                                }
                            }
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                ),
                McpClientConfig(
                    client="antigravity",
                    title="Antigravity CLI",
                    config_path="agy mcp list",
                    setup_kind="command",
                    config=(
                        "agy mcp add --type http "
                        '--header "X-Agent-Name: antigravity" '
                        f'context_router "{public_url}"'
                    ),
                ),
                McpClientConfig(
                    client="cursor",
                    title="Cursor Agent",
                    config_path="~/.cursor/mcp.json",
                    project_config_path=".cursor/mcp.json",
                    config=json.dumps(
                        {
                            "mcpServers": {
                                "context_router": {
                                    "url": public_url,
                                    "headers": {"X-Agent-Name": "cursor"},
                                }
                            }
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                ),
                McpClientConfig(
                    client="grok",
                    title="Grok CLI",
                    config_path="~/.grok/config.toml",
                    project_config_path=".grok/config.toml",
                    setup_kind="command",
                    config=(
                        "grok mcp add --transport http --scope user "
                        '--header "X-Agent-Name: grok" '
                        f'context_router "{public_url}"'
                    ),
                ),
            ],
            readiness=McpIntegrationReadiness(
                database_configured=database_configured,
                workspace_count=workspace_count,
                ready_for_full_test=database_configured and workspace_count > 0,
            ),
        )

    async def run_test(self, workspace_id: str) -> McpIntegrationTestResult:
        started_at = datetime.now(UTC)
        stages: list[McpIntegrationTestStage] = []
        workspace_name: str | None = None
        task_id: int | None = None
        read_call_id: int | None = None
        stage_definitions = [
            ("database", "数据库连接"),
            ("initialize", "MCP initialize"),
            ("tools", "工具发现"),
            ("workspace", "工作空间匹配"),
            ("prepare", "prepare_task_context"),
            ("search", "search_context_documents"),
            ("read", "read_context_document"),
            ("discover", "discover_task_tools"),
            ("invoke", "invoke_task_tool"),
        ]

        async def add_stage(key: str, label: str, action: StageAction) -> str:
            stage_started = perf_counter()
            try:
                detail = await action()
            except Exception as exc:
                stages.append(
                    McpIntegrationTestStage(
                        key=key,
                        label=label,
                        status="failed",
                        detail=self._safe_error(exc),
                        duration_ms=self._duration_ms(stage_started),
                    )
                )
                raise
            stages.append(
                McpIntegrationTestStage(
                    key=key,
                    label=label,
                    status="passed",
                    detail=detail,
                    duration_ms=self._duration_ms(stage_started),
                )
            )
            return detail

        try:
            await add_stage("database", "数据库连接", self._check_database)

            timeout = self._settings.mcp_test_timeout_seconds
            async with asyncio.timeout(timeout):
                async with streamable_http_client(self._settings.internal_mcp_url.rstrip("/")) as (
                    read_stream,
                    write_stream,
                    _,
                ):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(seconds=timeout),
                    ) as session:

                        async def initialize() -> str:
                            result = await session.initialize()
                            return f"{result.serverInfo.name} · protocol {result.protocolVersion}"

                        await add_stage("initialize", "MCP initialize", initialize)

                        async def list_tools() -> str:
                            result = await session.list_tools()
                            names = [tool.name for tool in result.tools]
                            expected = {
                                PREPARE_TOOL_NAME,
                                READ_TASK_CONTEXT_TOOL_NAME,
                                READ_MIDDLEWARE_CONTEXT_TOOL_NAME,
                                SEARCH_CONTEXT_TOOL_NAME,
                                READ_TOOL_NAME,
                                RESOLVE_DATABASE_TARGET_TOOL_NAME,
                                SEARCH_DATABASE_TOOL_NAME,
                                EXECUTE_DATABASE_TOOL_NAME,
                                EXECUTE_MAPPED_DATA_QUERY_TOOL_NAME,
                                SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME,
                                SEARCH_VALUE_MAPPINGS_TOOL_NAME,
                                RESOLVE_VALUE_CANDIDATES_TOOL_NAME,
                                APPLY_WORKSPACE_TOOL_NAME,
                                START_WORKSPACE_TOOL_NAME,
                                GET_WORKSPACE_OPERATION_TOOL_NAME,
                            }
                            missing = expected.difference(names)
                            if missing:
                                raise McpIntegrationError(f"缺少工具：{', '.join(sorted(missing))}")
                            return f"发现 {len(names)} 个工具：{', '.join(names)}"

                        await add_stage("tools", "工具发现", list_tools)

                        snapshot_holder: dict[str, Any] = {}

                        async def match_workspace() -> str:
                            try:
                                selected = self._registry.get_workspace_snapshot(workspace_id)
                                matched = self._registry.find_workspace_for_cwd(selected.root_path)
                            except ProjectRegistryError as exc:
                                raise McpIntegrationError(str(exc)) from exc
                            if matched.id != selected.id:
                                raise McpIntegrationError("cwd 匹配到了其他已注册工作空间")
                            snapshot_holder["snapshot"] = selected
                            node_count = len(selected.cache.documents)
                            return f"已匹配工作空间：{selected.name}（{node_count} 个节点）"

                        await add_stage("workspace", "工作空间匹配", match_workspace)
                        snapshot = snapshot_holder["snapshot"]
                        workspace_name = snapshot.name
                        prepare_holder: dict[str, Any] = {}

                        async def prepare_context() -> str:
                            nonlocal task_id
                            result = await session.call_tool(
                                PREPARE_TOOL_NAME,
                                arguments={
                                    "task": TEST_TASK_NAME,
                                    "cwd": snapshot.root_path,
                                    "agent_name": TEST_AGENT_NAME,
                                    "intent_type": "code_change",
                                    "capability_hints": ["context"],
                                },
                            )
                            payload = self._tool_payload(result)
                            task_id = self._positive_int(payload.get("task_id"), "task_id")
                            documents = payload.get("documents")
                            if not isinstance(documents, dict):
                                raise McpIntegrationError("prepare 未返回文档树")
                            root_document_id = documents.get("document_id")
                            if not isinstance(root_document_id, str) or not root_document_id:
                                raise McpIntegrationError("prepare 未返回入口 document_id")
                            prepare_holder["root_document_id"] = root_document_id
                            return f"已创建测试任务 #{task_id}，并返回工作空间文档导航树"

                        await add_stage("prepare", PREPARE_TOOL_NAME, prepare_context)

                        async def search_documents() -> str:
                            result = await session.call_tool(
                                SEARCH_CONTEXT_TOOL_NAME,
                                arguments={
                                    "task_id": task_id,
                                    "query": "AGENTS.md",
                                    "limit": 1,
                                },
                            )
                            payload = self._tool_payload(result)
                            results = payload.get("results")
                            if not isinstance(results, list) or not results:
                                raise McpIntegrationError("search 未返回入口文档")
                            first = results[0]
                            if not isinstance(first, dict) or not first.get("document_id"):
                                raise McpIntegrationError("search 返回的文档格式不正确")
                            if "content" in first:
                                raise McpIntegrationError("search 不应返回 Markdown 正文")
                            return "按路径检索入口文档成功"

                        await add_stage(
                            "search",
                            SEARCH_CONTEXT_TOOL_NAME,
                            search_documents,
                        )

                        async def read_document() -> str:
                            nonlocal read_call_id
                            result = await session.call_tool(
                                READ_TOOL_NAME,
                                arguments={
                                    "task_id": task_id,
                                    "requests": [
                                        {
                                            "document_id": prepare_holder["root_document_id"],
                                        }
                                    ],
                                },
                            )
                            payload = self._tool_payload(result)
                            read_call_id = self._positive_int(
                                payload.get("read_call_id"), "read_call_id"
                            )
                            documents = payload.get("documents")
                            if not isinstance(documents, list) or not documents:
                                raise McpIntegrationError("read 未返回文档")
                            first = documents[0]
                            if not isinstance(first, dict) or first.get("error") is not None:
                                raise McpIntegrationError("入口文档读取失败")
                            content = first.get("content")
                            if not isinstance(content, str):
                                raise McpIntegrationError("read 未返回 Markdown 正文")
                            character_count = len(content)
                            return (
                                f"读取入口文档成功（{character_count} 个字符），"
                                f"调用 #{read_call_id}"
                            )

                        await add_stage("read", READ_TOOL_NAME, read_document)

                        action_holder: dict[str, Any] = {}

                        async def discover_professional_action() -> str:
                            result = await session.call_tool(
                                DISCOVER_TASK_TOOLS_TOOL_NAME,
                                arguments={
                                    "task_id": task_id,
                                    "query": "read_task_context 读取任务数据库摘要",
                                    "capability_hints": ["database"],
                                    "limit": 5,
                                },
                            )
                            payload = self._tool_payload(result)
                            actions = payload.get("actions")
                            if not isinstance(actions, list):
                                raise McpIntegrationError("discover 未返回专业动作列表")
                            action = next(
                                (
                                    item
                                    for item in actions
                                    if isinstance(item, dict)
                                    and item.get("name") == READ_TASK_CONTEXT_TOOL_NAME
                                ),
                                None,
                            )
                            if action is None:
                                raise McpIntegrationError(
                                    "discover 未命中 read_task_context 专业动作"
                                )
                            revision = action.get("definition_revision")
                            if not isinstance(revision, str) or len(revision) != 64:
                                raise McpIntegrationError("discover 未返回有效 definition_revision")
                            action_holder["definition_revision"] = revision
                            return "已发现 read_task_context，并取得不可变工具定义版本"

                        await add_stage(
                            "discover",
                            DISCOVER_TASK_TOOLS_TOOL_NAME,
                            discover_professional_action,
                        )

                        async def invoke_professional_action() -> str:
                            result = await session.call_tool(
                                INVOKE_TASK_TOOL_NAME,
                                arguments={
                                    "task_id": task_id,
                                    "tool_name": READ_TASK_CONTEXT_TOOL_NAME,
                                    "arguments": {"sections": ["databases"]},
                                    "definition_revision": action_holder[
                                        "definition_revision"
                                    ],
                                },
                            )
                            payload = self._tool_payload(result)
                            if payload.get("status") != "succeeded":
                                raise McpIntegrationError("invoke 未成功执行专业动作")
                            if payload.get("tool_name") != READ_TASK_CONTEXT_TOOL_NAME:
                                raise McpIntegrationError("invoke 返回了错误的专业动作名称")
                            action_result = payload.get("result")
                            if not isinstance(action_result, dict):
                                raise McpIntegrationError("invoke 未返回专业动作结果")
                            databases = action_result.get("databases", [])
                            if not isinstance(databases, list):
                                raise McpIntegrationError("read_task_context 数据库摘要格式错误")
                            return f"统一入口执行成功（{len(databases)} 个数据库摘要）"

                        await add_stage(
                            "invoke",
                            INVOKE_TASK_TOOL_NAME,
                            invoke_professional_action,
                        )
        except Exception as exc:
            completed_keys = {stage.key for stage in stages}
            if not any(stage.status == "failed" for stage in stages):
                for key, label in stage_definitions:
                    if key not in completed_keys:
                        stages.append(
                            McpIntegrationTestStage(
                                key=key,
                                label=label,
                                status="failed",
                                detail=self._safe_error(exc),
                                duration_ms=0,
                            )
                        )
                        completed_keys.add(key)
                        break
            for key, label in stage_definitions:
                if key not in completed_keys:
                    stages.append(
                        McpIntegrationTestStage(
                            key=key,
                            label=label,
                            status="skipped",
                            detail="因前置检查失败而跳过",
                            duration_ms=0,
                        )
                    )

        finished_at = datetime.now(UTC)
        passed = bool(stages) and all(stage.status == "passed" for stage in stages)
        return McpIntegrationTestResult(
            status="passed" if passed else "failed",
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            task_id=task_id,
            read_call_id=read_call_id,
            started_at=started_at,
            finished_at=finished_at,
            stages=stages,
        )

    async def _check_database(self) -> str:
        database_url = self._settings.database_url
        if not database_url or not database_url.strip():
            raise McpIntegrationError("任务数据库尚未配置")

        def query() -> None:
            try:
                with psycopg.connect(
                    database_url,
                    connect_timeout=max(1, int(self._settings.mcp_test_timeout_seconds)),
                ) as connection:
                    connection.execute("SELECT 1").fetchone()
            except psycopg.Error as exc:
                raise McpIntegrationError("PostgreSQL 连接失败") from exc

        await asyncio.to_thread(query)
        return "PostgreSQL 连接正常"

    @staticmethod
    def _tool_payload(result: CallToolResult) -> dict[str, Any]:
        if result.isError:
            messages = [
                content.text
                for content in result.content
                if getattr(content, "type", None) == "text"
            ]
            raise McpIntegrationError("；".join(messages) or "MCP 工具调用失败")
        if result.structuredContent is not None:
            return result.structuredContent
        for content in result.content:
            if getattr(content, "type", None) != "text":
                continue
            try:
                payload = json.loads(content.text)
            except (json.JSONDecodeError, AttributeError):
                continue
            if isinstance(payload, dict):
                return payload
        raise McpIntegrationError("MCP 工具没有返回可解析的 JSON")

    @staticmethod
    def _positive_int(value: object, field: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise McpIntegrationError(f"MCP 返回的 {field} 无效")
        return value

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, round((perf_counter() - started) * 1000))

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, (McpIntegrationError, TimeoutError)):
            return str(exc) or "连接测试超时"
        return "连接测试失败，请查看后端日志"
