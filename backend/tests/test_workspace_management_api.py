from pathlib import Path

from fastapi.testclient import TestClient

from context_router.config import Settings
from context_router.main import create_app
from context_router.repositories.data_source_repository import (
    InMemoryDataSourceRepository,
)
from context_router.repositories.document_search_repository import (
    InMemoryDocumentSearchRepository,
)
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.workspace_repository import InMemoryWorkspaceRepository


class _TaskRepository:
    def create_workspace_task(self, **_: object) -> int:
        return 101


def _write_agents(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}", encoding="utf-8")


def _app(tmp_path: Path, *, with_tasks: bool = False):
    workspace_repository = InMemoryWorkspaceRepository()
    project_repository = InMemoryProjectRepository(workspace_repository)
    return create_app(
        Settings(
            database_url=None,
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        task_repository=_TaskRepository() if with_tasks else None,
        workspace_repository=workspace_repository,
        project_repository=project_repository,
        data_source_repository=InMemoryDataSourceRepository(project_repository),
        document_search_repository=InMemoryDocumentSearchRepository(),
    )


def test_workspace_projects_and_data_source_summary(tmp_path: Path) -> None:
    workspace_root = tmp_path / "company"
    _write_agents(workspace_root / "AGENTS.md", "根项目")
    (workspace_root / "services" / "order").mkdir(parents=True)
    _write_agents(
        workspace_root / "docs" / "frontend" / "root" / "AGENTS.md",
        "根项目",
    )
    _write_agents(
        workspace_root / "docs" / "backend" / "order" / "AGENTS.md",
        "订单项目",
    )
    app = _app(tmp_path, with_tasks=True)

    with TestClient(app) as client:
        workspace_response = client.post(
            "/api/workspaces",
            json={
                "name": "公司工作空间",
                "workspace_type": "公司项目",
                "root_path": str(workspace_root),
            },
        )
        assert workspace_response.status_code == 201
        workspace = workspace_response.json()

        root_project_response = client.post(
            f"/api/workspaces/{workspace['id']}/projects",
            json={
                "name": "根项目",
                "relative_path": ".",
                "document_relative_path": "docs/frontend/root/AGENTS.md",
                "project_kind": "frontend",
            },
        )
        nested_project_response = client.post(
            f"/api/workspaces/{workspace['id']}/projects",
            json={
                "name": "订单项目",
                "relative_path": "services/order",
                "document_relative_path": "docs/backend/order/AGENTS.md",
                "project_kind": "backend",
            },
        )
        assert root_project_response.status_code == 201
        assert nested_project_response.status_code == 201
        root_project = root_project_response.json()
        nested_project = nested_project_response.json()

        legacy_child_update = client.put(
            f"/api/projects/{nested_project['id']}",
            json={
                "name": "错误更新",
                "project_type": "公司项目",
                "agents_path": str(workspace_root / "services" / "order" / "AGENTS.md"),
            },
        )
        assert legacy_child_update.status_code == 400
        assert "工作空间项目接口" in legacy_child_update.json()["detail"]

        legacy_root_update = client.put(
            f"/api/projects/{root_project['id']}",
            json={
                "name": "错误更新",
                "project_type": "公司项目",
                "agents_path": str(workspace_root / "AGENTS.md"),
            },
        )
        assert legacy_root_update.status_code == 400
        assert "包含多个项目" in legacy_root_update.json()["detail"]

        source = client.post(
            "/api/data-sources",
            json={
                "name": "订单 PostgreSQL",
                "engine": "postgresql",
                "connection_config": {"host": "localhost"},
            },
        ).json()
        database = client.post(
            f"/api/data-sources/{source['id']}/databases",
            json={
                "remote_name": "orders",
                "display_name": "订单库",
                "namespace_type": "database",
            },
        ).json()
        for project, mcp_alias in (
            (root_project, "frontend_orders"),
            (nested_project, "backend_orders"),
        ):
            selected = client.put(
                f"/api/projects/{project['id']}/databases",
                json={
                    "database_ids": [database["id"]],
                    "mcp_aliases": {database["id"]: mcp_alias},
                },
            )
            assert selected.status_code == 200

        removed_project_enabled = client.patch(
            (f"/api/workspaces/{workspace['id']}/projects/{nested_project['id']}/enabled"),
            json={"enabled": True},
        )
        assert removed_project_enabled.status_code == 404

        workspace_list = client.get("/api/workspaces")
        projects = client.get(f"/api/workspaces/{workspace['id']}/projects")
        summary = client.get(f"/api/workspaces/{workspace['id']}/data-source-summary")
        refreshed = client.post(f"/api/workspaces/{workspace['id']}/refresh")
        tree = client.get(f"/api/workspaces/{workspace['id']}/tree")
        preview = client.post(f"/api/workspaces/{workspace['id']}/prepare-preview")
        removed_project_preview = client.post(
            f"/api/projects/{nested_project['id']}/prepare-preview"
        )
        removed_project_tree = client.get(f"/api/projects/{nested_project['id']}/tree")
        document_id = app.state.project_registry.get_tree(nested_project["id"]).id
        document = client.get(f"/api/workspaces/{workspace['id']}/documents/{document_id}")
        removed_project_document = client.get(
            f"/api/projects/{nested_project['id']}/documents/{document_id}"
        )
        deleted_workspace = client.delete(f"/api/workspaces/{workspace['id']}")
        sources_after_delete = client.get("/api/data-sources")

    assert workspace_list.status_code == 200
    assert workspace_list.json()[0]["project_count"] == 2, workspace_list.json()
    assert workspace_list.json()[0]["frontend_project_count"] == 1
    assert workspace_list.json()[0]["backend_project_count"] == 1
    assert workspace_list.json()[0]["data_source_count"] == 1
    assert [item["relative_path"] for item in projects.json()] == [
        ".",
        "services/order",
    ]
    assert [item["document_relative_path"] for item in projects.json()] == [
        "docs/frontend/root/AGENTS.md",
        "docs/backend/order/AGENTS.md",
    ]
    assert summary.status_code == 200
    assert summary.json()["source_count"] == 1
    assert summary.json()["database_count"] == 1
    assert summary.json()["assignment_count"] == 2
    assert summary.json()["project_count"] == 2
    assert refreshed.status_code == 200
    assert tree.status_code == 200
    assert tree.json()["children"] == []
    assert preview.status_code == 200
    assert preview.json()["workspace"]["workspace_id"] == workspace["id"]
    assert {item["relative_path"] for item in preview.json()["projects"]} == {
        ".",
        "services/order",
    }
    assert {item["document_relative_path"] for item in preview.json()["projects"]} == {
        "docs/frontend/root/AGENTS.md",
        "docs/backend/order/AGENTS.md",
    }
    assert {item["database"] for item in preview.json()["databases"]} == {
        "frontend_orders",
        "backend_orders",
    }
    assert removed_project_preview.status_code == 404
    assert removed_project_tree.status_code == 404
    assert document.status_code == 200
    assert document.json()["content"] == "# 订单项目"
    assert removed_project_document.status_code == 404
    assert deleted_workspace.status_code == 204
    assert sources_after_delete.status_code == 200
    assert sources_after_delete.json()[0]["project_count"] == 0


def test_failed_workspace_refresh_updates_error_summary(tmp_path: Path) -> None:
    workspace_root = tmp_path / "failed-refresh"
    (workspace_root / "service").mkdir(parents=True)
    agents_path = workspace_root / "docs" / "backend" / "service" / "AGENTS.md"
    _write_agents(agents_path, "刷新失败项目")
    app = _app(tmp_path)

    with TestClient(app) as client:
        workspace = client.post(
            "/api/workspaces",
            json={
                "name": "刷新失败工作空间",
                "workspace_type": "个人项目",
                "root_path": str(workspace_root),
            },
        ).json()
        project_response = client.post(
            f"/api/workspaces/{workspace['id']}/projects",
            json={
                "name": "刷新失败项目",
                "relative_path": "service",
                "document_relative_path": "docs/backend/service/AGENTS.md",
                "project_kind": "backend",
            },
        )
        assert project_response.status_code == 201

        agents_path.unlink()
        refresh_response = client.post(f"/api/workspaces/{workspace['id']}/refresh")
        latest_workspace = client.get(f"/api/workspaces/{workspace['id']}")
        latest_projects = client.get(f"/api/workspaces/{workspace['id']}/projects")

    assert refresh_response.status_code == 400
    assert latest_workspace.status_code == 200
    assert latest_workspace.json()["error_project_count"] == 1
    assert "找不到入口文件" in latest_projects.json()[0]["error"]


def test_workspace_project_rejects_path_escape(tmp_path: Path) -> None:
    workspace_root = tmp_path / "company"
    workspace_root.mkdir()
    app = _app(tmp_path)

    with TestClient(app) as client:
        workspace = client.post(
            "/api/workspaces",
            json={"name": "公司工作空间", "root_path": str(workspace_root)},
        ).json()
        response = client.post(
            f"/api/workspaces/{workspace['id']}/projects",
            json={
                "name": "越界项目",
                "relative_path": "../outside",
                "document_relative_path": "docs/backend/outside/AGENTS.md",
            },
        )

    assert response.status_code == 422


def test_workspace_project_requires_document_entry_under_docs(tmp_path: Path) -> None:
    workspace_root = tmp_path / "company"
    workspace_root.mkdir()
    _write_agents(workspace_root / "service" / "AGENTS.md", "旧入口")
    app = _app(tmp_path)

    with TestClient(app) as client:
        workspace = client.post(
            "/api/workspaces",
            json={"name": "公司工作空间", "root_path": str(workspace_root)},
        ).json()
        response = client.post(
            f"/api/workspaces/{workspace['id']}/projects",
            json={
                "name": "旧入口项目",
                "relative_path": "service",
                "document_relative_path": "service/AGENTS.md",
            },
        )

    assert response.status_code == 422
    assert "docs/" in response.text
