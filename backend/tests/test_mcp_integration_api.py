from pathlib import Path

from fastapi.testclient import TestClient

from context_router.config import Settings
from context_router.main import create_app
from context_router.repositories.project_repository import InMemoryProjectRepository


class FakeTaskRepository:
    def create_task(self, **_: object) -> int:
        return 1


def test_mcp_integration_returns_client_configs_and_readiness(tmp_path: Path) -> None:
    root = tmp_path / "project" / "AGENTS.md"
    root.parent.mkdir(parents=True)
    root.write_text("# 入口", encoding="utf-8")
    app = create_app(
        Settings(
            database_url="postgresql://example.invalid/context_router",
            public_mcp_url="https://context.example.com/mcp/",
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name="测试项目",
            default_agents_path=str(root),
        ),
        task_repository=FakeTaskRepository(),
        project_repository=InMemoryProjectRepository(),
    )

    with TestClient(app) as client:
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
        "read_context_document",
    ]
    assert payload["readiness"] == {
        "database_configured": True,
        "project_count": 1,
        "ready_for_full_test": True,
    }
    configs = {item["client"]: item["config"] for item in payload["clients"]}
    assert 'url = "https://context.example.com/mcp"' in configs["codex"]
    assert '"serverUrl": "https://context.example.com/mcp"' in configs["antigravity"]
