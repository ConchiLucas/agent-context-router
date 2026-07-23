from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

import psycopg
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

from context_router.config import Settings
from context_router.mcp_server import (
    EXECUTE_DATABASE_TOOL_DESCRIPTION,
    EXECUTE_DATABASE_TOOL_NAME,
    MCP_SERVER_NAME,
    PREPARE_TOOL_DESCRIPTION,
    PREPARE_TOOL_NAME,
    READ_TOOL_DESCRIPTION,
    READ_TOOL_NAME,
    SEARCH_DATABASE_TOOL_DESCRIPTION,
    SEARCH_DATABASE_TOOL_NAME,
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
        project_count = sum(project.enabled for project in self._registry.list_projects())
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
                McpToolInfo(name=READ_TOOL_NAME, description=READ_TOOL_DESCRIPTION),
                McpToolInfo(
                    name=SEARCH_DATABASE_TOOL_NAME,
                    description=SEARCH_DATABASE_TOOL_DESCRIPTION,
                ),
                McpToolInfo(
                    name=EXECUTE_DATABASE_TOOL_NAME,
                    description=EXECUTE_DATABASE_TOOL_DESCRIPTION,
                ),
            ],
            clients=[
                McpClientConfig(
                    client="codex",
                    title="Codex",
                    config_path="~/.codex/config.toml",
                    project_config_path=".codex/config.toml",
                    config=(f'[mcp_servers.context_router]\nurl = "{public_url}"\nenabled = true'),
                ),
                McpClientConfig(
                    client="antigravity",
                    title="Antigravity",
                    config_path="~/.gemini/config/mcp_config.json",
                    project_config_path=".agents/mcp_config.json",
                    config=json.dumps(
                        {
                            "mcpServers": {
                                "context-router": {
                                    "serverUrl": public_url,
                                }
                            }
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                ),
            ],
            readiness=McpIntegrationReadiness(
                database_configured=database_configured,
                project_count=project_count,
                ready_for_full_test=database_configured and project_count > 0,
            ),
        )

    async def run_test(self, project_id: str) -> McpIntegrationTestResult:
        started_at = datetime.now(UTC)
        stages: list[McpIntegrationTestStage] = []
        project_name: str | None = None
        task_id: int | None = None
        read_call_id: int | None = None
        stage_definitions = [
            ("database", "数据库连接"),
            ("initialize", "MCP initialize"),
            ("tools", "工具发现"),
            ("project", "项目匹配"),
            ("prepare", "prepare_task_context"),
            ("read", "read_context_document"),
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
                                READ_TOOL_NAME,
                                SEARCH_DATABASE_TOOL_NAME,
                                EXECUTE_DATABASE_TOOL_NAME,
                            }
                            missing = expected.difference(names)
                            if missing:
                                raise McpIntegrationError(f"缺少工具：{', '.join(sorted(missing))}")
                            unexpected = set(names).difference(expected)
                            if unexpected:
                                raise McpIntegrationError(
                                    f"发现未约定工具：{', '.join(sorted(unexpected))}"
                                )
                            return f"发现 {len(names)} 个工具：{', '.join(names)}"

                        await add_stage("tools", "工具发现", list_tools)

                        snapshot_holder: dict[str, Any] = {}

                        async def match_project() -> str:
                            try:
                                selected = self._registry.get_snapshot(project_id)
                                matched = self._registry.find_project_for_cwd(
                                    str(Path(selected.agents_path).expanduser().parent)
                                )
                            except ProjectRegistryError as exc:
                                raise McpIntegrationError(str(exc)) from exc
                            if matched.id != selected.id:
                                raise McpIntegrationError("cwd 匹配到了其他已注册项目")
                            snapshot_holder["snapshot"] = selected
                            node_count = len(selected.cache.documents)
                            return f"已匹配项目：{selected.name}（{node_count} 个节点）"

                        await add_stage("project", "项目匹配", match_project)
                        snapshot = snapshot_holder["snapshot"]
                        project_name = snapshot.name
                        prepare_holder: dict[str, Any] = {}

                        async def prepare_context() -> str:
                            nonlocal task_id
                            result = await session.call_tool(
                                PREPARE_TOOL_NAME,
                                arguments={
                                    "task": TEST_TASK_NAME,
                                    "cwd": str(Path(snapshot.agents_path).expanduser().parent),
                                    "agent_name": TEST_AGENT_NAME,
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
                            return f"已创建测试任务 #{task_id}，并返回完整文档树"

                        await add_stage("prepare", PREPARE_TOOL_NAME, prepare_context)

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
            project_id=project_id,
            project_name=project_name,
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
