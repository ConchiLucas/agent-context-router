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
            workspace_mapping_file=None,
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
            json={
                "name": "更新后的项目",
                "project_type": "交通物流",
                "project_kind": "frontend",
                "agents_path": str(root),
            },
        )
        removed_enabled = client.patch(
            f"/api/projects/{project_id}/enabled",
            json={"enabled": False},
        )
        removed_refresh = client.post(f"/api/projects/{project_id}/refresh")
        removed_tree = client.get(f"/api/projects/{project_id}/tree")
        removed_preview = client.post(f"/api/projects/{project_id}/prepare-preview")
        removed_document = client.get(f"/api/projects/{project_id}/documents/unknown-document")
        removed_tasks = client.get(f"/api/projects/{project_id}/tasks")
        workspace_tree = client.get(f"/api/workspaces/{project_id}/tree")
        listed = client.get("/api/projects")
        deleted = client.delete(f"/api/projects/{project_id}")
        empty = client.get("/api/projects")

    assert created.status_code == 201
    assert "enabled" not in created.json()
    assert created.json()["project_type"] == "公司项目"
    assert created.json()["project_kind"] == "backend"
    assert updated.status_code == 200
    assert updated.json()["name"] == "更新后的项目"
    assert updated.json()["project_type"] == "交通物流"
    assert updated.json()["project_kind"] == "frontend"
    assert removed_enabled.status_code == 404
    assert removed_refresh.status_code == 404
    assert removed_tree.status_code == 404
    assert removed_preview.status_code == 404
    assert removed_document.status_code == 404
    assert removed_tasks.status_code == 404
    assert workspace_tree.status_code == 200
    assert listed.json()[0]["id"] == project_id
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert empty.json() == []
