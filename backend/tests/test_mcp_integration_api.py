import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from context_router.config import Settings
from context_router.main import create_app
from context_router.repositories.data_source_repository import (
    InMemoryDataSourceRepository,
)
from context_router.repositories.database_tool_payload_repository import (
    InMemoryDatabaseToolPayloadRepository,
)
from context_router.repositories.document_search_repository import (
    InMemoryDocumentSearchRepository,
)
from context_router.repositories.mcp_tool_call_repository import (
    InMemoryMcpToolCallRepository,
)
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.runtime_run_repository import (
    InMemoryRuntimeRunRepository,
)


class FakeTaskRepository:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def create_task(self, **arguments: object) -> int:
        self.arguments = arguments
        return 1


def test_mcp_integration_returns_client_configs_and_readiness(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    root = workspace_root / "docs" / "backend" / "project" / "AGENTS.md"
    root.parent.mkdir(parents=True)
    (workspace_root / "backend" / "project").mkdir(parents=True)
    root.write_text("# 入口", encoding="utf-8")
    project_repository = InMemoryProjectRepository()
    task_repository = FakeTaskRepository()
    app = create_app(
        Settings(
            database_url="postgresql://example.invalid/context_router",
            public_mcp_url="https://context.example.com/mcp/",
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            workspace_mapping_file=None,
        ),
        task_repository=task_repository,
        project_repository=project_repository,
        data_source_repository=InMemoryDataSourceRepository(project_repository),
        document_search_repository=InMemoryDocumentSearchRepository(),
        mcp_tool_call_repository=InMemoryMcpToolCallRepository(),
        database_payload_repository=InMemoryDatabaseToolPayloadRepository(),
        runtime_run_repository=InMemoryRuntimeRunRepository(),
    )

    async def prepare_through_mcp() -> None:
        http_client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://127.0.0.1:49173",
            headers={"X-Agent-Name": "gemini"},
        )
        async with http_client:
            async with streamable_http_client(
                "http://127.0.0.1:49173/mcp/",
                http_client=http_client,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "prepare_task_context",
                        arguments={
                            "task": "验证客户端名称",
                            "cwd": str(workspace_root),
                        },
                    )
                    assert result.isError is False

    with TestClient(app) as client:
        workspace_response = client.post(
            "/api/workspaces",
            json={
                "name": "测试工作空间",
                "workspace_type": "公司项目",
                "root_path": str(workspace_root),
                "enabled": True,
            },
        )
        assert workspace_response.status_code == 201
        workspace_id = workspace_response.json()["id"]
        project_response = client.post(
            f"/api/workspaces/{workspace_id}/projects",
            json={
                "name": "测试项目",
                "project_kind": "backend",
                "relative_path": "backend/project",
                "document_relative_path": "docs/backend/project/AGENTS.md",
            },
        )
        assert project_response.status_code == 201
        response = client.get("/api/mcp/integration")
        tools_response = client.get("/api/mcp/integration/tools")
        asyncio.run(prepare_through_mcp())

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == {
        "name": "Context Router",
        "transport": "Streamable HTTP",
        "url": "https://context.example.com/mcp",
    }
    assert [tool["name"] for tool in payload["tools"]] == [
        "prepare_task_context",
        "read_task_context",
        "read_middleware_context",
        "search_context_documents",
        "read_context_document",
        "resolve_database_target",
        "search_database_objects",
        "execute_database_query",
        "save_data_visualization_query",
        "save_task_visualization_result",
        "list_task_containers",
        "inspect_container_errors",
        "read_table_relations",
        "search_relation_tables",
        "search_value_mappings",
        "resolve_value_candidates",
        "execute_mapped_data_query",
        "search_forwarding_interfaces",
        "read_forwarding_request_history",
        "prepare_forwarding_request",
        "execute_forwarding_request",
        "discover_task_tools",
        "invoke_task_tool",
        "apply_workspace_changes",
        "start_workspace",
        "get_workspace_operation",
    ]
    assert payload["readiness"] == {
        "database_configured": True,
        "workspace_count": 1,
        "ready_for_full_test": True,
    }
    configs = {item["client"]: item["config"] for item in payload["clients"]}
    assert 'url = "https://context.example.com/mcp"' in configs["codex"]
    assert '"X-Agent-Name" = "codex"' in configs["codex"]
    assert '"httpUrl": "https://context.example.com/mcp"' in configs["gemini"]
    assert '"X-Agent-Name": "gemini"' in configs["gemini"]
    assert "agy mcp add --type http" in configs["antigravity"]
    assert "X-Agent-Name: antigravity" in configs["antigravity"]
    assert '"url": "https://context.example.com/mcp"' in configs["cursor"]
    assert '"X-Agent-Name": "cursor"' in configs["cursor"]
    assert "grok mcp add --transport http" in configs["grok"]
    assert "X-Agent-Name: grok" in configs["grok"]
    client_configs = {item["client"]: item for item in payload["clients"]}
    assert client_configs["antigravity"]["setup_kind"] == "command"
    assert client_configs["cursor"]["setup_kind"] == "file"
    assert client_configs["grok"]["setup_kind"] == "command"
    assert tools_response.status_code == 200
    listed_tools = tools_response.json()["tools"]
    assert [tool["name"] for tool in listed_tools] == [
        "prepare_task_context",
        "read_task_context",
        "read_middleware_context",
        "search_context_documents",
        "read_context_document",
        "resolve_database_target",
        "search_database_objects",
        "execute_database_query",
        "save_data_visualization_query",
        "save_task_visualization_result",
        "list_task_containers",
        "inspect_container_errors",
        "read_table_relations",
        "search_relation_tables",
        "search_value_mappings",
        "resolve_value_candidates",
        "execute_mapped_data_query",
        "search_forwarding_interfaces",
        "read_forwarding_interface_detail",
        "read_forwarding_request_history",
        "prepare_forwarding_request",
        "execute_forwarding_request",
        "discover_task_tools",
        "invoke_task_tool",
        "apply_workspace_changes",
        "start_workspace",
        "get_workspace_operation",
    ]
    assert listed_tools[0]["inputSchema"]["required"] == ["task", "cwd"]
    assert listed_tools[0]["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }

    assert task_repository.arguments["agent_name"] == "gemini"
