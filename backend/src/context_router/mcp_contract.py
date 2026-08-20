from __future__ import annotations

CONTEXT_ROUTER_TRACE_SERVER_NAME = "context-router"
CONTEXT_ROUTER_CORE_TOOL_NAMES = (
    "prepare_task_context",
    "read_task_context",
    "read_middleware_context",
    "search_context_documents",
    "read_context_document",
    "search_database_objects",
    "execute_database_query",
)
CONTEXT_ROUTER_RUNTIME_TOOL_NAMES = (
    "apply_workspace_changes",
    "start_workspace",
    "get_workspace_operation",
)
CONTEXT_ROUTER_TABLE_RELATION_TOOL_NAMES = (
    "read_table_relations",
    "search_relation_tables",
)
CONTEXT_ROUTER_LEGACY_TOOL_NAMES = (
    "apply_project_changes",
    "get_project_operation",
    "prepare_table_relation_context",
)
CONTEXT_ROUTER_TRACE_TOOL_NAMES = (
    *CONTEXT_ROUTER_CORE_TOOL_NAMES,
    *CONTEXT_ROUTER_RUNTIME_TOOL_NAMES,
    *CONTEXT_ROUTER_TABLE_RELATION_TOOL_NAMES,
    *CONTEXT_ROUTER_LEGACY_TOOL_NAMES,
)
CONTEXT_ROUTER_TRACE_SOURCES = ("server", "legacy")
