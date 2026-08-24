from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from time import perf_counter_ns
from typing import Annotated, Any, Literal

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from context_router.database.errors import DatabaseAccessError
from context_router.mcp_contract import (
    CONTEXT_ROUTER_CORE_TOOL_NAMES,
    CONTEXT_ROUTER_DATA_VISUALIZATION_TOOL_NAMES,
    CONTEXT_ROUTER_INTERFACE_FORWARDING_TOOL_NAMES,
    CONTEXT_ROUTER_LOG_VISUALIZATION_TOOL_NAMES,
    CONTEXT_ROUTER_TABLE_RELATION_TOOL_NAMES,
    CONTEXT_ROUTER_TASK_VISUALIZATION_TOOL_NAMES,
    CONTEXT_ROUTER_VALUE_MAPPING_TOOL_NAMES,
)
from context_router.mcp_contract import (
    CONTEXT_ROUTER_TRACE_SERVER_NAME as TRACE_SERVER_NAME,
)
from context_router.schemas.ai_task_visualization import (
    AiTaskCodeLocation,
    AiTaskResultWrite,
    AiTaskVerificationItem,
)
from context_router.schemas.context import ContextDocumentReadRequest
from context_router.services.ai_data_visualization import (
    AiDataVisualizationError,
    AiDataVisualizationService,
)
from context_router.services.ai_log_visualization import (
    AiLogVisualizationError,
    AiLogVisualizationService,
)
from context_router.services.ai_task_visualization import (
    AiTaskVisualizationError,
    AiTaskVisualizationService,
)
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
    TaskContextReadError,
)
from context_router.services.database_catalog import DatabaseCatalogService
from context_router.services.database_query import DatabaseQueryService
from context_router.services.database_tool_payload import DatabaseToolPayloadService
from context_router.services.interface_forwarding_context import (
    InterfaceForwardingContextError,
    InterfaceForwardingContextService,
)
from context_router.services.mcp_trace import McpTraceService
from context_router.services.nacos_middleware import (
    MiddlewareContextError,
    MiddlewareContextService,
)
from context_router.services.table_relation_context import (
    TableRelationContextError,
    TableRelationContextService,
)
from context_router.services.value_mapping import ValueMappingError, ValueMappingService
from context_router.services.workspace_runtime_orchestration import (
    WorkspaceRuntimeOrchestrationError,
    WorkspaceRuntimeOrchestrationService,
)

MCP_SERVER_NAME = "Context Router"
MCP_SERVER_INSTRUCTIONS = (
    "Call prepare_task_context once at the start of a new workspace task. Preserve the "
    "returned task_id and pass it to every document or database call for that task. "
    "Prepare returns the real workspace entry when present, otherwise the active project or "
    "synthetic workspace entry, plus at most two explicit descendant levels and access "
    "capabilities. This navigation projection is not the full searchable scope. Call "
    "read_task_context only when database aliases or generic environment configuration "
    "are needed; it is not the authoritative source for live Nacos middleware details. "
    "When the document tree is large or the target is uncertain, call "
    "search_context_documents and then read the selected document or section with "
    "read_context_document. "
    "Use only database aliases returned by read_task_context. Search database objects before "
    "querying "
    "when the schema is uncertain. Database queries are always bounded and read-only. "
    "prepare again for a new conversation when no task_id is available. "
    "Environment config returned by read_task_context may contain connection details and "
    "credentials for the "
    "environment selected by this task. Treat it as sensitive local-only context and never "
    "echo it into logs or unrelated output. "
    "For Redis, MQ, Elasticsearch, MinIO, job scheduler, object storage, or other live "
    "middleware connection or diagnosis tasks, call read_middleware_context with "
    "the current task_id. For every environment-aware tool, an explicit environment argument "
    "wins; when prepare_task_context omits it, local is used, and later tools inherit the task "
    "environment when they omit it. Environment names come from the selected Workspace. "
    "This local-only "
    "tool returns plaintext by default. Set reveal_secrets=false only when a redacted view is "
    "preferred. Returning and using connection values in the current authorized task is allowed; "
    "never persist them in logs, source code, documentation, unrelated tool arguments, or commits. "
    "When a task involves how a database table relates to other tables, or where in the "
    "source code its rows are inserted or updated, call read_table_relations with the current "
    "task_id and up to 10 table names instead of scanning source code. It returns curated "
    "relations by default. Request writes or updates through sections when code entry points are "
    "needed; paths are relative to the workspace_root stated once per response. evidence=uncertain "
    "expands only soft verdicts and evidence=all expands every relation with per-dimension "
    "verdicts, "
    "measurements, re-runnable check SQL, and relation code sites. "
    "Empty writes or updates only mean no entry points are recorded yet. When only a business "
    "term is known, find exact table names first with search_relation_tables. "
    "When an interface parameter needs a business value such as a shipper ID or carrier ID, "
    "call search_value_mappings by business keyword or exact interface parameter. Then call "
    "resolve_value_candidates with the selected mapping. It executes only the saved bounded "
    "read rule, inherits the task environment when omitted, and returns at most 10 candidates. "
    "Do not invent IDs when a published mapping is available. "
    "When the user wants the browser data-visualization page to open with AI-selected query "
    "conditions, call save_data_visualization_query after resolving an exact published relation "
    "table and keyword. The current task supplies Workspace, environment, and AI source; never "
    "invent a Workspace or environment for this record. "
    "Before completing an investigation or implementation task, call "
    "save_task_visualization_result with a concise evidence-backed conclusion, relevant code "
    "locations, suggested next actions, and verification results. The task_id supplies all "
    "scope; never put credentials, raw logs, or speculative findings in the conclusion. "
    "When diagnosing errors in Docker services, call list_task_containers and inspect only a "
    "container returned for the current task Workspace with inspect_container_errors. The log "
    "reader is bounded and saves a visualization record only when error evidence is found; do "
    "not invent container IDs or inspect containers outside Agent Context Router registration. "
    "When the user wants to call an imported business interface, first use "
    "search_forwarding_interfaces. Use read_forwarding_request_history when recent request or "
    "response values can help assemble parameters, then call prepare_forwarding_request. "
    "Execute only a ready "
    "short-lived plan with execute_forwarding_request and its exact request_sha256. The server "
    "selects the task Workspace/environment, route, and saved account headers; never ask the "
    "user to provide a raw URL or copy saved headers. The first release executes only interfaces "
    "classified as read operations. Omitted address and account selections reuse the latest "
    "successful valid configuration, or the only current candidate. Inspect selection_evidence "
    "for the decision source. A needs_selection or needs_parameters result is a normal request "
    "for an explicit address, account role, or missing business value. The default "
    "value_strategy=reuse_successful preserves the latest successful request. Use "
    "refresh_selected with refresh_value_keys only when the user asks to replace named business "
    "values, refresh_mapped when all mapped values should be regenerated, and ignore_history only "
    "when the user explicitly rejects history. Caller values always win. Never invent business "
    "IDs: inspect parameter_evidence, value_resolutions, and warnings. "
    "When the user asks to start services, call start_workspace: start always means every "
    "registered project in the task Workspace. After modifying registered Workspace code, "
    "call apply_workspace_changes once with task_id and actual Workspace-relative changed "
    "paths. Poll get_workspace_operation until it reaches a terminal state."
)
(
    PREPARE_TOOL_NAME,
    READ_TASK_CONTEXT_TOOL_NAME,
    READ_MIDDLEWARE_CONTEXT_TOOL_NAME,
    SEARCH_CONTEXT_TOOL_NAME,
    READ_TOOL_NAME,
    SEARCH_DATABASE_TOOL_NAME,
    EXECUTE_DATABASE_TOOL_NAME,
) = CONTEXT_ROUTER_CORE_TOOL_NAMES
(
    READ_TABLE_RELATIONS_TOOL_NAME,
    SEARCH_RELATION_TABLES_TOOL_NAME,
) = CONTEXT_ROUTER_TABLE_RELATION_TOOL_NAMES
(
    SEARCH_FORWARDING_INTERFACES_TOOL_NAME,
    READ_FORWARDING_REQUEST_HISTORY_TOOL_NAME,
    PREPARE_FORWARDING_REQUEST_TOOL_NAME,
    EXECUTE_FORWARDING_REQUEST_TOOL_NAME,
) = CONTEXT_ROUTER_INTERFACE_FORWARDING_TOOL_NAMES
(
    SEARCH_VALUE_MAPPINGS_TOOL_NAME,
    RESOLVE_VALUE_CANDIDATES_TOOL_NAME,
) = CONTEXT_ROUTER_VALUE_MAPPING_TOOL_NAMES
(
    LIST_TASK_CONTAINERS_TOOL_NAME,
    INSPECT_CONTAINER_ERRORS_TOOL_NAME,
) = CONTEXT_ROUTER_LOG_VISUALIZATION_TOOL_NAMES
(SAVE_DATA_VISUALIZATION_QUERY_TOOL_NAME,) = CONTEXT_ROUTER_DATA_VISUALIZATION_TOOL_NAMES
(SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME,) = CONTEXT_ROUTER_TASK_VISUALIZATION_TOOL_NAMES
APPLY_WORKSPACE_TOOL_NAME = "apply_workspace_changes"
START_WORKSPACE_TOOL_NAME = "start_workspace"
GET_WORKSPACE_OPERATION_TOOL_NAME = "get_workspace_operation"
APPLY_WORKSPACE_TOOL_DESCRIPTION = (
    "Route actual Workspace-relative changed files to registered Projects, select fast/full "
    "profiles centrally, and queue one ordered asynchronous Workspace operation."
)
START_WORKSPACE_TOOL_DESCRIPTION = (
    "Start every registered service in the task Workspace through its single start profile. "
    "This tool never accepts a project ID, path, script, or command."
)
GET_WORKSPACE_OPERATION_TOOL_DESCRIPTION = (
    "Read one Workspace runtime operation, its ordered steps, and bounded log tails. Poll "
    "until status is succeeded, failed, cancelled, or interrupted."
)
LIST_TASK_CONTAINERS_TOOL_DESCRIPTION = (
    "List only Docker containers registered to the current task Workspace by Agent Context "
    "Router runtime labels. Use this before log inspection to resolve the intended service. "
    "Arbitrary Docker container names or containers from other Workspaces are never returned."
)
INSPECT_CONTAINER_ERRORS_TOOL_DESCRIPTION = (
    "Read a bounded, non-following Docker log snapshot from one container returned by "
    "list_task_containers, extract and redact error blocks, and save a log-visualization record "
    "only when an error is found. Defaults to the latest 15 minutes and 500 lines. Containers "
    "that are unregistered, inaccessible, or outside the task Workspace are rejected and never "
    "recorded. Repeated inspection of the same error in one task updates the same record."
)
SAVE_DATA_VISUALIZATION_QUERY_TOOL_DESCRIPTION = (
    "Save one validated data-visualization query condition for the current task. Workspace, "
    "environment, and AI source are derived from task_id; the caller supplies only the exact "
    "published relation table, keyword, and user-facing description. Repeated identical saves "
    "within one task are idempotent. This tool does not execute the database query."
)
SAVE_TASK_VISUALIZATION_RESULT_TOOL_DESCRIPTION = (
    "Save or update the structured conclusion shown by AI Task Visualization for the current "
    "task. Use investigating only for a meaningful interim conclusion, resolved when the task "
    "was completed and verified, or failed when the task could not be completed. Include only "
    "evidence-backed summaries, Workspace-relative code locations, safe suggested actions, and "
    "verification outcomes. Repeated calls update the same task record and increase its revision."
)
PREPARE_TOOL_DESCRIPTION = (
    "Locate the registered workspace for cwd, create a server-side task number, and "
    "return a task-local document projection. A real workspace AGENTS.md is always level 1; "
    "without one, the active project or synthetic workspace entry is level 1. The result has "
    "at most two explicit descendant levels. Nodes contain only document_id, summary, and "
    "children. Unrelated documents and deeper descendants are omitted from prepare but remain "
    "available through workspace-wide search_context_documents and read_context_document. "
    "Omit environment to use local, or pass any environment registered by the Workspace for "
    "this task only. access states which task capabilities "
    "are available. Database aliases and environment config are intentionally omitted; request "
    "them only when needed with read_task_context. access includes middleware when live Nacos "
    "middleware context may be requested with read_middleware_context."
)
READ_TASK_CONTEXT_TOOL_DESCRIPTION = (
    "Read database aliases and/or generic saved environment JSON for an existing task. "
    "This is not the authoritative or live source for Redis, MQ, Elasticsearch, MinIO, or "
    "other Nacos-managed middleware; use read_middleware_context for those details. Request "
    "only the sections needed. Environment config is sensitive local-only context and must "
    "never be copied into logs or unrelated output."
)
READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION = (
    "Authoritative live source for Redis, MQ, Elasticsearch, MinIO, job scheduler, object "
    "storage, and other Nacos-managed middleware connection or diagnosis tasks. Call this after "
    "prepare_task_context with the current task_id instead of inferring runtime values from "
    "application files or generic environment JSON. Pass any environment registered by the "
    "Workspace for this call; omit it to inherit the task environment. "
    "Omit components to read every configured component, or pass configured component IDs. The "
    "server derives Workspace, environment, Nacos address, namespace, dataIds, and extraction "
    "paths; callers cannot supply them. This local-only tool returns plaintext fields by default; "
    "pass reveal_secrets=false only when a redacted view is preferred. Returning and using "
    "connection values in the current authorized task is allowed. Never persist their values in "
    "logs, source code, documentation, unrelated tool arguments, or commits."
)
READ_TOOL_DESCRIPTION = (
    "Read one or more mapped Markdown documents or exact ATX-heading sections. task_id must "
    "be the value "
    "returned for the current task. Results preserve request order and every call is recorded "
    "server-side."
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
    "by read_task_context. Connection details and query limits are enforced server-side."
)
READ_TABLE_RELATIONS_TOOL_DESCRIPTION = (
    "Read the curated relation list for up to 10 database tables in the current task's "
    "Workspace. Each Workspace has one published relation snapshot; it does not follow or "
    "override the task database environment. Pass task_id and bare table "
    "names; add database only when a table name exists in several databases. A name that "
    "cannot be resolved fails as one entry of the answer with close-name suggestions, without "
    "failing the other tables. sections selects any of relations, writes, updates and defaults "
    "to relations only. Relations return structured child and parent endpoints, the inspected "
    "table's role (child/parent/self), and one cardinality, "
    "read from the code side because it states what the write paths permit; uncertain=true "
    "marks a relation whose code and data readings differ. evidence=uncertain expands only "
    "soft verdicts; evidence=all expands every relation with per-dimension verdicts, stored "
    "measurements, "
    "re-runnable check SQL for execute_database_query, and the code sites behind the code "
    "verdict. Entry points are grouped by workspace-relative source file and list the methods "
    "that persist the table. Join file paths "
    "onto workspace_root, which is stated once per response. Locate a method by name; line "
    "numbers are intentionally not provided. An empty writes or updates list means no entry "
    "points are recorded yet, never that nothing writes the table. Use search_relation_tables "
    "to discover table names; use search_database_objects for raw schema structure."
)
SEARCH_RELATION_TABLES_TOOL_DESCRIPTION = (
    "Find tables in the current task's curated table-relation data by name substring. Use "
    "this when only a business term or entity name is known, or to list which tables of a "
    "database have recorded relations; results are sorted by relation count and resolve into "
    "exact names for read_table_relations. only_related=false includes tables without any "
    "recorded relation. Each Workspace has one published relation snapshot, independent of the "
    "task database environment. This searches the curated relation snapshot only; a table "
    "missing "
    "here may still exist in the database — check search_database_objects before concluding "
    "it does not exist."
)
SEARCH_VALUE_MAPPINGS_TOOL_DESCRIPTION = (
    "Search published business-value mappings in the current task Workspace. Provide a Chinese "
    "business keyword, an exact imported interface ID and parameter location/path, or both. "
    "Results explain the configured read-only resolver and list bounded interface bindings; no "
    "database query is executed."
)
RESOLVE_VALUE_CANDIDATES_TOOL_DESCRIPTION = (
    "Resolve up to 10 candidate values with one published mapping's saved database alias, table, "
    "columns, and fixed filters. Omit environment to inherit the task environment; an explicit "
    "environment must match the task. The caller cannot provide SQL, connection details, or an "
    "unconfigured data source."
)
SEARCH_FORWARDING_INTERFACES_TOOL_DESCRIPTION = (
    "Search imported interfaces in the task Workspace and report whether each is callable in "
    "the task environment. Prefer an exact Chinese business meaning, path fragment, or Controller."
)
READ_FORWARDING_REQUEST_HISTORY_TOOL_DESCRIPTION = (
    "Read the newest bounded request history for one imported interface in the task Workspace "
    "and environment. Use it when request parameters may be reused from recent calls or when a "
    "later request needs a value from an earlier structured response. Request headers are never "
    "returned. Responses are omitted by default and are bounded when explicitly requested."
)
PREPARE_FORWARDING_REQUEST_TOOL_DESCRIPTION = (
    "Resolve one imported interface to the task environment, forwarding address, saved account "
    "role, latest successful request history, and OpenAPI contract. Explicit address/account/role "
    "wins; otherwise the latest successful still-valid selection is reused, followed by a single "
    "current candidate. selection_evidence reports caller, successful_history, or "
    "single_candidate. "
    "Historical pagination is "
    "safely normalized and volatile values are removed. Every proposed field includes source, "
    "evidence, and confidence; historical IDs not backed by an explicit database mapping are "
    "reported in warnings. value_strategy defaults to reuse_successful; refresh_selected replaces "
    "only refresh_value_keys, refresh_mapped replaces every mapped interface value, and "
    "ignore_history rebuilds without request history. Caller values always override generated "
    "values. Returns a short-lived immutable plan only when all required values are present. "
    "Saved request-header values are never returned."
)
EXECUTE_FORWARDING_REQUEST_TOOL_DESCRIPTION = (
    "Execute exactly one prepared, unexpired, read-only forwarding plan. The caller must echo the "
    "plan request_sha256; raw URLs, methods, request headers, and arbitrary overrides are "
    "forbidden."
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
RUNTIME_APPLY_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
RUNTIME_READ_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
FORWARDING_PREPARE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
FORWARDING_EXECUTE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
LOG_INSPECTION_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
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
        operation_task_resolver: Callable[[str], int] | None = None,
        **kwargs: object,
    ):
        self._trace_service = trace_service
        self._database_payload_service = database_payload_service
        self._operation_task_resolver = operation_task_resolver
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
        if task_id is None and name == GET_WORKSPACE_OPERATION_TOOL_NAME:
            operation_id = arguments.get("operation_id")
            if isinstance(operation_id, str) and self._operation_task_resolver is not None:
                try:
                    task_id = self._operation_task_resolver(operation_id)
                except Exception:
                    task_id = None
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
    workspace_runtime_service: WorkspaceRuntimeOrchestrationService | None = None,
    middleware_context_service: MiddlewareContextService | None = None,
    table_relation_context_service: TableRelationContextService | None = None,
    interface_forwarding_context_service: InterfaceForwardingContextService | None = None,
    value_mapping_service: ValueMappingService | None = None,
    ai_data_visualization_service: AiDataVisualizationService | None = None,
    ai_log_visualization_service: AiLogVisualizationService | None = None,
    ai_task_visualization_service: AiTaskVisualizationService | None = None,
) -> FastMCP:
    forwarding_execution_limiter = asyncio.Semaphore(4)
    server = ContextRouterMCP(
        name=MCP_SERVER_NAME,
        instructions=MCP_SERVER_INSTRUCTIONS,
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        trace_service=trace_service,
        database_payload_service=database_payload_service,
        operation_task_resolver=(
            workspace_runtime_service.get_task_id if workspace_runtime_service else None
        ),
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
        environment: Annotated[
            str | None,
            Field(
                max_length=32,
                pattern=r"^[a-z][a-z0-9_-]{0,31}$",
                description=("Optional task-only environment. Omit to use local."),
            ),
        ] = None,
    ) -> dict[str, Any]:
        try:
            result = preparation_service.prepare(
                task=task,
                cwd=cwd,
                agent_name=agent_name,
                environment=environment,
            )
        except ContextPreparationError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        return result.model_dump(exclude_none=True)

    @server.tool(
        name=READ_TASK_CONTEXT_TOOL_NAME,
        description=READ_TASK_CONTEXT_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def read_task_context(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        sections: Annotated[
            list[Literal["databases", "environment"]],
            Field(min_length=1, max_length=2),
        ],
    ) -> dict[str, Any]:
        try:
            result = preparation_service.read_task_context(
                task_id=task_id,
                sections=sections,
            )
        except TaskContextReadError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        return result.model_dump(exclude_none=True)

    @server.tool(
        name=READ_MIDDLEWARE_CONTEXT_TOOL_NAME,
        description=READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def read_middleware_context(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        environment: Annotated[
            str | None,
            Field(
                max_length=32,
                pattern=r"^[a-z][a-z0-9_-]{0,31}$",
                description="Optional call environment. Omit to inherit the task environment.",
            ),
        ] = None,
        components: Annotated[
            list[
                Annotated[
                    str,
                    Field(
                        min_length=1,
                        max_length=64,
                        pattern=r"^[a-z][a-z0-9_-]{0,63}$",
                    ),
                ]
            ]
            | None,
            Field(default=None, min_length=1, max_length=20),
        ] = None,
        reveal_secrets: Annotated[bool, Field(strict=True)] = True,
    ) -> dict[str, Any]:
        if middleware_context_service is None:
            raise ToolError("middleware_context_disabled: 中间件上下文工具当前不可用")
        try:
            result = middleware_context_service.read(
                task_id=task_id,
                environment=environment,
                components=components,
                reveal_secrets=reveal_secrets,
            )
        except MiddlewareContextError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        return result.model_dump(mode="json", exclude_none=True)

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

    @server.tool(
        name=SAVE_DATA_VISUALIZATION_QUERY_TOOL_NAME,
        description=SAVE_DATA_VISUALIZATION_QUERY_TOOL_DESCRIPTION,
        annotations=LOG_INSPECTION_TOOL_ANNOTATIONS,
    )
    def save_data_visualization_query(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        description: Annotated[str, Field(min_length=1, max_length=2000)],
        database_key: Annotated[
            str,
            Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"),
        ],
        schema_name: Annotated[str, Field(min_length=1, max_length=255)],
        table_name: Annotated[str, Field(min_length=1, max_length=255)],
        keyword: Annotated[str, Field(min_length=1, max_length=500)],
    ) -> dict[str, object]:
        if ai_data_visualization_service is None:
            raise ToolError("data_visualization_disabled: 数据可视化 MCP 当前不可用")
        try:
            result = ai_data_visualization_service.create_for_task(
                task_id=task_id,
                description=description,
                database_key=database_key,
                schema_name=schema_name,
                table_name=table_name,
                keyword=keyword,
            )
            return result.model_dump(mode="json", exclude_none=True)
        except AiDataVisualizationError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME,
        description=SAVE_TASK_VISUALIZATION_RESULT_TOOL_DESCRIPTION,
        annotations=LOG_INSPECTION_TOOL_ANNOTATIONS,
    )
    def save_task_visualization_result(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        status: Literal["investigating", "resolved", "failed"],
        summary: Annotated[str, Field(min_length=1, max_length=4000)],
        root_cause: Annotated[str | None, Field(max_length=4000)] = None,
        code_locations: Annotated[
            list[AiTaskCodeLocation] | None,
            Field(default=None, max_length=50),
        ] = None,
        suggested_actions: Annotated[
            list[Annotated[str, Field(min_length=1, max_length=1000)]] | None,
            Field(default=None, max_length=50),
        ] = None,
        verification: Annotated[
            list[AiTaskVerificationItem] | None,
            Field(default=None, max_length=50),
        ] = None,
    ) -> dict[str, object]:
        if ai_task_visualization_service is None:
            raise ToolError("task_visualization_disabled: 任务可视化 MCP 当前不可用")
        try:
            result = ai_task_visualization_service.save_result(
                task_id,
                AiTaskResultWrite(
                    status=status,
                    summary=summary,
                    root_cause=root_cause,
                    code_locations=code_locations or [],
                    suggested_actions=suggested_actions or [],
                    verification=verification or [],
                ),
            )
            return result.model_dump(mode="json", exclude_none=True)
        except AiTaskVisualizationError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=LIST_TASK_CONTAINERS_TOOL_NAME,
        description=LIST_TASK_CONTAINERS_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def list_task_containers(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        query: Annotated[str | None, Field(min_length=1, max_length=240)] = None,
    ) -> dict[str, object]:
        if ai_log_visualization_service is None:
            raise ToolError("log_visualization_disabled: 容器日志排查 MCP 当前不可用")
        try:
            return ai_log_visualization_service.list_task_containers(
                task_id=task_id,
                query=query,
            )
        except AiLogVisualizationError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=INSPECT_CONTAINER_ERRORS_TOOL_NAME,
        description=INSPECT_CONTAINER_ERRORS_TOOL_DESCRIPTION,
        annotations=LOG_INSPECTION_TOOL_ANNOTATIONS,
    )
    def inspect_container_errors(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        container_id: Annotated[str, Field(min_length=12, max_length=64)],
        since_minutes: Annotated[int, Field(ge=1, le=1440, strict=True)] = 15,
        tail: Annotated[int, Field(ge=1, le=1000, strict=True)] = 500,
        keywords: Annotated[
            list[Annotated[str, Field(min_length=1, max_length=120)]] | None,
            Field(default=None, min_length=1, max_length=10),
        ] = None,
    ) -> dict[str, object]:
        if ai_log_visualization_service is None:
            raise ToolError("log_visualization_disabled: 容器日志排查 MCP 当前不可用")
        try:
            return ai_log_visualization_service.inspect_container_errors(
                task_id=task_id,
                container_id=container_id,
                since_minutes=since_minutes,
                tail=tail,
                keywords=keywords,
            )
        except AiLogVisualizationError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=READ_TABLE_RELATIONS_TOOL_NAME,
        description=READ_TABLE_RELATIONS_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def read_table_relations(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        tables: Annotated[
            list[Annotated[str, Field(min_length=1, max_length=255)]],
            Field(min_length=1, max_length=10),
        ],
        sections: Annotated[
            list[Literal["relations", "writes", "updates"]] | None,
            Field(default=None, min_length=1, max_length=3),
        ] = None,
        database: Annotated[
            str | None,
            Field(max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"),
        ] = None,
        evidence: Annotated[
            Literal["none", "uncertain", "all"],
            Field(description="Evidence expansion mode; defaults to no evidence."),
        ] = "none",
    ) -> dict[str, object]:
        if table_relation_context_service is None:
            raise ToolError("table_relations_disabled: 表关联上下文工具当前不可用")
        try:
            return table_relation_context_service.read(
                task_id=task_id,
                tables=tables,
                sections=sections,
                database=database,
                evidence=evidence,
            )
        except TableRelationContextError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=SEARCH_RELATION_TABLES_TOOL_NAME,
        description=SEARCH_RELATION_TABLES_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def search_relation_tables(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        query: Annotated[str | None, Field(min_length=1, max_length=255)] = None,
        database: Annotated[
            str | None,
            Field(max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"),
        ] = None,
        only_related: Annotated[bool, Field(strict=True)] = True,
        limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 50,
    ) -> dict[str, object]:
        if table_relation_context_service is None:
            raise ToolError("table_relations_disabled: 表关联上下文工具当前不可用")
        try:
            return table_relation_context_service.search(
                task_id=task_id,
                query=query,
                database=database,
                only_related=only_related,
                limit=limit,
            )
        except TableRelationContextError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=SEARCH_VALUE_MAPPINGS_TOOL_NAME,
        description=SEARCH_VALUE_MAPPINGS_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def search_value_mappings(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        query: Annotated[str | None, Field(min_length=1, max_length=240)] = None,
        interface_id: Annotated[str | None, Field(min_length=1, max_length=36)] = None,
        location: Literal["path", "query", "body"] | None = None,
        parameter_path: Annotated[str | None, Field(min_length=1, max_length=240)] = None,
        limit: Annotated[int, Field(ge=1, le=20, strict=True)] = 10,
    ) -> dict[str, object]:
        if value_mapping_service is None:
            raise ToolError("value_mapping_disabled: 业务值映射 MCP 当前不可用")
        try:
            return value_mapping_service.search_for_task(
                task_id=task_id,
                query=query,
                interface_id=interface_id,
                location=location,
                parameter_path=parameter_path,
                limit=limit,
            )
        except ValueMappingError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=RESOLVE_VALUE_CANDIDATES_TOOL_NAME,
        description=RESOLVE_VALUE_CANDIDATES_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def resolve_value_candidates(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        mapping_id: Annotated[str, Field(min_length=1, max_length=36)],
        environment: Annotated[
            str | None,
            Field(max_length=32, pattern=r"^[a-z][a-z0-9_-]{0,31}$"),
        ] = None,
        keyword: Annotated[str, Field(max_length=240)] = "",
        limit: Annotated[int, Field(ge=1, le=10, strict=True)] = 10,
    ) -> dict[str, object]:
        if value_mapping_service is None:
            raise ToolError("value_mapping_disabled: 业务值映射 MCP 当前不可用")
        try:
            return value_mapping_service.resolve_for_task(
                mapping_id,
                task_id=task_id,
                environment=environment,
                keyword=keyword,
                limit=limit,
            )
        except ValueMappingError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=SEARCH_FORWARDING_INTERFACES_TOOL_NAME,
        description=SEARCH_FORWARDING_INTERFACES_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def search_forwarding_interfaces(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        query: Annotated[str, Field(min_length=1, max_length=240)],
        service: Annotated[str | None, Field(max_length=160)] = None,
        role: Annotated[str | None, Field(max_length=160)] = None,
        limit: Annotated[int, Field(ge=1, le=50, strict=True)] = 10,
    ) -> dict[str, object]:
        if interface_forwarding_context_service is None:
            raise ToolError("interface_forwarding_disabled: 接口转发 MCP 当前不可用")
        try:
            return interface_forwarding_context_service.search(
                task_id=task_id,
                query=query,
                service=service,
                role=role,
                limit=limit,
            )
        except InterfaceForwardingContextError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=READ_FORWARDING_REQUEST_HISTORY_TOOL_NAME,
        description=READ_FORWARDING_REQUEST_HISTORY_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def read_forwarding_request_history(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        interface_id: Annotated[str, Field(min_length=1, max_length=36)],
        limit: Annotated[int, Field(ge=1, le=10, strict=True)] = 5,
        success_only: Annotated[bool, Field(strict=True)] = True,
        include_response: Annotated[bool, Field(strict=True)] = False,
    ) -> dict[str, object]:
        if interface_forwarding_context_service is None:
            raise ToolError("interface_forwarding_disabled: 接口转发 MCP 当前不可用")
        try:
            return interface_forwarding_context_service.history(
                task_id=task_id,
                interface_id=interface_id,
                limit=limit,
                success_only=success_only,
                include_response=include_response,
            )
        except InterfaceForwardingContextError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=PREPARE_FORWARDING_REQUEST_TOOL_NAME,
        description=PREPARE_FORWARDING_REQUEST_TOOL_DESCRIPTION,
        annotations=FORWARDING_PREPARE_TOOL_ANNOTATIONS,
    )
    def prepare_forwarding_request(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        interface_id: Annotated[str, Field(min_length=1, max_length=36)],
        environment: Annotated[
            str | None,
            Field(max_length=32, pattern=r"^[a-z][a-z0-9_-]{0,31}$"),
        ] = None,
        address_id: Annotated[str | None, Field(max_length=36)] = None,
        login_account: Annotated[str | None, Field(max_length=240)] = None,
        role_name: Annotated[str | None, Field(max_length=160)] = None,
        path: Annotated[dict[str, Any] | None, Field(default=None)] = None,
        query: Annotated[dict[str, Any] | None, Field(default=None)] = None,
        body: Annotated[dict[str, Any] | None, Field(default=None)] = None,
        value_strategy: Literal[
            "reuse_successful",
            "refresh_selected",
            "refresh_mapped",
            "ignore_history",
        ] = "reuse_successful",
        refresh_value_keys: Annotated[
            list[
                Annotated[
                    str,
                    Field(
                        min_length=1,
                        max_length=64,
                        pattern=r"^[a-z][a-z0-9_]{0,63}$",
                    ),
                ]
            ]
            | None,
            Field(default=None, min_length=1, max_length=20),
        ] = None,
    ) -> dict[str, object]:
        if interface_forwarding_context_service is None:
            raise ToolError("interface_forwarding_disabled: 接口转发 MCP 当前不可用")
        try:
            return interface_forwarding_context_service.prepare(
                task_id=task_id,
                interface_id=interface_id,
                environment=environment,
                address_id=address_id,
                login_account=login_account,
                role_name=role_name,
                path=path,
                query=query,
                body=body,
                value_strategy=value_strategy,
                refresh_value_keys=refresh_value_keys,
            )
        except InterfaceForwardingContextError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=EXECUTE_FORWARDING_REQUEST_TOOL_NAME,
        description=EXECUTE_FORWARDING_REQUEST_TOOL_DESCRIPTION,
        annotations=FORWARDING_EXECUTE_TOOL_ANNOTATIONS,
    )
    async def execute_forwarding_request(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        plan_id: Annotated[str, Field(min_length=1, max_length=36)],
        request_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
    ) -> dict[str, object]:
        if interface_forwarding_context_service is None:
            raise ToolError("interface_forwarding_disabled: 接口转发 MCP 当前不可用")
        try:
            async with forwarding_execution_limiter:
                return await anyio.to_thread.run_sync(
                    partial(
                        interface_forwarding_context_service.execute,
                        task_id=task_id,
                        plan_id=plan_id,
                        request_sha256=request_sha256,
                    ),
                    abandon_on_cancel=False,
                )
        except InterfaceForwardingContextError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=APPLY_WORKSPACE_TOOL_NAME,
        description=APPLY_WORKSPACE_TOOL_DESCRIPTION,
        annotations=RUNTIME_APPLY_TOOL_ANNOTATIONS,
    )
    def apply_workspace_changes(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        changed_files: Annotated[
            list[Annotated[str, Field(min_length=1, max_length=1000)]],
            Field(min_length=1, max_length=500),
        ],
    ) -> dict[str, object]:
        if workspace_runtime_service is None:
            raise ToolError("workspace_runtime_disabled: Workspace Runtime 当前不可用")
        try:
            result = workspace_runtime_service.apply_changes(
                task_id=task_id,
                changed_files=changed_files,
            )
        except WorkspaceRuntimeOrchestrationError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        return result.model_dump(mode="json", exclude_none=True)

    @server.tool(
        name=START_WORKSPACE_TOOL_NAME,
        description=START_WORKSPACE_TOOL_DESCRIPTION,
        annotations=RUNTIME_APPLY_TOOL_ANNOTATIONS,
    )
    def start_workspace(
        task_id: Annotated[int, Field(ge=1, strict=True)],
    ) -> dict[str, object]:
        if workspace_runtime_service is None:
            raise ToolError("workspace_runtime_disabled: Workspace Runtime 当前不可用")
        try:
            result = workspace_runtime_service.start_workspace(task_id=task_id)
        except WorkspaceRuntimeOrchestrationError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        return result.model_dump(mode="json", exclude_none=True)

    @server.tool(
        name=GET_WORKSPACE_OPERATION_TOOL_NAME,
        description=GET_WORKSPACE_OPERATION_TOOL_DESCRIPTION,
        annotations=RUNTIME_READ_TOOL_ANNOTATIONS,
    )
    def get_workspace_operation(
        operation_id: Annotated[str, Field(min_length=1, max_length=32)],
        log_characters: Annotated[int, Field(ge=1, le=50_000)] = 10_000,
    ) -> dict[str, object]:
        if workspace_runtime_service is None:
            raise ToolError("workspace_runtime_disabled: Workspace Runtime 当前不可用")
        try:
            result = workspace_runtime_service.get_operation(operation_id, log_characters)
        except WorkspaceRuntimeOrchestrationError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        return result.model_dump(mode="json", exclude_none=True)

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
            "environment": _safe_string(arguments.get("environment"), 32),
        }
    if name == READ_TASK_CONTEXT_TOOL_NAME:
        sections = arguments.get("sections")
        return {
            "sections": [item for item in sections if isinstance(item, str)]
            if isinstance(sections, list)
            else [],
        }
    if name == READ_MIDDLEWARE_CONTEXT_TOOL_NAME:
        components = arguments.get("components")
        return {
            "environment": _safe_string(arguments.get("environment"), 16),
            "component_count": len(components) if isinstance(components, list) else None,
            "all_components": components is None,
            "reveal_secrets": arguments.get("reveal_secrets", True) is True,
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
            "environment": _safe_string(arguments.get("environment"), 16),
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
    if name == SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME:
        locations = arguments.get("code_locations")
        actions = arguments.get("suggested_actions")
        verification = arguments.get("verification")
        return {
            "status": _safe_string(arguments.get("status"), 20),
            "summary_characters": (
                len(arguments["summary"]) if isinstance(arguments.get("summary"), str) else 0
            ),
            "root_cause_supplied": isinstance(arguments.get("root_cause"), str),
            "code_location_count": len(locations) if isinstance(locations, list) else 0,
            "suggested_action_count": len(actions) if isinstance(actions, list) else 0,
            "verification_count": len(verification) if isinstance(verification, list) else 0,
        }
    if name == READ_TABLE_RELATIONS_TOOL_NAME:
        sections = arguments.get("sections")
        tables = arguments.get("tables")
        return {
            "tables": (
                [_safe_string(item, 255) for item in tables if isinstance(item, str)]
                if isinstance(tables, list)
                else None
            ),
            "database": _safe_string(arguments.get("database"), 64),
            "environment": _safe_string(arguments.get("environment"), 16),
            "sections": (
                [item for item in sections if isinstance(item, str)]
                if isinstance(sections, list)
                else None
            ),
            "evidence": _safe_string(arguments.get("evidence"), 16) or "none",
        }
    if name == SEARCH_RELATION_TABLES_TOOL_NAME:
        return {
            "query": _safe_string(arguments.get("query"), 255),
            "database": _safe_string(arguments.get("database"), 64),
            "environment": _safe_string(arguments.get("environment"), 32),
            "only_related": arguments.get("only_related", True) is True,
            "limit": arguments.get("limit") if isinstance(arguments.get("limit"), int) else None,
        }
    if name == SEARCH_VALUE_MAPPINGS_TOOL_NAME:
        raw_query = arguments.get("query")
        return {
            "query_sha256": (
                hashlib.sha256(raw_query.strip().encode("utf-8")).hexdigest()
                if isinstance(raw_query, str)
                else None
            ),
            "interface_id": _safe_string(arguments.get("interface_id"), 36),
            "location": _safe_string(arguments.get("location"), 16),
            "parameter_path": _safe_string(arguments.get("parameter_path"), 240),
            "limit": arguments.get("limit") if isinstance(arguments.get("limit"), int) else None,
        }
    if name == RESOLVE_VALUE_CANDIDATES_TOOL_NAME:
        keyword = arguments.get("keyword")
        return {
            "mapping_id": _safe_string(arguments.get("mapping_id"), 36),
            "environment": _safe_string(arguments.get("environment"), 32),
            "keyword_sha256": (
                hashlib.sha256(keyword.strip().encode("utf-8")).hexdigest()
                if isinstance(keyword, str) and keyword.strip()
                else None
            ),
            "limit": arguments.get("limit") if isinstance(arguments.get("limit"), int) else None,
        }
    if name == SEARCH_FORWARDING_INTERFACES_TOOL_NAME:
        raw_query = arguments.get("query")
        return {
            "query_sha256": (
                hashlib.sha256(raw_query.strip().encode("utf-8")).hexdigest()
                if isinstance(raw_query, str)
                else None
            ),
            "service": _safe_string(arguments.get("service"), 160),
            "role": _safe_string(arguments.get("role"), 160),
            "limit": arguments.get("limit") if isinstance(arguments.get("limit"), int) else None,
        }
    if name == READ_FORWARDING_REQUEST_HISTORY_TOOL_NAME:
        return {
            "interface_id": _safe_string(arguments.get("interface_id"), 36),
            "limit": arguments.get("limit") if isinstance(arguments.get("limit"), int) else 5,
            "success_only": arguments.get("success_only", True) is True,
            "include_response": arguments.get("include_response", False) is True,
        }
    if name == PREPARE_FORWARDING_REQUEST_TOOL_NAME:
        supplied = {
            location: len(arguments.get(location, {}))
            if isinstance(arguments.get(location), dict)
            else 0
            for location in ("path", "query", "body")
        }
        return {
            "interface_id": _safe_string(arguments.get("interface_id"), 36),
            "environment": _safe_string(arguments.get("environment"), 32),
            "address_selected": isinstance(arguments.get("address_id"), str),
            "account_selected": isinstance(arguments.get("login_account"), str),
            "role_selected": isinstance(arguments.get("role_name"), str),
            "supplied_value_counts": supplied,
            "value_strategy": _safe_string(arguments.get("value_strategy"), 32)
            or "reuse_successful",
            "refresh_value_key_count": (
                len(arguments.get("refresh_value_keys", []))
                if isinstance(arguments.get("refresh_value_keys"), list)
                else 0
            ),
        }
    if name == EXECUTE_FORWARDING_REQUEST_TOOL_NAME:
        return {
            "plan_id": _safe_string(arguments.get("plan_id"), 36),
            "request_sha256": _safe_string(arguments.get("request_sha256"), 64),
        }
    if name == APPLY_WORKSPACE_TOOL_NAME:
        changed_files = arguments.get("changed_files")
        return {"changed_file_count": len(changed_files) if isinstance(changed_files, list) else 0}
    if name == START_WORKSPACE_TOOL_NAME:
        return {"scope": "workspace"}
    if name == GET_WORKSPACE_OPERATION_TOOL_NAME:
        return {
            "operation_id": _safe_string(arguments.get("operation_id"), 32),
            "log_characters": arguments.get("log_characters", 10_000),
        }
    return None


def _result_summary(name: str, payload: dict[str, Any]) -> dict[str, object] | None:
    if name == PREPARE_TOOL_NAME:
        return {
            "document_count": _document_tree_count(payload.get("documents")),
            "warning_count": len(payload.get("warnings", []))
            if isinstance(payload.get("warnings"), list)
            else 0,
        }
    if name == READ_TASK_CONTEXT_TOOL_NAME:
        databases = payload.get("databases")
        environment = payload.get("environment")
        return {
            "database_count": len(databases) if isinstance(databases, list) else None,
            "environment_requested": isinstance(environment, dict),
            "environment_configured": (
                bool(environment.get("configured")) if isinstance(environment, dict) else None
            ),
        }
    if name == READ_MIDDLEWARE_CONTEXT_TOOL_NAME:
        components = payload.get("components")
        warnings = payload.get("warnings")
        return {
            "component_count": len(components) if isinstance(components, list) else 0,
            "source_count": (
                sum(
                    len(component.get("sources", []))
                    for component in components
                    if isinstance(component, dict) and isinstance(component.get("sources"), list)
                )
                if isinstance(components, list)
                else 0
            ),
            "warning_count": len(warnings) if isinstance(warnings, list) else 0,
            "secrets_revealed": payload.get("secrets_revealed") is True,
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
    if name == SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME:
        locations = payload.get("code_locations")
        verification = payload.get("verification")
        return {
            "status": _safe_string(payload.get("status"), 20),
            "revision": payload.get("revision"),
            "code_location_count": len(locations) if isinstance(locations, list) else 0,
            "verification_count": len(verification) if isinstance(verification, list) else 0,
        }
    if name == READ_TABLE_RELATIONS_TOOL_NAME:
        entries = payload.get("tables")
        if not isinstance(entries, list):
            return {"table_count": 0}
        resolved = [entry for entry in entries if isinstance(entry, dict) and "error" not in entry]
        return {
            "table_count": len(entries),
            "error_count": len(entries) - len(resolved),
            "relation_count": sum(
                len(entry["relations"])
                for entry in resolved
                if isinstance(entry.get("relations"), list)
            ),
            "write_count": sum(
                len(entry["writes"]) for entry in resolved if isinstance(entry.get("writes"), list)
            ),
            "update_count": sum(
                len(entry["updates"])
                for entry in resolved
                if isinstance(entry.get("updates"), list)
            ),
        }
    if name == SEARCH_RELATION_TABLES_TOOL_NAME:
        tables = payload.get("tables")
        return {
            "returned_count": len(tables) if isinstance(tables, list) else 0,
            "truncated": payload.get("truncated") is True,
        }
    if name == SEARCH_VALUE_MAPPINGS_TOOL_NAME:
        return {
            "returned_count": payload.get("returned_count", 0),
            "environment": _safe_string(payload.get("environment"), 32),
            "truncated": payload.get("truncated") is True,
        }
    if name == RESOLVE_VALUE_CANDIDATES_TOOL_NAME:
        return {
            "mapping_id": _safe_string(payload.get("mapping_id"), 36),
            "returned_count": payload.get("returned_count", 0),
            "environment": _safe_string(payload.get("environment"), 32),
            "truncated": payload.get("truncated") is True,
        }
    if name == SEARCH_FORWARDING_INTERFACES_TOOL_NAME:
        return {
            "returned_count": payload.get("returned_count", 0),
            "environment": _safe_string(payload.get("environment"), 32),
        }
    if name == READ_FORWARDING_REQUEST_HISTORY_TOOL_NAME:
        return {
            "returned_count": payload.get("returned_count", 0),
            "environment": _safe_string(payload.get("environment"), 32),
        }
    if name == PREPARE_FORWARDING_REQUEST_TOOL_NAME:
        candidates = payload.get("candidates")
        missing = payload.get("missing")
        value_resolutions = payload.get("value_resolutions")
        resolution_issues = payload.get("resolution_issues")
        selection_evidence = payload.get("selection_evidence")
        address_selection = (
            selection_evidence.get("address") if isinstance(selection_evidence, dict) else None
        )
        identity_selection = (
            selection_evidence.get("identity") if isinstance(selection_evidence, dict) else None
        )
        return {
            "status": _safe_string(payload.get("status"), 32),
            "value_strategy": _safe_string(payload.get("value_strategy"), 32),
            "candidate_count": len(candidates) if isinstance(candidates, list) else 0,
            "missing_count": len(missing) if isinstance(missing, list) else 0,
            "value_resolution_count": (
                len(value_resolutions) if isinstance(value_resolutions, list) else 0
            ),
            "resolution_issue_count": (
                len(resolution_issues) if isinstance(resolution_issues, list) else 0
            ),
            "address_selection_source": (
                _safe_string(address_selection.get("source"), 32)
                if isinstance(address_selection, dict)
                else None
            ),
            "identity_selection_source": (
                _safe_string(identity_selection.get("source"), 32)
                if isinstance(identity_selection, dict)
                else None
            ),
            "plan_id": _safe_string(payload.get("plan_id"), 36),
        }
    if name == EXECUTE_FORWARDING_REQUEST_TOOL_NAME:
        return {
            "status": _safe_string(payload.get("status"), 32),
            "success": payload.get("success") is True,
            "status_code": payload.get("status_code"),
            "duration_ms": payload.get("duration_ms"),
            "response_bytes": payload.get("response_bytes"),
            "truncated": payload.get("truncated") is True,
        }
    if name in {
        APPLY_WORKSPACE_TOOL_NAME,
        START_WORKSPACE_TOOL_NAME,
        GET_WORKSPACE_OPERATION_TOOL_NAME,
    }:
        steps = payload.get("steps")
        return {
            "operation_id": _safe_string(payload.get("id"), 32),
            "status": _safe_string(payload.get("status"), 16),
            "step_count": len(steps) if isinstance(steps, list) else 0,
        }
    return None


def _document_tree_count(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    children = value.get("children")
    return (
        1 + sum(_document_tree_count(child) for child in children)
        if isinstance(children, list)
        else 1
    )


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
