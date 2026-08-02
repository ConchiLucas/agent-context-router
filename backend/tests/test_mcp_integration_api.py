from pathlib import Path

from fastapi.testclient import TestClient

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
    def create_task(self, **_: object) -> int:
        return 1


def test_mcp_integration_returns_client_configs_and_readiness(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    root = workspace_root / "docs" / "backend" / "project" / "AGENTS.md"
    root.parent.mkdir(parents=True)
    (workspace_root / "backend" / "project").mkdir(parents=True)
    root.write_text("# 入口", encoding="utf-8")
    project_repository = InMemoryProjectRepository()
    app = create_app(
        Settings(
            database_url="postgresql://example.invalid/context_router",
            public_mcp_url="https://context.example.com/mcp/",
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        ),
        task_repository=FakeTaskRepository(),
        project_repository=project_repository,
        data_source_repository=InMemoryDataSourceRepository(project_repository),
        document_search_repository=InMemoryDocumentSearchRepository(),
        mcp_tool_call_repository=InMemoryMcpToolCallRepository(),
        database_payload_repository=InMemoryDatabaseToolPayloadRepository(),
        runtime_run_repository=InMemoryRuntimeRunRepository(),
    )

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

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == {
        "name": "Context Router",
        "transport": "Streamable HTTP",
        "url": "https://context.example.com/mcp",
    }
    assert [tool["name"] for tool in payload["tools"]] == [
        "prepare_task_context",
        "search_context_documents",
        "read_context_document",
        "search_database_objects",
        "execute_database_query",
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
    assert '"serverUrl": "https://context.example.com/mcp"' in configs["antigravity"]
