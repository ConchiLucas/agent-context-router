from pathlib import Path

from fastapi.testclient import TestClient

from context_router.config import Settings
from context_router.main import create_app
from context_router.repositories.project_repository import InMemoryProjectRepository


def test_project_configuration_crud_api(tmp_path: Path) -> None:
    root = tmp_path / "project" / "AGENTS.md"
    root.parent.mkdir(parents=True)
    root.write_text("# 项目入口", encoding="utf-8")
    repository = InMemoryProjectRepository()
    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        project_repository=repository,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/projects",
            json={"name": "测试项目", "agents_path": str(root)},
        )
        project_id = created.json()["id"]
        updated = client.put(
            f"/api/projects/{project_id}",
            json={"name": "更新后的项目", "agents_path": str(root)},
        )
        disabled = client.patch(
            f"/api/projects/{project_id}/enabled",
            json={"enabled": False},
        )
        listed = client.get("/api/projects")
        deleted = client.delete(f"/api/projects/{project_id}")
        empty = client.get("/api/projects")

    assert created.status_code == 201
    assert created.json()["enabled"] is True
    assert updated.status_code == 200
    assert updated.json()["name"] == "更新后的项目"
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert listed.json()[0]["id"] == project_id
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert empty.json() == []
