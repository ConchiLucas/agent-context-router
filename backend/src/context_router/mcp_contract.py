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
CONTEXT_ROUTER_INTERFACE_FORWARDING_TOOL_NAMES = (
    "search_forwarding_interfaces",
    "read_forwarding_request_history",
    "prepare_forwarding_request",
    "execute_forwarding_request",
)
CONTEXT_ROUTER_VALUE_MAPPING_TOOL_NAMES = (
    "search_value_mappings",
    "resolve_value_candidates",
)
CONTEXT_ROUTER_LOG_VISUALIZATION_TOOL_NAMES = (
    "list_task_containers",
    "inspect_container_errors",
)
CONTEXT_ROUTER_DATA_VISUALIZATION_TOOL_NAMES = ("save_data_visualization_query",)
CONTEXT_ROUTER_TASK_VISUALIZATION_TOOL_NAMES = ("save_task_visualization_result",)
CONTEXT_ROUTER_LEGACY_TOOL_NAMES = (
    "apply_project_changes",
    "get_project_operation",
    "prepare_table_relation_context",
)
CONTEXT_ROUTER_TRACE_TOOL_NAMES = (
    *CONTEXT_ROUTER_CORE_TOOL_NAMES,
    *CONTEXT_ROUTER_RUNTIME_TOOL_NAMES,
    *CONTEXT_ROUTER_TABLE_RELATION_TOOL_NAMES,
    *CONTEXT_ROUTER_VALUE_MAPPING_TOOL_NAMES,
    *CONTEXT_ROUTER_INTERFACE_FORWARDING_TOOL_NAMES,
    *CONTEXT_ROUTER_LOG_VISUALIZATION_TOOL_NAMES,
    *CONTEXT_ROUTER_DATA_VISUALIZATION_TOOL_NAMES,
    *CONTEXT_ROUTER_TASK_VISUALIZATION_TOOL_NAMES,
    *CONTEXT_ROUTER_LEGACY_TOOL_NAMES,
)
CONTEXT_ROUTER_TRACE_SOURCES = ("server", "legacy")
