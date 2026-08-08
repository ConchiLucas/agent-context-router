from pathlib import Path

from fastapi.testclient import TestClient

from context_router.config import Settings
from context_router.main import create_app
from context_router.repositories.database_environment_repository import (
    InMemoryDatabaseEnvironmentRepository,
)
from context_router.repositories.project_repository import InMemoryProjectRepository


class FakeTaskRepository:
    def create_workspace_task(self, **_: object) -> int:
        return 77


def test_workspace_preview_returns_prepare_result_and_project_preview_is_removed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project" / "AGENTS.md"
    child = tmp_path / "project" / "docs" / "child.md"
    child.parent.mkdir(parents=True)
    root.write_text(
        """---
title: 项目入口
summary: 项目导航。
---

## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 子文档 | `./docs/child.md` |
""",
        encoding="utf-8",
    )
    child.write_text("# 无显式概要", encoding="utf-8")
    project_entry = root.parent / "docs" / "backend" / "test" / "AGENTS.md"
    project_entry.parent.mkdir(parents=True)
    project_entry.write_text("# 测试项目文档入口", encoding="utf-8")

    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            workspace_mapping_file=None,
            default_project_name=None,
            default_agents_path=None,
        ),
        task_repository=FakeTaskRepository(),
        project_repository=InMemoryProjectRepository(),
        database_environment_repository=InMemoryDatabaseEnvironmentRepository(),
    )

    with TestClient(app) as client:
        workspace = client.post(
            "/api/workspaces",
            json={"name": "测试工作空间", "root_path": str(root.parent)},
        )
        assert workspace.status_code == 201
        project = client.post(
            f"/api/workspaces/{workspace.json()['id']}/projects",
            json={
                "name": "测试项目",
                "relative_path": ".",
                "document_relative_path": "docs/backend/test/AGENTS.md",
            },
        )
        assert project.status_code == 201

        environment_config = client.put(
            f"/api/workspaces/{workspace.json()['id']}/environment-config",
            json={
                "expected_revision": 0,
                "environments": {
                    "test": {"service": {"endpoint": "test.internal"}},
                    "uat": {"service": {"endpoint": "uat.internal"}},
                },
            },
        )
        assert environment_config.status_code == 200

        response = client.post(
            f"/api/workspaces/{workspace.json()['id']}/prepare-preview",
            params={"environment": "test"},
        )
        environment_after_preview = client.get(
            f"/api/workspaces/{workspace.json()['id']}/environment-config"
        )
        removed_project_preview = client.post(
            f"/api/projects/{project.json()['id']}/prepare-preview"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == 77
    assert payload["workspace"]["workspace_id"] == workspace.json()["id"]
    project_root = payload["documents"]
    assert project_root["summary"] == "项目导航。"
    assert "summary" not in project_root["children"][0]
    assert "content" not in str(payload["documents"])
    assert payload["system_guides"]["required"][0]["content"]["schema_version"] == 1
    assert payload["database_environment"] == {
        "key": "test",
        "name": "TEST",
        "revision": 1,
        "selection": "task_explicit",
    }
    assert payload["environment_config"] == {"service": {"endpoint": "test.internal"}}
    assert environment_after_preview.json()["active_environment"] == "uat"
    assert removed_project_preview.status_code == 404
