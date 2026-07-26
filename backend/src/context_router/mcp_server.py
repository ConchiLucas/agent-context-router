from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from time import perf_counter_ns
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from context_router.database.errors import DatabaseAccessError
from context_router.mcp_contract import (
    CONTEXT_ROUTER_TRACE_SERVER_NAME as TRACE_SERVER_NAME,
)
from context_router.mcp_contract import (
    CONTEXT_ROUTER_TRACE_TOOL_NAMES,
)
from context_router.schemas.context import ContextDocumentReadRequest
from context_router.services.context_document_read import (
    ContextDocumentReadError,
    ContextDocumentReadService,
)
from context_router.services.context_document_search import (
    ContextDocumentSearchError,
    ContextDocumentSearchService,
)
from context_router.services.context_preparation import (
    ContextPreparationError,
    ContextPreparationService,
)
from context_router.services.database_catalog import DatabaseCatalogService
from context_router.services.database_query import DatabaseQueryService
from context_router.services.database_tool_payload import DatabaseToolPayloadService
from context_router.services.mcp_trace import McpTraceService

MCP_SERVER_NAME = "Context Router"
MCP_SERVER_INSTRUCTIONS = (
    "Call prepare_task_context once at the start of a new workspace task. Preserve the "
    "returned task_id and pass it to every document or database call for that task. "
    "When the document tree is large or the target is uncertain, call "
    "search_context_documents and then read the selected document or section with "
    "read_context_document. "
    "Use only database aliases returned by prepare. Search database objects before querying "
    "when the schema is uncertain. Database queries are always bounded and read-only. Call "
    "prepare again for a new conversation when no task_id is available."
)
(
    PREPARE_TOOL_NAME,
    SEARCH_CONTEXT_TOOL_NAME,
    READ_TOOL_NAME,
    SEARCH_DATABASE_TOOL_NAME,
    EXECUTE_DATABASE_TOOL_NAME,
) = CONTEXT_ROUTER_TRACE_TOOL_NAMES
PREPARE_TOOL_DESCRIPTION = (
    "Locate the registered workspace for cwd, create a server-side task number, and "
    "return its explicit workspace document tree or synthetic project-root tree. Project "
    "documents outside an explicit root remain available through search_context_documents. "
    "Summaries are only returned when explicitly declared in Markdown Front Matter."
)
READ_TOOL_DESCRIPTION = (
    "Read one or more Markdown documents or exact ATX-heading sections from the workspace "
    "selected by prepare_task_context. task_id must be the value returned for the current "
    "task. Results preserve request order and every call is recorded server-side."
)
SEARCH_CONTEXT_TOOL_DESCRIPTION = (
    "Search every mapped Markdown document in the workspace selected by prepare_task_context. "
    "Returns document metadata, matching sections, relevance, and deterministic match reasons "
    "without returning Markdown content. Use read_context_document for selected results."
)
SEARCH_DATABASE_TOOL_DESCRIPTION = (
    "Search schemas, tables, views, columns, or indexes in a database authorized for the "
    "current task. Use names first and request summary/full details only when needed."
)
EXECUTE_DATABASE_TOOL_DESCRIPTION = (
    "Execute exactly one bounded read-only SQL statement against a database alias returned "
    "by prepare_task_context. Connection details and query limits are enforced server-side."
)
PREPARE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
READ_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
DATABASE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


class ContextRouterMCP(FastMCP):
    def __init__(
        self,
        *args: object,
        trace_service: McpTraceService | None = None,
        database_payload_service: DatabaseToolPayloadService | None = None,
        **kwargs: object,
    ):
        self._trace_service = trace_service
        self._database_payload_service = database_payload_service
        super().__init__(*args, **kwargs)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        trace_service = self._trace_service
        if trace_service is None:
            return await super().call_tool(name, arguments)

        started_at = datetime.now(UTC)
        started_ns = perf_counter_ns()
        request_summary = _request_summary(name, arguments)
        if name == PREPARE_TOOL_NAME:
            try:
                result = await super().call_tool(name, arguments)
            except Exception as exc:
                task_id = _exception_task_id(exc)
                if task_id is not None:
                    trace_service.record_failed_call(
                        task_id=task_id,
                        server_name=TRACE_SERVER_NAME,
                        tool_name=name,
                        started_at=started_at,
                        finished_at=datetime.now(UTC),
                        duration_ms=_elapsed_ms(started_ns),
                        request_summary=request_summary,
                        error_code=_error_code(exc),
                    )
                raise
            payload = _structured_payload(result)
            task_id = _positive_int(payload.get("task_id"))
            if task_id is not None:
                finished_at = datetime.now(UTC)
                trace_service.record_completed_call(
                    task_id=task_id,
                    server_name=TRACE_SERVER_NAME,
                    tool_name=name,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=_elapsed_ms(started_ns),
                    request_summary=request_summary,
                    result_summary=_result_summary(name, payload),
                )
            return result

        task_id = _positive_int(arguments.get("task_id"))
        tool_call_id = (
            trace_service.start_call(
                task_id=task_id,
                server_name=TRACE_SERVER_NAME,
                tool_name=name,
                started_at=started_at,
                request_summary=request_summary,
            )
            if task_id is not None
            else None
        )
        token = trace_service.bind_call(tool_call_id)
        payload_service = self._database_payload_service
        if payload_service is not None:
            payload_service.capture_request(
                tool_call_id,
                tool_name=name,
                arguments=arguments,
            )
        try:
            result = await super().call_tool(name, arguments)
        except asyncio.CancelledError:
            if payload_service is not None:
                payload_service.capture_response(
                    tool_call_id,
                    tool_name=name,
                    status="cancelled",
                    payload={
                        "error": {
                            "code": "tool_call_cancelled",
                            "message": "MCP 工具调用已取消",
                        }
                    },
                )
            trace_service.finish_call(
                tool_call_id,
                status="cancelled",
                finished_at=datetime.now(UTC),
                duration_ms=_elapsed_ms(started_ns),
            )
            raise
        except Exception as exc:
            error_code = _error_code(exc)
            if payload_service is not None:
                payload_service.capture_response(
                    tool_call_id,
                    tool_name=name,
                    status="error",
                    payload={
                        "error": {
                            "code": error_code,
                            "message": _database_payload_error_message(name, error_code),
                        }
                    },
                )
            trace_service.finish_call(
                tool_call_id,
                status="error",
                finished_at=datetime.now(UTC),
                duration_ms=_elapsed_ms(started_ns),
                error_code=error_code,
            )
            raise
        else:
            payload = _structured_payload(result)
            if bool(getattr(result, "isError", False)):
                if payload_service is not None:
                    payload_service.capture_response(
                        tool_call_id,
                        tool_name=name,
                        status="error",
                        payload=payload
                        or {
                            "error": {
                                "code": "tool_error_result",
                                "message": "MCP 工具返回错误结果",
                            }
                        },
                    )
                trace_service.finish_call(
                    tool_call_id,
                    status="error",
                    finished_at=datetime.now(UTC),
                    duration_ms=_elapsed_ms(started_ns),
                    error_code="tool_error_result",
                )
            else:
                if payload_service is not None:
                    payload_service.capture_response(
                        tool_call_id,
                        tool_name=name,
                        status="ok",
                        payload=payload,
                    )
                trace_service.finish_call(
                    tool_call_id,
                    status="ok",
                    finished_at=datetime.now(UTC),
                    duration_ms=_elapsed_ms(started_ns),
                    result_summary=_result_summary(name, payload),
                )
            return result
        finally:
            trace_service.reset_call(token)


def create_context_router_mcp(
    preparation_service: ContextPreparationService,
    document_read_service: ContextDocumentReadService,
    database_catalog_service: DatabaseCatalogService | None = None,
    database_query_service: DatabaseQueryService | None = None,
    trace_service: McpTraceService | None = None,
    database_payload_service: DatabaseToolPayloadService | None = None,
    document_search_service: ContextDocumentSearchService | None = None,
) -> FastMCP:
    server = ContextRouterMCP(
        name=MCP_SERVER_NAME,
        instructions=MCP_SERVER_INSTRUCTIONS,
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        trace_service=trace_service,
        database_payload_service=database_payload_service,
    )

    @server.tool(
        name=PREPARE_TOOL_NAME,
        description=PREPARE_TOOL_DESCRIPTION,
        annotations=PREPARE_TOOL_ANNOTATIONS,
    )
    def prepare_task_context(
        task: Annotated[str, Field(min_length=1, max_length=4000)],
        cwd: Annotated[str, Field(min_length=1)],
        agent_name: Annotated[str | None, Field(max_length=64)] = None,
    ) -> dict[str, Any]:
        try:
            result = preparation_service.prepare(task=task, cwd=cwd, agent_name=agent_name)
        except ContextPreparationError as exc:
            raise ToolError(str(exc)) from exc
        return result.model_dump(exclude_none=True)

    @server.tool(
        name=SEARCH_CONTEXT_TOOL_NAME,
        description=SEARCH_CONTEXT_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def search_context_documents(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        query: Annotated[str, Field(min_length=1, max_length=200)],
        limit: Annotated[int, Field(ge=1, le=50, strict=True)] = 10,
    ) -> dict[str, Any]:
        if document_search_service is None:
            raise ToolError("document_search_disabled: 文档搜索当前不可用")
        try:
            result = document_search_service.search(
                task_id=task_id,
                query=query,
                limit=limit,
            )
        except ContextDocumentSearchError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        return result.model_dump(exclude_none=True)

    @server.tool(
        name=READ_TOOL_NAME,
        description=READ_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def read_context_document(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        requests: Annotated[
            list[ContextDocumentReadRequest],
            Field(min_length=1, max_length=10),
        ],
    ) -> dict[str, Any]:
        try:
            result = document_read_service.read(task_id=task_id, requests=requests)
        except ContextDocumentReadError as exc:
            raise ToolError(str(exc)) from exc
        return result.model_dump(exclude_none=True)

    @server.tool(
        name=SEARCH_DATABASE_TOOL_NAME,
        description=SEARCH_DATABASE_TOOL_DESCRIPTION,
        annotations=DATABASE_TOOL_ANNOTATIONS,
    )
    def search_database_objects(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        database: Annotated[
            str,
            Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"),
        ],
        object_type: Literal["schema", "table", "view", "column", "index"],
        pattern: Annotated[str, Field(min_length=1, max_length=255)] = "*",
        detail: Literal["names", "summary", "full"] = "names",
        schema: Annotated[str | None, Field(max_length=255)] = None,
        table: Annotated[str | None, Field(max_length=255)] = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> dict[str, object]:
        if database_catalog_service is None:
            raise ToolError("database_tools_disabled: 数据库工具当前不可用")
        try:
            return database_catalog_service.search(
                task_id=task_id,
                database=database,
                object_type=object_type,
                pattern=pattern,
                detail=detail,
                schema=schema,
                table=table,
                limit=limit,
            )
        except DatabaseAccessError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=EXECUTE_DATABASE_TOOL_NAME,
        description=EXECUTE_DATABASE_TOOL_DESCRIPTION,
        annotations=DATABASE_TOOL_ANNOTATIONS,
    )
    def execute_database_query(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        database: Annotated[
            str,
            Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"),
        ],
        sql: Annotated[str, Field(min_length=1, max_length=200_000)],
    ) -> dict[str, object]:
        if database_query_service is None:
            raise ToolError("database_tools_disabled: 数据库工具当前不可用")
        try:
            return database_query_service.execute(task_id=task_id, database=database, sql=sql)
        except DatabaseAccessError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    return server


def _elapsed_ms(started_ns: int) -> int:
    return max(0, (perf_counter_ns() - started_ns) // 1_000_000)


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _structured_payload(result: object) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[1], dict):
        return result[1]
    for attribute in ("structuredContent", "structured_content"):
        value = getattr(result, attribute, None)
        if isinstance(value, dict):
            return value
    return {}


def _request_summary(name: str, arguments: dict[str, Any]) -> dict[str, object] | None:
    if name == PREPARE_TOOL_NAME:
        task = arguments.get("task")
        agent_name = arguments.get("agent_name")
        return {
            "task_characters": len(task) if isinstance(task, str) else 0,
            "agent_name": agent_name if isinstance(agent_name, str) else None,
        }
    if name == READ_TOOL_NAME:
        requests = arguments.get("requests")
        if not isinstance(requests, list):
            return {"request_count": 0}
        return {
            "request_count": len(requests),
            "section_count": sum(
                isinstance(item, dict) and isinstance(item.get("section"), str) for item in requests
            ),
        }
    if name == SEARCH_CONTEXT_TOOL_NAME:
        query = arguments.get("query")
        return {
            "query_characters": len(query) if isinstance(query, str) else 0,
            "query_sha256": (
                hashlib.sha256(query.strip().encode("utf-8")).hexdigest()
                if isinstance(query, str)
                else None
            ),
            "limit": arguments.get("limit") if isinstance(arguments.get("limit"), int) else None,
        }
    if name == SEARCH_DATABASE_TOOL_NAME:
        return {
            "database": _safe_string(arguments.get("database"), 64),
            "object_type": _safe_string(arguments.get("object_type"), 32),
            "detail": _safe_string(arguments.get("detail"), 16),
            "limit": arguments.get("limit") if isinstance(arguments.get("limit"), int) else None,
            "schema_scoped": bool(arguments.get("schema")),
            "table_scoped": bool(arguments.get("table")),
        }
    if name == EXECUTE_DATABASE_TOOL_NAME:
        sql = arguments.get("sql")
        return {
            "database": _safe_string(arguments.get("database"), 64),
            "sql_sha256": (
                hashlib.sha256(sql.strip().encode("utf-8")).hexdigest()
                if isinstance(sql, str)
                else None
            ),
        }
    return None


def _result_summary(name: str, payload: dict[str, Any]) -> dict[str, object] | None:
    if name == PREPARE_TOOL_NAME:
        project = payload.get("project")
        return {
            "document_count": (project.get("node_count") if isinstance(project, dict) else None),
            "database_count": len(payload.get("databases", []))
            if isinstance(payload.get("databases"), list)
            else 0,
            "warning_count": len(payload.get("warnings", []))
            if isinstance(payload.get("warnings"), list)
            else 0,
        }
    if name == READ_TOOL_NAME:
        documents = payload.get("documents")
        if not isinstance(documents, list):
            return {"document_count": 0}
        return {
            "document_count": len(documents),
            "ok_count": sum(
                isinstance(document, dict) and document.get("error") is None
                for document in documents
            ),
            "error_count": sum(
                isinstance(document, dict) and document.get("error") is not None
                for document in documents
            ),
            "content_characters": sum(
                len(document.get("content", ""))
                for document in documents
                if isinstance(document, dict) and isinstance(document.get("content"), str)
            ),
        }
    if name == SEARCH_CONTEXT_TOOL_NAME:
        results = payload.get("results")
        relevance = (
            [
                item.get("relevance")
                for item in results
                if isinstance(item, dict) and isinstance(item.get("relevance"), int | float)
            ]
            if isinstance(results, list)
            else []
        )
        return {
            "returned_count": (
                payload.get("returned_count")
                if isinstance(payload.get("returned_count"), int)
                else 0
            ),
            "truncated": (
                payload.get("truncated") if isinstance(payload.get("truncated"), bool) else False
            ),
            "max_relevance": max(relevance) if relevance else None,
        }
    if name == SEARCH_DATABASE_TOOL_NAME:
        return _bounded_result_metadata(payload, count_key="returned_count")
    if name == EXECUTE_DATABASE_TOOL_NAME:
        return _bounded_result_metadata(payload, count_key="returned_rows")
    return None


def _bounded_result_metadata(
    payload: dict[str, Any],
    *,
    count_key: str,
) -> dict[str, object]:
    return {
        count_key: payload.get(count_key) if isinstance(payload.get(count_key), int) else None,
        "result_bytes": (
            payload.get("result_bytes") if isinstance(payload.get("result_bytes"), int) else None
        ),
        "truncated": (
            payload.get("truncated") if isinstance(payload.get("truncated"), bool) else None
        ),
    }


def _safe_string(value: object, max_length: int) -> str | None:
    return value[:max_length] if isinstance(value, str) else None


def _error_code(exc: Exception) -> str:
    current: BaseException | None = exc
    while current is not None:
        code = getattr(current, "code", None)
        if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,64}", code):
            return code
        current = current.__cause__ or current.__context__
    prefix = str(exc).partition(":")[0].strip()
    if re.fullmatch(r"[a-z0-9_]{1,64}", prefix):
        return prefix
    return "tool_call_failed"


def _database_payload_error_message(tool_name: str, error_code: str) -> str:
    if tool_name == SEARCH_DATABASE_TOOL_NAME:
        return {
            "connection_failed": "数据库当前无法连接",
            "catalog_query_failed": "数据库对象搜索失败",
            "query_rejected": "数据库对象搜索超出项目授权范围",
            "result_metadata_too_large": "数据库对象结果超过响应限制",
            "result_cell_too_large": "数据库对象字段超过响应限制",
            "engine_not_supported": "这个数据库类型不支持所请求的对象搜索",
        }.get(error_code, "数据库对象搜索失败")
    return {
        "query_rejected": "SQL 不符合当前项目的只读或数据库范围策略",
        "query_timeout": "数据库查询超时",
        "query_cancelled": "数据库查询已取消",
        "connection_failed": "数据库当前无法连接",
        "result_cell_too_large": "单个查询结果字段超过响应限制",
        "result_metadata_too_large": "查询列信息超过响应限制",
        "engine_not_supported": "这个数据库类型暂不支持只读查询",
    }.get(error_code, "数据库查询执行失败")


def _exception_task_id(exc: Exception) -> int | None:
    current: BaseException | None = exc
    while current is not None:
        task_id = _positive_int(getattr(current, "task_id", None))
        if task_id is not None:
            return task_id
        current = current.__cause__ or current.__context__
    return None
