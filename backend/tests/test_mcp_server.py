import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from context_router.mcp_server import (
    MCP_SERVER_INSTRUCTIONS,
    PREPARE_TOOL_DESCRIPTION,
    READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION,
    READ_TASK_CONTEXT_TOOL_DESCRIPTION,
    create_context_router_mcp,
)
from context_router.schemas.context import SearchContextDocumentsResult
from context_router.schemas.table_relations import (
    TableIdentity,
    TableRelationContextResult,
    TableRelationDatabaseScope,
)


class UnusedService:
    def prepare(self, **_: object) -> None:
        raise AssertionError("tools/list must not call prepare")

    def read(self, **_: object) -> None:
        raise AssertionError("tools/list must not call read")


class _PrepareResult:
    def model_dump(self, **_: object) -> dict[str, object]:
        return {"task_id": 55}


class RecordingPreparationService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def prepare(self, **arguments: object) -> _PrepareResult:
        self.arguments = arguments
        return _PrepareResult()

    def read_task_context(self, **arguments: object) -> _PrepareResult:
        self.arguments = arguments
        return _PrepareResult()


class RecordingCatalogService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def search(self, **arguments: object) -> dict[str, object]:
        self.arguments = arguments
        return {"objects": [], "returned_count": 0}


class RecordingDocumentSearchService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def search(self, **arguments: object) -> SearchContextDocumentsResult:
        self.arguments = arguments
        return SearchContextDocumentsResult(
            task_id=int(arguments["task_id"]),
            query=str(arguments["query"]),
            returned_count=0,
            truncated=False,
            results=[],
        )


class RecordingQueryService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def execute(self, **arguments: object) -> dict[str, object]:
        self.arguments = arguments
        return {"rows": [[1]], "returned_rows": 1}


class RecordingMiddlewareContextService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def read(self, **arguments: object) -> _PrepareResult:
        self.arguments = arguments
        return _PrepareResult()


class RecordingTableRelationService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def context_for_task(self, **arguments: object) -> TableRelationContextResult:
        self.arguments = arguments
        return TableRelationContextResult(
            workspace_id="workspace-1",
            task_id=int(arguments["task_id"]),
            detail_level=str(arguments["detail_level"]),  # type: ignore[arg-type]
            relation_database_scope=TableRelationDatabaseScope(
                config_revision=1,
                database_key="cargo_db",
                schema_name="cargo",
            ),
            root_table=TableIdentity(
                project_id="project-1",
                project_name="cargo-service",
                database_key="cargo_db",
                schema_name="cargo",
                table_name=str(arguments["table"]),
            ),
            related_tables=[],
            joins=[],
            total_relation_count=0,
            returned_relation_count=0,
            has_more=False,
        )


class _RuntimeResult:
    def __init__(self, operation_id: str, task_id: int = 9) -> None:
        self.operation_id = operation_id
        self.task_id = task_id

    def model_dump(self, **_: object) -> dict[str, object]:
        return {
            "id": self.operation_id,
            "task_id": self.task_id,
            "workspace_id": "workspace-1",
            "kind": "apply_changes",
            "status": "queued",
            "steps": [],
        }


class RecordingWorkspaceRuntimeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def apply_changes(self, **arguments: object) -> _RuntimeResult:
        self.calls.append(("apply", arguments))
        return _RuntimeResult("operation-1")

    def start_workspace(self, **arguments: object) -> _RuntimeResult:
        self.calls.append(("start", arguments))
        return _RuntimeResult("operation-2")

    def get_operation(self, operation_id: str, log_characters: int) -> _RuntimeResult:
        self.calls.append(("get", {"operation_id": operation_id, "log_characters": log_characters}))
        return _RuntimeResult(operation_id)

    def get_task_id(self, operation_id: str) -> int:
        assert operation_id
        return 9


def test_mcp_exposes_stable_context_and_runtime_tools() -> None:
    service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        service,
        service,
    )

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == [
        "prepare_task_context",
        "read_task_context",
        "read_middleware_context",
        "search_context_documents",
        "read_context_document",
        "search_database_objects",
        "execute_database_query",
        "prepare_table_relation_context",
        "apply_workspace_changes",
        "start_workspace",
        "get_workspace_operation",
    ]
    assert tools[0].annotations is not None
    assert tools[0].annotations.readOnlyHint is True
    assert tools[0].annotations.destructiveHint is False
    assert tools[0].annotations.idempotentHint is False
    assert tools[0].annotations.openWorldHint is False
    for tool in tools[1:8]:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False
    for tool in (tools[8], tools[9]):
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is True
        assert tool.annotations.idempotentHint is False
    for tool in (tools[10],):
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
    prepare_schema = tools[0].inputSchema
    assert prepare_schema["required"] == ["task", "cwd"]
    assert set(prepare_schema["properties"]) == {
        "task",
        "cwd",
        "agent_name",
        "environment",
    }
    assert "test" in str(prepare_schema["properties"]["environment"])
    assert "uat" in str(prepare_schema["properties"]["environment"])
    assert "read_task_context" in PREPARE_TOOL_DESCRIPTION
    assert "sensitive" in READ_TASK_CONTEXT_TOOL_DESCRIPTION
    assert "not the authoritative or live source" in READ_TASK_CONTEXT_TOOL_DESCRIPTION
    assert "reveal_secrets" in READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION
    assert "returns plaintext fields by default" in READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION
    assert "Returning and using connection values" in READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION
    assert "never echo it into logs" in MCP_SERVER_INSTRUCTIONS
    task_context_schema = tools[1].inputSchema
    middleware_schema = tools[2].inputSchema
    document_search_schema = tools[3].inputSchema
    database_search_schema = tools[5].inputSchema
    query_schema = tools[6].inputSchema
    table_relation_schema = tools[7].inputSchema
    assert task_context_schema["required"] == ["task_id", "sections"]
    assert set(task_context_schema["properties"]) == {"task_id", "sections"}
    assert middleware_schema["required"] == ["task_id"]
    assert set(middleware_schema["properties"]) == {
        "task_id",
        "components",
        "reveal_secrets",
    }
    assert middleware_schema["properties"]["reveal_secrets"]["default"] is True
    assert document_search_schema["required"] == ["task_id", "query"]
    assert set(document_search_schema["properties"]) == {"task_id", "query", "limit"}
    assert database_search_schema["required"] == ["task_id", "database", "object_type"]
    assert set(database_search_schema["properties"]) == {
        "task_id",
        "database",
        "object_type",
        "pattern",
        "detail",
        "schema",
        "table",
        "limit",
    }
    assert query_schema["required"] == ["task_id", "database", "sql"]
    assert set(query_schema["properties"]) == {"task_id", "database", "sql"}
    assert table_relation_schema["required"] == ["task_id", "table"]
    assert set(table_relation_schema["properties"]) == {
        "task_id",
        "table",
        "database_key",
        "schema",
        "detail_level",
        "relation_limit",
        "relation_offset",
        "evidence_limit_per_join",
    }
    assert "tables" not in table_relation_schema["properties"]
    assert "include_evidence" not in table_relation_schema["properties"]
    assert table_relation_schema["properties"]["detail_level"]["default"] == "evidence"
    assert set(table_relation_schema["properties"]["detail_level"]["enum"]) == {
        "compact",
        "evidence",
        "full",
    }
    assert table_relation_schema["properties"]["relation_limit"]["default"] == 20
    assert table_relation_schema["properties"]["relation_offset"]["default"] == 0
    assert table_relation_schema["properties"]["evidence_limit_per_join"]["default"] == 5


def test_workspace_runtime_tools_forward_only_task_scoped_arguments() -> None:
    service = UnusedService()
    runtime = RecordingWorkspaceRuntimeService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        service,
        service,
        workspace_runtime_service=runtime,  # type: ignore[arg-type]
    )

    _, applied = asyncio.run(
        server.call_tool(
            "apply_workspace_changes",
            {"task_id": 9, "changed_files": ["backend/app.py"]},
        )
    )
    _, started = asyncio.run(server.call_tool("start_workspace", {"task_id": 9}))
    _, read = asyncio.run(
        server.call_tool(
            "get_workspace_operation",
            {"operation_id": "operation-1", "log_characters": 2000},
        )
    )

    assert applied["id"] == "operation-1"
    assert started["id"] == "operation-2"
    assert read["id"] == "operation-1"
    assert runtime.calls == [
        ("apply", {"task_id": 9, "changed_files": ["backend/app.py"]}),
        ("start", {"task_id": 9}),
        ("get", {"operation_id": "operation-1", "log_characters": 2000}),
    ]


def test_prepare_forwards_optional_task_environment() -> None:
    preparation = RecordingPreparationService()
    document_service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        preparation,
        document_service,
    )

    _, result = asyncio.run(
        server.call_tool(
            "prepare_task_context",
            {
                "task": "检查 TEST 环境",
                "cwd": "/workspace/project",
                "agent_name": "codex",
                "environment": "test",
            },
        )
    )

    assert result == {"task_id": 55}
    assert preparation.arguments == {
        "task": "检查 TEST 环境",
        "cwd": "/workspace/project",
        "agent_name": "codex",
        "environment": "test",
    }


def test_read_task_context_forwards_only_requested_sections() -> None:
    preparation = RecordingPreparationService()
    document_service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        preparation,
        document_service,
    )

    _, result = asyncio.run(
        server.call_tool(
            "read_task_context",
            {"task_id": 9, "sections": ["databases", "environment"]},
        )
    )

    assert result == {"task_id": 55}
    assert preparation.arguments == {
        "task_id": 9,
        "sections": ["databases", "environment"],
    }


def test_read_middleware_context_forwards_only_task_scoped_arguments() -> None:
    document_service = UnusedService()
    middleware = RecordingMiddlewareContextService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        middleware_context_service=middleware,  # type: ignore[arg-type]
    )

    _, result = asyncio.run(
        server.call_tool(
            "read_middleware_context",
            {
                "task_id": 9,
                "components": ["redis-main", "rocketmq"],
            },
        )
    )

    assert result == {"task_id": 55}
    assert middleware.arguments == {
        "task_id": 9,
        "components": ["redis-main", "rocketmq"],
        "reveal_secrets": True,
    }


def test_document_search_forwards_only_fixed_public_arguments() -> None:
    document_service = UnusedService()
    search = RecordingDocumentSearchService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        document_search_service=search,
    )

    _, result = asyncio.run(
        server.call_tool(
            "search_context_documents",
            {
                "task_id": 9,
                "query": "数据库迁移",
                "limit": 7,
            },
        )
    )

    assert result == {
        "task_id": 9,
        "query": "数据库迁移",
        "returned_count": 0,
        "truncated": False,
        "results": [],
    }
    assert search.arguments == {
        "task_id": 9,
        "query": "数据库迁移",
        "limit": 7,
    }


def test_database_tools_forward_only_fixed_public_arguments() -> None:
    document_service = UnusedService()
    catalog = RecordingCatalogService()
    query = RecordingQueryService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        catalog,  # type: ignore[arg-type]
        query,  # type: ignore[arg-type]
    )

    _, search_result = asyncio.run(
        server.call_tool(
            "search_database_objects",
            {
                "task_id": 9,
                "database": "analytics",
                "object_type": "table",
                "pattern": "event*",
            },
        )
    )
    _, query_result = asyncio.run(
        server.call_tool(
            "execute_database_query",
            {
                "task_id": 9,
                "database": "analytics",
                "sql": "SELECT 1",
            },
        )
    )

    assert search_result == {"objects": [], "returned_count": 0}
    assert catalog.arguments == {
        "task_id": 9,
        "database": "analytics",
        "object_type": "table",
        "pattern": "event*",
        "detail": "names",
        "schema": None,
        "table": None,
        "limit": 100,
    }
    assert query_result == {"rows": [[1]], "returned_rows": 1}
    assert query.arguments == {
        "task_id": 9,
        "database": "analytics",
        "sql": "SELECT 1",
    }


def test_table_relation_tool_returns_undirected_observed_context() -> None:
    document_service = UnusedService()
    relation_service = RecordingTableRelationService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        table_relation_service=relation_service,  # type: ignore[arg-type]
    )

    _, result = asyncio.run(
        server.call_tool(
            "prepare_table_relation_context",
            {
                "task_id": 9,
                "table": "cs_dsly_basic_cargo",
                "database_key": "cargo_db",
                "schema": "cargo",
                "detail_level": "full",
            },
        )
    )

    assert relation_service.arguments == {
        "task_id": 9,
        "table": "cs_dsly_basic_cargo",
        "database_key": "cargo_db",
        "schema": "cargo",
        "detail_level": "full",
        "relation_limit": 20,
        "relation_offset": 0,
        "evidence_limit_per_join": 5,
    }
    assert result["relation_semantics"] == {
        "kind": "observed_sql_join",
        "directed": False,
        "notice": "结果表示项目 SQL 中观察到的字段等值关联，不等同于外键、主从关系或数据血缘。",
    }


def test_table_relation_tool_defaults_to_evidence_detail() -> None:
    document_service = UnusedService()
    relation_service = RecordingTableRelationService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        table_relation_service=relation_service,  # type: ignore[arg-type]
    )

    asyncio.run(
        server.call_tool(
            "prepare_table_relation_context",
            {"task_id": 9, "table": "cs_dsly_basic_cargo"},
        )
    )

    assert relation_service.arguments == {
        "task_id": 9,
        "table": "cs_dsly_basic_cargo",
        "database_key": None,
        "schema": None,
        "detail_level": "evidence",
        "relation_limit": 20,
        "relation_offset": 0,
        "evidence_limit_per_join": 5,
    }


@pytest.mark.parametrize("invalid_task_id", ["9", True])
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "read_middleware_context",
            {"components": ["redis-main"], "reveal_secrets": True},
        ),
        (
            "search_context_documents",
            {"query": "数据库迁移"},
        ),
        (
            "read_context_document",
            {"requests": [{"document_id": "root"}]},
        ),
        (
            "search_database_objects",
            {"database": "analytics", "object_type": "table"},
        ),
        (
            "execute_database_query",
            {"database": "analytics", "sql": "SELECT 1"},
        ),
        (
            "prepare_table_relation_context",
            {"table": "example_table"},
        ),
    ],
)
def test_followup_tools_reject_coercible_task_ids_before_business_execution(
    invalid_task_id: object,
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    document_service = UnusedService()
    catalog = RecordingCatalogService()
    query = RecordingQueryService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        catalog,  # type: ignore[arg-type]
        query,  # type: ignore[arg-type]
    )

    with pytest.raises(ToolError):
        asyncio.run(
            server.call_tool(
                tool_name,
                {"task_id": invalid_task_id, **arguments},
            )
        )

    assert catalog.arguments == {}
    assert query.arguments == {}
