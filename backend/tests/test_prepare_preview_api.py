from pathlib import Path

from fastapi.testclient import TestClient

from context_router.config import Settings
from context_router.main import create_app
from context_router.repositories.project_repository import InMemoryProjectRepository


class FakeTaskRepository:
    def create_task(self, **_: object) -> int:
        return 77


def test_project_preview_returns_prepare_result(tmp_path: Path) -> None:
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

    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        task_repository=FakeTaskRepository(),
        project_repository=InMemoryProjectRepository(),
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/projects",
            json={"name": "测试项目", "agents_path": str(root)},
        )
        assert created.status_code == 201

        response = client.post(f"/api/projects/{created.json()['id']}/prepare-preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == 77
    assert payload["documents"]["summary"] == "项目导航。"
    assert "summary" not in payload["documents"]["children"][0]
    assert "content" not in response.text
