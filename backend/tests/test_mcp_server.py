import asyncio

from context_router.mcp_server import create_context_router_mcp


class UnusedService:
    def prepare(self, **_: object) -> None:
        raise AssertionError("tools/list must not call prepare")

    def read(self, **_: object) -> None:
        raise AssertionError("tools/list must not call read")


class RecordingCatalogService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def search(self, **arguments: object) -> dict[str, object]:
        self.arguments = arguments
        return {"objects": [], "returned_count": 0}


class RecordingQueryService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def execute(self, **arguments: object) -> dict[str, object]:
        self.arguments = arguments
        return {"rows": [[1]], "returned_rows": 1}


def test_mcp_exposes_four_stable_context_tools() -> None:
    service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        service,
        service,
    )

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == [
        "prepare_task_context",
        "read_context_document",
        "search_database_objects",
        "execute_database_query",
    ]
    search_schema = tools[2].inputSchema
    query_schema = tools[3].inputSchema
    assert search_schema["required"] == ["task_id", "database", "object_type"]
    assert set(search_schema["properties"]) == {
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
