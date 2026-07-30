import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from context_router.mcp_server import (
    MCP_SERVER_INSTRUCTIONS,
    PREPARE_TOOL_DESCRIPTION,
    create_context_router_mcp,
)
from context_router.schemas.context import SearchContextDocumentsResult


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


def test_mcp_exposes_stable_context_and_runtime_tools() -> None:
    service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        service,
        service,
    )

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == [
        "prepare_task_context",
        "search_context_documents",
        "read_context_document",
        "search_database_objects",
        "execute_database_query",
        "apply_project_changes",
        "get_project_operation",
    ]
    assert tools[0].annotations is not None
    assert tools[0].annotations.readOnlyHint is True
    assert tools[0].annotations.destructiveHint is False
    assert tools[0].annotations.idempotentHint is False
    assert tools[0].annotations.openWorldHint is False
    for tool in tools[1:5]:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False
    assert tools[5].annotations is not None
    assert tools[5].annotations.readOnlyHint is False
    assert tools[5].annotations.destructiveHint is True
    assert tools[5].annotations.idempotentHint is False
    assert tools[6].annotations is not None
    assert tools[6].annotations.readOnlyHint is True
    assert tools[6].annotations.destructiveHint is False
    assert tools[6].annotations.idempotentHint is True
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
    assert "credentials" in PREPARE_TOOL_DESCRIPTION
    assert "never echo it into logs" in MCP_SERVER_INSTRUCTIONS
    document_search_schema = tools[1].inputSchema
    database_search_schema = tools[3].inputSchema
    query_schema = tools[4].inputSchema
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


@pytest.mark.parametrize("invalid_task_id", ["9", True])
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
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
