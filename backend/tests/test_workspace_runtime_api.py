from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.api.workspace_runtime import router
from context_router.middleware.browser_read_only import BrowserReadOnlyMiddleware
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.runtime_operation_repository import (
    InMemoryRuntimeOperationRepository,
)
from context_router.repositories.workspace_repository import InMemoryWorkspaceRepository
from context_router.repositories.workspace_runtime_repository import (
    InMemoryWorkspaceRuntimeRepository,
)


def build_app(tmp_path: Path) -> tuple[FastAPI, str]:
    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace1",
        name="Workspace",
        root_path=str(tmp_path),
    )
    project_repository = InMemoryProjectRepository(workspace_repository)
    project_repository.create_project(
        project_id="backend1",
        name="Backend",
        workspace_id="workspace1",
        relative_path="backend",
        document_relative_path="docs/backend/AGENTS.md",
        project_kind="backend",
    )
    app = FastAPI()
    app.state.workspace_repository = workspace_repository
    app.state.project_repository = project_repository
    app.state.workspace_runtime_repository = InMemoryWorkspaceRuntimeRepository()
    app.state.runtime_operation_repository = InMemoryRuntimeOperationRepository()
    app.add_middleware(BrowserReadOnlyMiddleware, api_prefix="/api")
    app.include_router(router, prefix="/api")
    return app, "workspace1"


def test_ai_client_can_manage_single_workspace_runtime_entry(tmp_path: Path) -> None:
    app, workspace_id = build_app(tmp_path)
    with TestClient(app) as client:
        saved = client.put(
            f"/api/workspaces/{workspace_id}/runtime-config/start",
            json={
                "files": [
                    {
                        "relative_path": "deploy.sh",
                        "content": "#!/bin/sh\nexit 0\n",
                        "executable": True,
                    }
                ]
            },
        )
        policy = client.put(
            f"/api/workspaces/{workspace_id}/runtime-policy",
            json={
                "project_order": ["backend1"],
                "workspace_paths": ["deploy-compose-full.sh", ".env.example"],
            },
        )
        fetched = client.get(f"/api/workspaces/{workspace_id}/runtime-config")

    assert saved.status_code == 200
    assert policy.status_code == 200
    assert fetched.status_code == 200
    assert fetched.json()["start"]["files"][0]["relative_path"] == "deploy.sh"
    assert fetched.json()["policy"]["project_order"] == ["backend1"]
    assert ".env.local" not in str(fetched.json())


def test_runtime_config_requires_fixed_executable_entry_and_valid_projects(
    tmp_path: Path,
) -> None:
    app, workspace_id = build_app(tmp_path)
    with TestClient(app) as client:
        missing_entry = client.put(
            f"/api/workspaces/{workspace_id}/runtime-config/start",
            json={"files": [{"relative_path": "other.sh", "content": "", "executable": True}]},
        )
        invalid_project = client.put(
            f"/api/workspaces/{workspace_id}/runtime-policy",
            json={"project_order": ["other"], "workspace_paths": []},
        )

    assert missing_entry.status_code == 422
    assert invalid_project.status_code == 400


def test_browser_cannot_write_workspace_runtime_configuration(tmp_path: Path) -> None:
    app, workspace_id = build_app(tmp_path)
    with TestClient(app) as client:
        response = client.put(
            f"/api/workspaces/{workspace_id}/runtime-config/start",
            headers={"Origin": "http://127.0.0.1:49174"},
            json={
                "files": [
                    {
                        "relative_path": "deploy.sh",
                        "content": "#!/bin/sh\n",
                        "executable": True,
                    }
                ]
            },
        )

    assert response.status_code == 405
