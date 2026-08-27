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
from mcp.server.fastmcp import Context, FastMCP
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
from context_router.mcp_tool_registry import TaskToolRegistry
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
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
from context_router.services.database_context import DatabaseContextError, DatabaseContextService
from context_router.services.database_query import DatabaseQueryService
from context_router.services.database_tool_payload import DatabaseToolPayloadService
from context_router.services.interface_forwarding_context import (
    InterfaceForwardingContextError,
    InterfaceForwardingContextService,
)
from context_router.services.mcp_trace import McpTraceService, current_tool_call_id
from context_router.services.nacos_middleware import (
    MiddlewareContextError,
    MiddlewareContextService,
)
from context_router.services.table_relation_context import (
    TableRelationContextError,
    TableRelationContextService,
)
from context_router.services.task_capability import TaskCapabilityError, TaskCapabilityService
from context_router.services.value_mapping import ValueMappingError, ValueMappingService
from context_router.services.workspace_runtime_orchestration import (
    WorkspaceRuntimeOrchestrationError,
    WorkspaceRuntimeOrchestrationService,
)

MCP_SERVER_NAME = "Context Router"
MCP_CLIENT_NAME_HEADER = "X-Agent-Name"
MCP_CLIENT_AGENT_NAMES = frozenset({"codex", "gemini", "antigravity", "cursor", "grok"})
MCP_SERVER_INSTRUCTIONS = (
    "Call prepare_task_context once at the start of a new workspace task. First classify the "
    "user's primary intent as interface_discovery, interface_execute, data_query, task_execute, "
    "bug_investigate, bug_fix, or code_change and pass it as intent_type. Use "
    "interface_discovery when the user only wants to find, compare, or inspect an interface; "
    "the server also corrects discovery wording that was declared as interface_execute. Set "
    "error_signal=true only when a Bug "
    "request contains "
    "or points to actual runtime error evidence. Preserve the "
    "returned task_id and pass it to every document or database call for that task. Every "
    "successful traced tool response includes tool_call_id; reuse that exact ID in later "
    "execution_tool_call_id or verification_call_ids fields instead of inventing evidence. "
    "The document navigation tools are core direct-call tools: after prepare, call "
    "search_context_documents directly when the target is uncertain, then call "
    "read_context_document directly for selected IDs or sections. These core tools are never "
    "returned by discover_task_tools and must never be wrapped in invoke_task_tool. "
    "Use prepare_task_context.recommended_actions first for professional capabilities. When the "
    "next technical domain is not covered, call discover_task_tools with the same task_id and "
    "current sub-goal, then call invoke_task_tool with the returned name, arguments schema, and "
    "definition_revision. Direct "
    "professional tools remain available during rollout, but do not enumerate or call unrelated "
    "tools speculatively. "
    "Prepare returns the real workspace entry when present, otherwise the active project or "
    "synthetic workspace entry, plus at most two explicit descendant levels and access "
    "capabilities. This navigation projection is not the full searchable scope. A "
    "business-value mapping search and atomic execution can run immediately after "
    "prepare_task_context; do not call "
    "read_task_context, search_database_objects, or execute_database_query merely to discover or "
    "recheck the mapping source. When a mapping fits, call execute_mapped_data_query so execution "
    "and visualization saving happen atomically. Keep include_record=true when the user needs the "
    "selected row. When it returns goal_completed=true, call only its terminal next_action; do not "
    "resolve a database, search schemas or relations, execute raw SQL, or save the visualization "
    "again. Call "
    "read_task_context only after no suitable mapping is "
    "found "
    "and raw database aliases or generic environment configuration are needed; it is not the "
    "authoritative source for live Nacos middleware details. "
    "When the document tree is large or the target is uncertain, call "
    "search_context_documents and then read the selected document or section with "
    "read_context_document. "
    "For raw database work, call resolve_database_target and pass its opaque "
    "database_context_id to database tools. Never pass or guess a database alias. Search database "
    "objects before querying "
    "when the schema is uncertain. Database queries are always bounded and read-only. "
    "prepare again for a new conversation when no task_id is available. "
    "Environment config returned by read_task_context may contain connection details and "
    "credentials for the "
    "environment selected by this task. Treat it as sensitive local-only context and never "
    "echo it into logs or unrelated output. "
    "The task environment is selected once by prepare_task_context from the registered "
    "Workspace environment aliases and is returned in the prepare result. Every later tool "
    "inherits that immutable task snapshot and never accepts an environment override. "
    "For Redis, MQ, Elasticsearch, MinIO, job scheduler, object storage, or other live "
    "middleware connection or diagnosis tasks, call read_middleware_context with "
    "the current task_id. Environment names and aliases come from the selected Workspace. "
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
    "Empty writes or updates only mean no entry points are recorded yet. When a table-relation "
    "task starts from only a business term, find exact table names with search_relation_tables. "
    "When a data query or interface parameter contains a business value such as a shipper ID "
    "or carrier ID, call search_value_mappings by business keyword before discovering tables "
    "or inventing SQL. Then call "
    "resolve_value_candidates with the selected mapping. When the user asks for a random value, "
    "pass selection=random and the exact requested limit; do not replace it with ORDER BY RAND() "
    "or another raw random SQL query. It executes only the saved bounded "
    "read rule, inherits the task environment when omitted, and returns at most 10 candidates. "
    "Use table-relation and raw schema discovery only when no published mapping fits. Do not "
    "invent IDs when a published mapping is available. "
    "When the user wants the browser data-visualization page to open with AI-selected query "
    "conditions, call save_data_visualization_query after resolving an exact published relation "
    "table and keyword. The current task supplies Workspace, environment, and AI source; never "
    "invent a Workspace or environment for this record. "
    "Use one task_id for the full execution lifecycle: prepare context, inspect or change the "
    "authorized Workspace, verify the outcome, then call save_task_visualization_result before "
    "the final user response. Use investigating only for a meaningful non-terminal checkpoint. "
    "Use resolved only after the requested outcome is complete and include at least one actual "
    "verification result. Use failed only for a concrete blocker and include its root cause and "
    "safe next action. The saved conclusion is a structured execution record, not a replacement "
    "for the user-facing response. Never put credentials, raw logs, or speculative findings in it. "
    "When diagnosing errors in Docker services, call list_task_containers and inspect only a "
    "container returned for the current task Workspace with inspect_container_errors. The log "
    "reader is bounded and saves a visualization record only when error evidence is found; do "
    "not invent container IDs or inspect containers outside Agent Context Router registration. "
    "When the user wants to call an imported business interface, first use "
    "search_forwarding_interfaces. Use read_forwarding_request_history when recent request or "
    "response values can help assemble parameters, then call prepare_forwarding_request. "
    "Execute only a ready "
    "short-lived plan with execute_forwarding_request and its exact request_sha256. The server "
    "deduplicates retries of the same plan and successful equivalent requests in the same task. "
    "After a successful interface execution, never prepare or execute that request again merely "
    "to obtain visualization IDs or verification evidence. The execution already writes Interface "
    "Visualization. Save the task conclusion once; for interface_execute, verification_call_ids "
    "may be omitted and the server will bind the latest successful interface execution. Do not "
    "call read_task_context or document search after success to discover generated record IDs. "
    "The server "
    "selects the task Workspace/environment, route, and saved account headers; never ask the "
    "user to provide a raw URL or copy saved headers. Imported read, write, destructive, and "
    "unknown operation kinds may be executed when they match the user's stated intent. Omitted "
    "address and account selections reuse the latest "
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
    RESOLVE_DATABASE_TARGET_TOOL_NAME,
    SEARCH_DATABASE_TOOL_NAME,
    EXECUTE_DATABASE_TOOL_NAME,
) = CONTEXT_ROUTER_CORE_TOOL_NAMES
(
    READ_TABLE_RELATIONS_TOOL_NAME,
    SEARCH_RELATION_TABLES_TOOL_NAME,
) = CONTEXT_ROUTER_TABLE_RELATION_TOOL_NAMES
(
    SEARCH_FORWARDING_INTERFACES_TOOL_NAME,
    READ_FORWARDING_INTERFACE_DETAIL_TOOL_NAME,
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
(
    SAVE_DATA_VISUALIZATION_QUERY_TOOL_NAME,
    EXECUTE_MAPPED_DATA_QUERY_TOOL_NAME,
) = CONTEXT_ROUTER_DATA_VISUALIZATION_TOOL_NAMES
(SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME,) = CONTEXT_ROUTER_TASK_VISUALIZATION_TOOL_NAMES
APPLY_WORKSPACE_TOOL_NAME = "apply_workspace_changes"
START_WORKSPACE_TOOL_NAME = "start_workspace"
GET_WORKSPACE_OPERATION_TOOL_NAME = "get_workspace_operation"
DISCOVER_TASK_TOOLS_TOOL_NAME = "discover_task_tools"
INVOKE_TASK_TOOL_NAME = "invoke_task_tool"
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
DISCOVER_TASK_TOOLS_TOOL_DESCRIPTION = (
    "Discover the smallest set of task-aware professional MCP actions relevant to the current "
    "goal. Returns complete input schemas, parameter descriptions, safety annotations, readiness, "
    "and immutable definition revisions. Use this after prepare_task_context when its recommended "
    "actions are insufficient or the task enters a new technical domain. This tool never returns "
    "core navigation tools prepare_task_context, search_context_documents, or "
    "read_context_document; call those directly with the same task_id."
)
INVOKE_TASK_TOOL_DESCRIPTION = (
    "Invoke one professional action returned by prepare_task_context.recommended_actions or "
    "discover_task_tools.actions. Pass the returned action name as tool_name, not action_name, "
    "and copy its definition_revision exactly. The server binds task_id, verifies the action "
    "definition revision and task capability, then executes the existing professional tool with "
    "normal tracing and policy checks. Core navigation tools are called directly and are rejected "
    "here with a direct-call correction."
)
DIRECT_CALL_ONLY_TOOL_NAMES = frozenset(
    {
        PREPARE_TOOL_NAME,
        SEARCH_CONTEXT_TOOL_NAME,
        READ_TOOL_NAME,
        DISCOVER_TASK_TOOLS_TOOL_NAME,
        INVOKE_TASK_TOOL_NAME,
        SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME,
        APPLY_WORKSPACE_TOOL_NAME,
        START_WORKSPACE_TOOL_NAME,
        GET_WORKSPACE_OPERATION_TOOL_NAME,
    }
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
    "environment, and AI source are derived from task_id. After resolve_value_candidates, pass "
    "mapping_id instead of searching database objects or relation tables again; the saved mapping "
    "supplies database, schema, and table. Pass execution_tool_call_id when a successful "
    "resolve_value_candidates or execute_database_query call already produced the data, so the "
    "visualization is recorded as succeeded instead of pending. Without mapping_id, supply the "
    "exact published relation table explicitly. Repeated identical saves within one task are "
    "idempotent."
)
EXECUTE_MAPPED_DATA_QUERY_TOOL_DESCRIPTION = (
    "Atomically execute one published business-value mapping in the task environment and save "
    "the resulting condition to Data Visualization. This is the preferred data-query path: it "
    "needs no environment, database alias, schema discovery, raw SQL, or second save call. "
    "include_record=true (the default) also returns the selected complete row from the mapping's "
    "authorized table. Use selection=random only when the user's wording explicitly asks for a "
    "random result. A successful primary result sets goal_completed=true; then perform only the "
    "returned terminal next_action and do not resolve a database or execute raw SQL."
)
SAVE_TASK_VISUALIZATION_RESULT_TOOL_DESCRIPTION = (
    "Save or update the structured conclusion shown by AI Task Visualization for the current "
    "task. Use investigating only for a meaningful interim conclusion, resolved when the task "
    "was completed and verified, or failed when the task could not be completed. Resolved requires "
    "at least one real verification outcome; failed requires a concrete root cause. Include only "
    "evidence-backed summaries, Workspace-relative code locations, safe suggested actions, and "
    "verification outcomes. For resolved, pass verification_call_ids referencing successful calls "
    "from this task; the server converts them into verified evidence. For interface_execute, omit "
    "verification_call_ids to bind the latest successful execute_forwarding_request automatically; "
    "never repeat the interface request just to obtain an ID. Do not hand-write "
    "verification objects. Repeated calls update the same task record and increase its revision."
)
PREPARE_TOOL_DESCRIPTION = (
    "First classify the user's primary intent and pass intent_type. Locate the registered "
    "workspace for cwd, create a server-side task number, and "
    "return a task-local document projection. A real workspace AGENTS.md is always level 1; "
    "without one, the active project or synthetic workspace entry is level 1. The result has "
    "at most two explicit descendant levels. Nodes contain only document_id, summary, and "
    "children. Unrelated documents and deeper descendants are omitted from prepare but remain "
    "available through workspace-wide search_context_documents and read_context_document. "
    "Omit environment to use local, or pass any environment registered by the Workspace for "
    "this task only. The returned execution_contract is authoritative for mutation policy, "
    "required MCP steps, and visualization targets. A bug_investigate task is read-only; a "
    "bug_fix task with error_signal=true must inspect a registered container before applying "
    "changes. access states which task capabilities "
    "are available. Database aliases and environment config are intentionally omitted; request "
    "them only when needed with read_task_context. access includes middleware when live Nacos "
    "middleware context may be requested with read_middleware_context."
)
READ_TASK_CONTEXT_TOOL_DESCRIPTION = (
    "Read database aliases and/or generic saved environment JSON for an existing task. "
    "Do not call this before search_value_mappings or resolve_value_candidates: published "
    "mappings already own their database alias and resolve it in the task environment. Call it "
    "only when no mapping fits and raw database discovery/querying is required, or when generic "
    "environment JSON is explicitly needed. "
    "This is not the authoritative or live source for Redis, MQ, Elasticsearch, MinIO, or "
    "other Nacos-managed middleware; use read_middleware_context for those details. Request "
    "only the sections needed. Environment config is sensitive local-only context and must "
    "never be copied into logs or unrelated output."
)
READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION = (
    "Authoritative live source for Redis, MQ, Elasticsearch, MinIO, job scheduler, object "
    "storage, and other Nacos-managed middleware connection or diagnosis tasks. Call this after "
    "prepare_task_context with the current task_id instead of inferring runtime values from "
    "application files or generic environment JSON. It always inherits the environment selected "
    "and frozen by prepare_task_context. "
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
    "current task. Pass only a database_context_id returned by resolve_database_target. Use "
    "names first and request summary/full details only when needed."
)
EXECUTE_DATABASE_TOOL_DESCRIPTION = (
    "Execute exactly one bounded read-only SQL statement against a database_context_id returned "
    "by resolve_database_target. Do not use this to repeat a business-value mapping resolver or to "
    "implement random selection after resolve_value_candidates; use selection=random there. "
    "Connection details and query limits are enforced server-side."
)
RESOLVE_DATABASE_TARGET_TOOL_DESCRIPTION = (
    "Resolve a task-bound database target before schema discovery or raw SQL. Prefer mapping_id "
    "when a published business mapping exists; otherwise pass a table name or business hint. "
    "The returned opaque database_context_id is bound to the task environment and physical "
    "database, expires automatically, and is the only database selector accepted by database tools."
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
    "Search published business-value mappings for data queries or interface parameters in the "
    "current task Workspace. Provide a Chinese business keyword, an exact imported interface ID "
    "and parameter location/path, or both. Use this before table/schema discovery whenever a "
    "business ID, code, number, or named entity may already be mapped. Results explain the "
    "configured read-only resolver. Calls without interface_id omit binding details and return "
    "only their count; calls for an exact interface return at most 20 matching bindings. No "
    "database query is executed."
)
RESOLVE_VALUE_CANDIDATES_TOOL_DESCRIPTION = (
    "Resolve up to 10 candidate values with one published mapping's saved database alias, table, "
    "columns, and fixed filters. Omit environment to inherit the task environment; an explicit "
    "environment must match the task. selection=default preserves resolver order; "
    "selection=random samples from a bounded pool of at most 10 candidates and never performs an "
    "unbounded database random sort. For requests such as random/随机/任意一个, set "
    "selection=random and set limit to the number requested. This tool does not require a prior "
    "read_task_context call. The response is authoritative for its database, schema, table, "
    "display fields, and next action; after success do not call search_database_objects or "
    "search_relation_tables. The caller cannot provide SQL, connection details, or an "
    "unconfigured data source."
)
SEARCH_FORWARDING_INTERFACES_TOOL_DESCRIPTION = (
    "Search imported interfaces in the task Workspace and report whether each is callable in "
    "the task environment. Pass the user's original business wording. Results may include a "
    "curated business entity, action, scenario, aliases, CRUD type, and source-backed table "
    "effects. Use score_breakdown, match_reasons, and mismatches to understand the ranking "
    "instead of asking for manual confirmation. "
    "Prefer candidates whose business action and entity both match the request instead of choosing "
    "only by HTTP method, path, or a generic interface name. Query interfaces expose only tables "
    "proved to contribute to the returned response; mutation interfaces omit validation reads. "
    "search_event_id records the initial ranking and is automatically linked when a result is "
    "prepared and executed; the caller does not pass it to later tools."
)
READ_FORWARDING_INTERFACE_DETAIL_TOOL_DESCRIPTION = (
    "Read one imported interface's shared semantic detail after search. Returns business entity, "
    "action, scenario, aliases, positive and negative examples, CRUD type, request contract, "
    "bounded response-contract summary, published parameter mappings, source-backed table effects, "
    "task-intent match evidence, and current environment readiness. It never returns forwarding "
    "URLs, saved request headers, credentials, or raw request/response history. Use it when search "
    "candidates are ambiguous or the user asks about parameters, response fields, or affected "
    "tables."
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
    "values. When no successful selection exists, a sole current address or identity is selected; "
    "multiple candidates require an explicit address/account/role from the caller. Returns a "
    "short-lived immutable plan only when all required values are present. "
    "Saved request-header values are never returned."
)
EXECUTE_FORWARDING_REQUEST_TOOL_DESCRIPTION = (
    "Execute exactly one prepared, unexpired forwarding plan. Imported read and write operations, "
    "including destructive or unclassified operations, are executable; the caller must select an "
    "interface that matches the user's stated intent and echo the "
    "plan request_sha256; raw URLs, methods, request headers, and arbitrary overrides are "
    "forbidden. Repeating the same plan, or preparing an equivalent request after it already "
    "succeeded in the same task and unchanged forwarding configuration, reuses the saved execution "
    "without sending a second HTTP request or creating another Interface Visualization record."
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
    destructiveHint=True,
    idempotentHint=True,
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
                tool_call_id = trace_service.record_completed_call(
                    task_id=task_id,
                    server_name=TRACE_SERVER_NAME,
                    tool_name=name,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=_elapsed_ms(started_ns),
                    request_summary=request_summary,
                    result_summary=_result_summary(name, payload),
                )
                _attach_tool_call_id(result, tool_call_id)
            return result

        trace_name, trace_arguments = _effective_trace_call(name, arguments)
        request_summary = _request_summary(trace_name, trace_arguments)
        task_id = _positive_int(trace_arguments.get("task_id"))
        if task_id is None and trace_name == GET_WORKSPACE_OPERATION_TOOL_NAME:
            operation_id = trace_arguments.get("operation_id")
            if isinstance(operation_id, str) and self._operation_task_resolver is not None:
                try:
                    task_id = self._operation_task_resolver(operation_id)
                except Exception:
                    task_id = None
        tool_call_id = (
            trace_service.start_call(
                task_id=task_id,
                server_name=TRACE_SERVER_NAME,
                tool_name=trace_name,
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
                tool_name=trace_name,
                arguments=trace_arguments,
            )
        argument_error = _argument_error_summary(trace_name, trace_arguments)
        try:
            if argument_error is not None:
                raise ToolError(f"invalid_tool_arguments: {argument_error['message']}")
            result = await super().call_tool(name, arguments)
        except asyncio.CancelledError:
            if payload_service is not None:
                payload_service.capture_response(
                    tool_call_id,
                    tool_name=trace_name,
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
                    tool_name=trace_name,
                    status="error",
                    payload={
                        "error": {
                            "code": error_code,
                            "message": _database_payload_error_message(trace_name, error_code),
                        }
                    },
                )
            trace_service.finish_call(
                tool_call_id,
                status="error",
                finished_at=datetime.now(UTC),
                duration_ms=_elapsed_ms(started_ns),
                result_summary=argument_error or _safe_error_summary(error_code),
                error_code=error_code,
            )
            raise
        else:
            payload = _structured_payload(result)
            if bool(getattr(result, "isError", False)):
                if payload_service is not None:
                    payload_service.capture_response(
                        tool_call_id,
                        tool_name=trace_name,
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
                effective_payload = (
                    payload.get("result")
                    if name == INVOKE_TASK_TOOL_NAME and isinstance(payload.get("result"), dict)
                    else payload
                )
                if payload_service is not None:
                    payload_service.capture_response(
                        tool_call_id,
                        tool_name=trace_name,
                        status="ok",
                        payload=effective_payload,
                    )
                trace_service.finish_call(
                    tool_call_id,
                    status="ok",
                    finished_at=datetime.now(UTC),
                    duration_ms=_elapsed_ms(started_ns),
                    result_summary=_result_summary(trace_name, effective_payload),
                )
                _attach_tool_call_id(result, tool_call_id)
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
    database_context_service: DatabaseContextService | None = None,
    task_repository: TaskReader | None = None,
    task_capability_service: TaskCapabilityService | None = None,
) -> FastMCP:
    forwarding_execution_limiter = asyncio.Semaphore(4)
    task_tool_registry = TaskToolRegistry()
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
        ctx: Context,
        agent_name: Annotated[str | None, Field(max_length=64)] = None,
        environment: Annotated[
            str | None,
            Field(
                max_length=32,
                pattern=r"^[a-z][a-z0-9_-]{0,31}$",
                description=(
                    "Optional task-only environment assertion. Omit to detect a registered "
                    "environment alias in task; local is used only when none is mentioned."
                ),
            ),
        ] = None,
        intent_type: Literal[
            "interface_discovery",
            "interface_execute",
            "data_query",
            "task_execute",
            "bug_investigate",
            "bug_fix",
            "code_change",
        ]
        | None = None,
        error_signal: Annotated[
            bool,
            Field(
                strict=True,
                description=(
                    "True only for bug_investigate or bug_fix when the user provides or points "
                    "to runtime error evidence."
                ),
            ),
        ] = False,
        intent_summary: Annotated[
            str | None,
            Field(
                max_length=1000,
                description=(
                    "Short statement of requested action and whether code changes are allowed."
                ),
            ),
        ] = None,
        capability_hints: Annotated[
            list[
                Literal[
                    "context",
                    "database",
                    "data",
                    "interface",
                    "logs",
                    "middleware",
                    "relation",
                    "mapping",
                ]
            ]
            | None,
            Field(
                default=None,
                min_length=1,
                max_length=8,
                description=(
                    "Optional read-domain hints explicitly implied by the user request. They may "
                    "only expand safe read capabilities and never grant code or runtime mutation."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        try:
            request_agent_name = _request_agent_name(ctx)
            result = preparation_service.prepare(
                task=task,
                cwd=cwd,
                agent_name=request_agent_name or agent_name,
                environment=environment,
                intent_type=intent_type,
                error_signal=error_signal,
                intent_summary=intent_summary,
            )
        except ContextPreparationError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        payload = result.model_dump(exclude_none=True)
        if task_capability_service is not None and task_repository is not None:
            try:
                enabled = task_capability_service.initialize(result.task_id, capability_hints)
                task_record = task_repository.get_task(result.task_id)
            except (TaskCapabilityError, TaskRepositoryError) as exc:
                code = getattr(exc, "code", "task_capabilities_unavailable")
                raise ToolError(f"{code}: {exc}") from exc
            payload["enabled_capabilities"] = enabled
            payload["recommended_actions"] = task_tool_registry.discover(
                intent_type=task_record.intent_type,
                query=task,
                enabled_capabilities=set(enabled),
                limit=5,
                task_id=result.task_id,
            )
        return payload

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
                environment=None,
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
        name=RESOLVE_DATABASE_TARGET_TOOL_NAME,
        description=RESOLVE_DATABASE_TARGET_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def resolve_database_target(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        mapping_id: Annotated[str | None, Field(min_length=1, max_length=36)] = None,
        table_name: Annotated[str | None, Field(min_length=1, max_length=255)] = None,
        business_hint: Annotated[str | None, Field(min_length=1, max_length=500)] = None,
    ) -> dict[str, object]:
        if database_context_service is None:
            raise ToolError("database_tools_disabled: 数据库上下文工具当前不可用")
        if mapping_id is None and table_name is None and business_hint is None:
            raise ToolError(
                "invalid_tool_arguments: mapping_id、table_name、business_hint 至少提供一个"
            )
        try:
            return database_context_service.resolve_target(
                task_id=task_id,
                mapping_id=mapping_id,
                table_name=table_name,
                business_hint=business_hint,
            )
        except DatabaseContextError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=SEARCH_DATABASE_TOOL_NAME,
        description=SEARCH_DATABASE_TOOL_DESCRIPTION,
        annotations=DATABASE_TOOL_ANNOTATIONS,
    )
    def search_database_objects(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        database_context_id: Annotated[
            str,
            Field(min_length=36, max_length=36),
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
            if database_context_service is None:
                raise ToolError("database_tools_disabled: 数据库上下文工具当前不可用")
            database = database_context_service.alias_for_context(
                task_id=task_id,
                database_context_id=database_context_id,
            )
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
        except DatabaseContextError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        except DatabaseAccessError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=EXECUTE_DATABASE_TOOL_NAME,
        description=EXECUTE_DATABASE_TOOL_DESCRIPTION,
        annotations=DATABASE_TOOL_ANNOTATIONS,
    )
    def execute_database_query(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        database_context_id: Annotated[
            str,
            Field(min_length=36, max_length=36),
        ],
        sql: Annotated[str, Field(min_length=1, max_length=200_000)],
    ) -> dict[str, object]:
        if database_query_service is None:
            raise ToolError("database_tools_disabled: 数据库工具当前不可用")
        try:
            if database_context_service is None:
                raise ToolError("database_tools_disabled: 数据库上下文工具当前不可用")
            database = database_context_service.alias_for_context(
                task_id=task_id,
                database_context_id=database_context_id,
            )
            return database_query_service.execute(task_id=task_id, database=database, sql=sql)
        except DatabaseContextError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
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
        keyword: Annotated[str, Field(min_length=1, max_length=500)],
        mapping_id: Annotated[str | None, Field(min_length=1, max_length=36)] = None,
        database_key: Annotated[
            str | None,
            Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"),
        ] = None,
        schema_name: Annotated[str | None, Field(min_length=1, max_length=255)] = None,
        table_name: Annotated[str | None, Field(min_length=1, max_length=255)] = None,
        execution_tool_call_id: Annotated[int | None, Field(ge=1, strict=True)] = None,
    ) -> dict[str, object]:
        if ai_data_visualization_service is None:
            raise ToolError("data_visualization_disabled: 数据可视化 MCP 当前不可用")
        try:
            if mapping_id is not None:
                if value_mapping_service is None:
                    raise ToolError("value_mapping_disabled: 业务值映射 MCP 当前不可用")
                source = value_mapping_service.source_for_task(mapping_id, task_id=task_id)
                database_key = str(source["database_alias"])
                schema_name = str(source["schema_name"])
                table_name = str(source["table_name"])
            if database_key is None or schema_name is None or table_name is None:
                raise ToolError(
                    "invalid_tool_arguments: 请传 mapping_id，或完整传入 database_key、"
                    "schema_name、table_name"
                )
            source_call = None
            if execution_tool_call_id is not None:
                _verified_tool_calls(
                    trace_service,
                    task_id=task_id,
                    call_ids=[execution_tool_call_id],
                    allowed_tools={RESOLVE_VALUE_CANDIDATES_TOOL_NAME, EXECUTE_DATABASE_TOOL_NAME},
                )
                trace = trace_service.get_trace(task_id) if trace_service is not None else None
                source_call = next(
                    call
                    for call in (trace.calls if trace is not None else [])
                    if call.tool_call_id == execution_tool_call_id
                )
            result = ai_data_visualization_service.create_for_task(
                task_id=task_id,
                description=description,
                database_key=database_key,
                schema_name=schema_name,
                table_name=table_name,
                keyword=keyword,
            )
            if source_call is not None:
                result_summary = source_call.result_summary or {}
                result_count = result_summary.get("returned_rows")
                if not isinstance(result_count, int):
                    result_count = result_summary.get("returned_count")
                ai_data_visualization_service.record_execution(
                    record_id=result.id,
                    workspace_id=result.workspace_id,
                    environment=result.environment,
                    succeeded=True,
                    result_card_count=None,
                    result_row_count=result_count if isinstance(result_count, int) else None,
                    duration_ms=source_call.duration_ms or 0,
                    error_summary=None,
                )
                latest = ai_data_visualization_service.latest(
                    workspace_id=result.workspace_id,
                    environment=result.environment,
                    task_id=task_id,
                ).record
                if latest is not None:
                    result = latest
            return result.model_dump(mode="json", exclude_none=True)
        except (AiDataVisualizationError, ValueMappingError) as exc:
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
        verification_call_ids: Annotated[
            list[Annotated[int, Field(ge=1, strict=True)]] | None,
            Field(default=None, min_length=1, max_length=20),
        ] = None,
    ) -> dict[str, object]:
        if ai_task_visualization_service is None:
            raise ToolError("task_visualization_disabled: 任务可视化 MCP 当前不可用")
        try:
            effective_call_ids = verification_call_ids or _inferred_verification_call_ids(
                trace_service,
                task_repository,
                task_id=task_id,
                status=status,
            )
            verified_calls = _verified_tool_calls(
                trace_service,
                task_id=task_id,
                call_ids=effective_call_ids,
            )
            result = ai_task_visualization_service.save_result(
                task_id,
                AiTaskResultWrite(
                    status=status,
                    summary=summary,
                    root_cause=root_cause,
                    code_locations=code_locations or [],
                    suggested_actions=suggested_actions or [],
                    verification=verified_calls,
                ),
            )
            payload = result.model_dump(mode="json", exclude_none=True)
            if effective_call_ids:
                payload["verification_call_ids"] = effective_call_ids
            return payload
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
        keyword: Annotated[str, Field(max_length=240)] = "",
        limit: Annotated[int, Field(ge=1, le=10, strict=True)] = 10,
        selection: Literal["default", "random"] = "default",
    ) -> dict[str, object]:
        if value_mapping_service is None:
            raise ToolError("value_mapping_disabled: 业务值映射 MCP 当前不可用")
        try:
            result = value_mapping_service.resolve_for_task(
                mapping_id,
                task_id=task_id,
                environment=None,
                keyword=keyword,
                limit=limit,
                selection=selection,
            )
            candidates = result.get("candidates")
            first_candidate = candidates[0] if isinstance(candidates, list) and candidates else None
            candidate_value = (
                first_candidate.get("value") if isinstance(first_candidate, dict) else None
            )
            visualization_keyword = (
                str(candidate_value) if candidate_value is not None else keyword.strip()
            )
            call_id = current_tool_call_id()
            next_arguments: dict[str, object] = {
                "task_id": task_id,
                "description": f"{str(result.get('name') or '业务数据')}查询",
                "keyword": visualization_keyword,
                "mapping_id": mapping_id,
            }
            if call_id is not None:
                next_arguments["execution_tool_call_id"] = call_id
            existing_next_action = result.get("next_action")
            result["next_action"] = {
                **(existing_next_action if isinstance(existing_next_action, dict) else {}),
                "tool": SAVE_DATA_VISUALIZATION_QUERY_TOOL_NAME,
                "arguments": next_arguments,
                "ready": bool(visualization_keyword and call_id is not None),
            }
            return result
        except ValueMappingError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=EXECUTE_MAPPED_DATA_QUERY_TOOL_NAME,
        description=EXECUTE_MAPPED_DATA_QUERY_TOOL_DESCRIPTION,
        annotations=LOG_INSPECTION_TOOL_ANNOTATIONS,
    )
    def execute_mapped_data_query(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        mapping_id: Annotated[str, Field(min_length=1, max_length=36)],
        description: Annotated[str, Field(min_length=1, max_length=2000)],
        keyword: Annotated[str, Field(max_length=240)] = "",
        limit: Annotated[int, Field(ge=1, le=10, strict=True)] = 10,
        selection: Literal["default", "random"] = "default",
        include_record: Annotated[
            bool,
            Field(description="返回命中值对应的完整记录，避免再次解析数据库或猜字段。"),
        ] = True,
        purpose: Annotated[
            Literal["primary_visualization", "supporting_evidence"] | None,
            Field(
                description=(
                    "数据查询主任务使用 primary_visualization；代码开发和 Bug 任务默认使用 "
                    "supporting_evidence，避免污染数据可视化列表。"
                )
            ),
        ] = None,
    ) -> dict[str, object]:
        if value_mapping_service is None:
            raise ToolError("value_mapping_disabled: 业务值映射 MCP 当前不可用")
        try:
            effective_purpose = purpose
            if effective_purpose is None:
                effective_purpose = "primary_visualization"
                if task_repository is not None:
                    task_record = task_repository.get_task(task_id)
                    if task_record.intent_type != "data_query":
                        effective_purpose = "supporting_evidence"
            result = value_mapping_service.resolve_for_task(
                mapping_id,
                task_id=task_id,
                environment=None,
                keyword=keyword,
                limit=limit,
                selection=selection,
                include_record=include_record,
            )
            candidates = result.get("candidates")
            first = candidates[0] if isinstance(candidates, list) and candidates else None
            selected_value = first.get("value") if isinstance(first, dict) else None
            if selected_value is None:
                return {
                    **result,
                    "status": "no_result",
                    "purpose": effective_purpose,
                    "goal_completed": False,
                    "visualization": None,
                }
            if effective_purpose == "supporting_evidence":
                return {
                    **result,
                    "status": "succeeded",
                    "purpose": effective_purpose,
                    "goal_completed": False,
                    "visualization": None,
                }
            if ai_data_visualization_service is None:
                raise ToolError("data_visualization_disabled: 数据可视化 MCP 当前不可用")
            source = value_mapping_service.source_for_task(mapping_id, task_id=task_id)
            visualization = ai_data_visualization_service.create_for_mapping_task(
                task_id=task_id,
                description=description,
                database_key=str(source["database_alias"]),
                schema_name=str(source["schema_name"]),
                table_name=str(source["table_name"]),
                keyword=str(selected_value),
            )
            returned_count = result.get("returned_count")
            elapsed_ms = result.get("elapsed_ms")
            ai_data_visualization_service.record_execution(
                record_id=visualization.id,
                workspace_id=visualization.workspace_id,
                environment=visualization.environment,
                succeeded=True,
                result_card_count=None,
                result_row_count=(returned_count if isinstance(returned_count, int) else None),
                duration_ms=elapsed_ms if isinstance(elapsed_ms, int) else 0,
            )
            saved = ai_data_visualization_service.latest(
                workspace_id=visualization.workspace_id,
                environment=visualization.environment,
                task_id=task_id,
            ).record
            call_id = current_tool_call_id()
            return {
                **result,
                "status": "succeeded",
                "purpose": effective_purpose,
                "goal_completed": True,
                "prohibited_followups": [
                    RESOLVE_DATABASE_TARGET_TOOL_NAME,
                    SEARCH_DATABASE_TOOL_NAME,
                    EXECUTE_DATABASE_TOOL_NAME,
                    SAVE_DATA_VISUALIZATION_QUERY_TOOL_NAME,
                ],
                "next_action": {
                    "tool": SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME,
                    "arguments": {
                        "task_id": task_id,
                        "status": "resolved",
                        "summary": f"{description}：已查询并保存数据可视化结果",
                        "verification_call_ids": [call_id] if call_id is not None else [],
                    },
                    "ready": call_id is not None,
                    "terminal": True,
                },
                "visualization": (
                    saved.model_dump(mode="json", exclude_none=True) if saved else None
                ),
            }
        except TaskRepositoryError as exc:
            raise ToolError(f"task_not_found: {exc}") from exc
        except (ValueMappingError, AiDataVisualizationError) as exc:
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
        name=READ_FORWARDING_INTERFACE_DETAIL_TOOL_NAME,
        description=READ_FORWARDING_INTERFACE_DETAIL_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def read_forwarding_interface_detail(
        task_id: Annotated[int, Field(ge=1, strict=True)],
        interface_id: Annotated[str, Field(min_length=1, max_length=36)],
    ) -> dict[str, object]:
        if interface_forwarding_context_service is None:
            raise ToolError("interface_forwarding_disabled: 接口转发 MCP 当前不可用")
        try:
            return interface_forwarding_context_service.detail(
                task_id=task_id,
                interface_id=interface_id,
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
                environment=None,
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
        name=DISCOVER_TASK_TOOLS_TOOL_NAME,
        description=DISCOVER_TASK_TOOLS_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
    )
    def discover_task_tools(
        task_id: Annotated[
            int,
            Field(
                ge=1,
                strict=True,
                description="prepare_task_context 返回的当前任务 ID。",
            ),
        ],
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=1000,
                description="当前要完成的具体步骤或技术目标，保留关键业务词。",
            ),
        ],
        capability_hints: Annotated[
            list[
                Literal[
                    "context",
                    "database",
                    "data",
                    "interface",
                    "logs",
                    "middleware",
                    "relation",
                    "mapping",
                ]
            ]
            | None,
            Field(
                default=None,
                min_length=1,
                max_length=8,
                description="用户目标明确涉及的只读能力域；不会授予代码或运行时变更能力。",
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=10, strict=True, description="最多返回的相关动作数。"),
        ] = 5,
    ) -> dict[str, Any]:
        if task_repository is None or task_capability_service is None:
            raise ToolError("task_tool_discovery_disabled: 渐进式任务工具发现当前不可用")
        try:
            task_record = task_repository.get_task(task_id)
            enabled = task_capability_service.initialize(task_id, capability_hints)
        except (TaskRepositoryError, TaskCapabilityError) as exc:
            code = getattr(exc, "code", "task_tool_discovery_failed")
            raise ToolError(f"{code}: {exc}") from exc
        actions = task_tool_registry.discover(
            intent_type=task_record.intent_type,
            query=query,
            enabled_capabilities=set(enabled),
            limit=limit,
            task_id=task_id,
        )
        return {
            "task_id": task_id,
            "intent_type": task_record.intent_type,
            "query": query,
            "enabled_capabilities": enabled,
            "actions": actions,
        }

    @server.tool(
        name=INVOKE_TASK_TOOL_NAME,
        description=INVOKE_TASK_TOOL_DESCRIPTION,
        annotations=LOG_INSPECTION_TOOL_ANNOTATIONS,
    )
    async def invoke_task_tool(
        task_id: Annotated[
            int,
            Field(
                ge=1,
                strict=True,
                description="prepare_task_context 返回的当前任务 ID。",
            ),
        ],
        tool_name: Annotated[
            str,
            Field(
                min_length=1,
                max_length=100,
                description="recommended_actions 或 discover_task_tools 返回的动作 name。",
            ),
        ],
        arguments: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "目标动作的参数对象，不包含 task_id；字段必须符合发现结果中的 input_schema。"
                ),
            ),
        ],
        definition_revision: Annotated[
            str,
            Field(
                min_length=64,
                max_length=64,
                pattern=r"^[0-9a-f]{64}$",
                description="发现结果返回的 definition_revision，防止按过期 Schema 执行。",
            ),
        ],
        ctx: Context,
    ) -> dict[str, Any]:
        if task_capability_service is None:
            raise ToolError("task_tool_invocation_disabled: 渐进式任务工具调用当前不可用")
        definition = task_tool_registry.get(tool_name)
        if definition is None:
            if tool_name in DIRECT_CALL_ONLY_TOOL_NAMES:
                raise ToolError(
                    "core_tool_direct_call_required: "
                    f"{tool_name} 是公共直连工具，不会由 discover_task_tools 返回，也不能经 "
                    "invoke_task_tool 调用；请使用相同 task_id 直接调用该工具"
                )
            raise ToolError(f"task_tool_not_found: 未发现可调用动作 {tool_name}")
        if definition.definition_revision != definition_revision:
            raise ToolError("task_tool_definition_changed: 工具定义已更新，请重新发现后再调用")
        if "task_id" in arguments:
            raise ToolError("invalid_tool_arguments: arguments 不允许包含 task_id")
        try:
            task_capability_service.ensure_allowed(task_id, definition.spec.capability)
        except TaskCapabilityError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        result = await definition.tool.run(
            {"task_id": task_id, **arguments},
            context=ctx,
            convert_result=False,
        )
        return {
            "task_id": task_id,
            "tool_name": tool_name,
            "capability": definition.spec.capability,
            "status": "succeeded",
            "definition_revision": definition.definition_revision,
            "result": result,
        }

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

    for tool_name in task_tool_registry.names:
        tool = server._tool_manager.get_tool(tool_name)
        if tool is None:
            raise RuntimeError(f"渐进式 MCP 注册表引用了未注册工具：{tool_name}")
        task_tool_registry.bind(tool_name, tool)

    return server


def _effective_trace_call(
    name: str,
    arguments: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if name != INVOKE_TASK_TOOL_NAME:
        return name, arguments
    target_name = arguments.get("tool_name")
    target_arguments = arguments.get("arguments")
    task_id = arguments.get("task_id")
    if not isinstance(target_name, str) or not isinstance(target_arguments, dict):
        return name, arguments
    return target_name, {"task_id": task_id, **target_arguments}


def _elapsed_ms(started_ns: int) -> int:
    return max(0, (perf_counter_ns() - started_ns) // 1_000_000)


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _request_agent_name(ctx: Context) -> str | None:
    """Read the configured MCP client identity from the current HTTP request."""
    try:
        request = ctx.request_context.request
    except ValueError:
        return None
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    value = headers.get(MCP_CLIENT_NAME_HEADER)
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized if normalized in MCP_CLIENT_AGENT_NAMES else None


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


def _attach_tool_call_id(result: object, tool_call_id: int | None) -> None:
    """Expose the persisted trace ID in the structured MCP response for later tool linking."""
    if tool_call_id is None:
        return
    payload = _structured_payload(result)
    payload["tool_call_id"] = tool_call_id


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
            "database_context_id": _safe_string(arguments.get("database_context_id"), 36),
            "object_type": _safe_string(arguments.get("object_type"), 32),
            "detail": _safe_string(arguments.get("detail"), 16),
            "limit": arguments.get("limit") if isinstance(arguments.get("limit"), int) else None,
            "schema_scoped": bool(arguments.get("schema")),
            "table_scoped": bool(arguments.get("table")),
        }
    if name == EXECUTE_DATABASE_TOOL_NAME:
        sql = arguments.get("sql")
        return {
            "database_context_id": _safe_string(arguments.get("database_context_id"), 36),
            "sql_sha256": (
                hashlib.sha256(sql.strip().encode("utf-8")).hexdigest()
                if isinstance(sql, str)
                else None
            ),
        }
    if name == SAVE_DATA_VISUALIZATION_QUERY_TOOL_NAME:
        return {
            "mapping_id": _safe_string(arguments.get("mapping_id"), 36),
            "database": _safe_string(arguments.get("database_key"), 64),
            "schema_scoped": bool(arguments.get("schema_name")),
            "table_scoped": bool(arguments.get("table_name")),
            "execution_tool_call_id": _positive_int(arguments.get("execution_tool_call_id")),
            "keyword_characters": (
                len(arguments["keyword"]) if isinstance(arguments.get("keyword"), str) else 0
            ),
        }
    if name == SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME:
        locations = arguments.get("code_locations")
        actions = arguments.get("suggested_actions")
        verification = arguments.get("verification")
        verification_call_ids = arguments.get("verification_call_ids")
        return {
            "status": _safe_string(arguments.get("status"), 20),
            "summary_characters": (
                len(arguments["summary"]) if isinstance(arguments.get("summary"), str) else 0
            ),
            "root_cause_supplied": isinstance(arguments.get("root_cause"), str),
            "code_location_count": len(locations) if isinstance(locations, list) else 0,
            "suggested_action_count": len(actions) if isinstance(actions, list) else 0,
            "verification_count": len(verification) if isinstance(verification, list) else 0,
            "verification_call_count": (
                len(verification_call_ids) if isinstance(verification_call_ids, list) else 0
            ),
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
            "selection": _safe_string(arguments.get("selection"), 16) or "default",
        }
    if name == EXECUTE_MAPPED_DATA_QUERY_TOOL_NAME:
        keyword = arguments.get("keyword")
        return {
            "mapping_id": _safe_string(arguments.get("mapping_id"), 36),
            "keyword_sha256": (
                hashlib.sha256(keyword.strip().encode("utf-8")).hexdigest()
                if isinstance(keyword, str) and keyword.strip()
                else None
            ),
            "limit": arguments.get("limit") if isinstance(arguments.get("limit"), int) else 10,
            "selection": _safe_string(arguments.get("selection"), 16) or "default",
            "include_record": arguments.get("include_record", True) is True,
            "purpose": _safe_string(arguments.get("purpose"), 32),
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
    if name == READ_FORWARDING_INTERFACE_DETAIL_TOOL_NAME:
        return {"interface_id": _safe_string(arguments.get("interface_id"), 36)}
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
    if name == EXECUTE_MAPPED_DATA_QUERY_TOOL_NAME:
        return {
            "status": _safe_string(payload.get("status"), 24),
            "purpose": _safe_string(payload.get("purpose"), 32),
            "goal_completed": payload.get("goal_completed") is True,
            "returned_count": (
                payload.get("returned_count")
                if isinstance(payload.get("returned_count"), int)
                else None
            ),
            "record_count": (
                payload.get("record_count")
                if isinstance(payload.get("record_count"), int)
                else None
            ),
            "record_truncated": payload.get("record_truncated") is True,
        }
    if name == SAVE_DATA_VISUALIZATION_QUERY_TOOL_NAME:
        return {
            "execution_status": _safe_string(payload.get("execution_status"), 16),
            "result_row_count": (
                payload.get("result_row_count")
                if isinstance(payload.get("result_row_count"), int)
                else None
            ),
            "task_linked": isinstance(payload.get("task_id"), int),
        }
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
            "selection": _safe_string(payload.get("selection"), 16) or "default",
            "candidate_pool_count": (
                payload.get("candidate_pool_count")
                if isinstance(payload.get("candidate_pool_count"), int)
                else None
            ),
            "truncated": payload.get("truncated") is True,
        }
    if name == SEARCH_FORWARDING_INTERFACES_TOOL_NAME:
        return {
            "returned_count": payload.get("returned_count", 0),
            "environment": _safe_string(payload.get("environment"), 32),
            "match_confidence": _safe_string(payload.get("match_confidence"), 16),
            "goal_completed": payload.get("goal_completed") is True,
            "next_action": _safe_string(payload.get("next_action"), 64),
        }
    if name == READ_FORWARDING_INTERFACE_DETAIL_TOOL_NAME:
        assessment = payload.get("selection_assessment")
        readiness = payload.get("execution_readiness")
        return {
            "environment": _safe_string(payload.get("environment"), 32),
            "match_score": (
                assessment.get("match_score") if isinstance(assessment, dict) else None
            ),
            "callable": readiness.get("callable") if isinstance(readiness, dict) else None,
            "goal_completed": payload.get("goal_completed") is True,
            "next_action": _safe_string(payload.get("next_action"), 64),
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
            "deduplicated": payload.get("deduplicated") is True,
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


def _verified_tool_calls(
    trace_service: McpTraceService | None,
    *,
    task_id: int,
    call_ids: list[int],
    allowed_tools: set[str] | None = None,
) -> list[AiTaskVerificationItem]:
    if not call_ids:
        return []
    if trace_service is None:
        raise ToolError("verification_unavailable: MCP 调用记录当前不可用")
    try:
        trace = trace_service.get_trace(task_id)
    except Exception as exc:
        raise ToolError("verification_unavailable: MCP 调用记录读取失败") from exc
    calls = {call.tool_call_id: call for call in trace.calls}
    verified: list[AiTaskVerificationItem] = []
    for call_id in dict.fromkeys(call_ids):
        call = calls.get(call_id)
        if call is None or call.status != "ok":
            raise ToolError(f"invalid_verification_call: 调用 {call_id} 不属于当前任务或尚未成功")
        if call.tool_name == SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME or (
            allowed_tools is not None and call.tool_name not in allowed_tools
        ):
            raise ToolError(f"invalid_verification_call: 调用 {call_id} 不能作为当前结果的验证证据")
        summary = call.result_summary or {}
        count = summary.get("returned_rows")
        if not isinstance(count, int):
            count = summary.get("returned_count")
        suffix = f"，返回 {count} 条" if isinstance(count, int) else ""
        verified.append(
            AiTaskVerificationItem(
                type="mcp_call",
                description=f"{call.tool_name} 成功调用",
                result=f"已验证当前任务调用 #{call_id}{suffix}",
                tool_call_id=call_id,
            )
        )
    return verified


def _inferred_verification_call_ids(
    trace_service: McpTraceService | None,
    task_repository: TaskReader | None,
    *,
    task_id: int,
    status: str,
) -> list[int]:
    if status != "resolved" or trace_service is None or task_repository is None:
        return []
    try:
        task = task_repository.get_task(task_id)
        trace = trace_service.get_trace(task_id)
    except Exception:
        return []
    if task.intent_type != "interface_execute":
        return []
    for call in reversed(trace.calls):
        summary = call.result_summary or {}
        if (
            call.status == "ok"
            and call.tool_name == EXECUTE_FORWARDING_REQUEST_TOOL_NAME
            and summary.get("success") is True
        ):
            return [call.tool_call_id]
    return []


def _argument_error_summary(name: str, arguments: dict[str, Any]) -> dict[str, object] | None:
    missing: list[str] = []
    invalid: list[str] = []
    allowed_values: dict[str, list[str]] = {}

    def require_text(*fields: str) -> None:
        for field in fields:
            value = arguments.get(field)
            if not isinstance(value, str) or not value.strip():
                missing.append(field)

    if name == RESOLVE_DATABASE_TARGET_TOOL_NAME:
        allowed_fields = {"task_id", "mapping_id", "table_name", "business_hint"}
        invalid.extend(sorted(set(arguments) - allowed_fields))
        if not any(
            isinstance(arguments.get(field), str) and arguments[field].strip()
            for field in ("mapping_id", "table_name", "business_hint")
        ):
            missing.append("mapping_id|table_name|business_hint")
    elif name == SEARCH_DATABASE_TOOL_NAME:
        require_text("database_context_id", "object_type")
        detail = arguments.get("detail", "names")
        if detail not in {"names", "summary", "full"}:
            invalid.append("detail")
            allowed_values["detail"] = ["names", "summary", "full"]
    elif name == EXECUTE_DATABASE_TOOL_NAME:
        require_text("database_context_id", "sql")
    elif name == SAVE_DATA_VISUALIZATION_QUERY_TOOL_NAME:
        require_text("description", "keyword")
        mapping_id = arguments.get("mapping_id")
        if not isinstance(mapping_id, str) or not mapping_id.strip():
            require_text("database_key", "schema_name", "table_name")
    elif name == SAVE_TASK_VISUALIZATION_RESULT_TOOL_NAME:
        require_text("status", "summary")
        status = arguments.get("status")
        if status is not None and status not in {"investigating", "resolved", "failed"}:
            invalid.append("status")
            allowed_values["status"] = ["investigating", "resolved", "failed"]
    if not missing and not invalid:
        return None
    parts: list[str] = []
    if missing:
        parts.append("缺少必填字段：" + "、".join(missing))
    if invalid:
        parts.append("字段值不合法：" + "、".join(invalid))
    if allowed_values:
        parts.append(
            "允许值："
            + "；".join(f"{field}={','.join(values)}" for field, values in allowed_values.items())
        )
    return {
        "reason": "invalid_tool_arguments",
        "message": "；".join(parts),
        "missing_fields": missing,
        "invalid_fields": invalid,
        "allowed_values": allowed_values,
    }


def _safe_error_summary(error_code: str) -> dict[str, object]:
    return {"reason": error_code}


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
        "column_not_found": "SQL 引用了当前表中不存在的字段，请先读取字段清单",
        "table_not_found": "SQL 引用了当前数据库中不存在的表，请先搜索表名",
        "schema_not_found": "SQL 引用了当前数据库中不存在的 Schema，请先搜索 Schema",
        "database_not_found": "当前任务环境中的数据库目标不存在，请重新解析数据库目标",
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
