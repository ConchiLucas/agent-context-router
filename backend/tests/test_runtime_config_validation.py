import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from context_router.config import Settings
from context_router.main import create_app
from context_router.repositories.document_search_repository import (
    InMemoryDocumentSearchRepository,
)
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.runtime_config_repository import (
    InMemoryRuntimeConfigRepository,
    RuntimeConfigFileDraft,
)
from context_router.repositories.runtime_operation_repository import (
    InMemoryRuntimeOperationRepository,
)
from context_router.repositories.runtime_runner_repository import (
    InMemoryRuntimeRunnerRepository,
)
from context_router.repositories.workspace_repository import InMemoryWorkspaceRepository
from context_router.schemas.runtime_configs import RuntimeConfigModeUpdate


def test_runtime_config_rejects_invalid_yaml_with_file_and_line() -> None:
    with pytest.raises(ValidationError, match=r"compose\.yml.*第 5 行"):
        RuntimeConfigModeUpdate.model_validate(
            {
                "files": [
                    {
                        "relative_path": "compose.yml",
                        "content": (
                            "services:\n  app:\n    command: |-\n    echo broken\nnext: value\n"
                        ),
                    }
                ]
            }
        )


def test_runtime_config_accepts_valid_yaml_literal_block_and_non_yaml() -> None:
    update = RuntimeConfigModeUpdate.model_validate(
        {
            "files": [
                {
                    "relative_path": "compose.yml",
                    "content": ("services:\n  app:\n    command: |-\n      echo valid\n"),
                },
                {
                    "relative_path": "deploy.sh",
                    "content": "not: [required to be yaml\n",
                    "executable": True,
                },
            ]
        }
    )

    assert [item.relative_path for item in update.files] == [
        "compose.yml",
        "deploy.sh",
    ]


def test_runtime_config_api_redacts_invalid_yaml_and_preserves_old_config(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    document = workspace_root / "docs/backend/AGENTS.md"
    document.parent.mkdir(parents=True)
    document.write_text("# Backend", encoding="utf-8")
    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace1",
        name="Workspace",
        root_path=str(workspace_root),
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
    runtime_repository = InMemoryRuntimeConfigRepository()
    runtime_repository.replace_files(
        "backend1",
        "fast",
        [RuntimeConfigFileDraft("deploy.sh", "#!/bin/sh\nexit 0\n", True)],
    )
    app = create_app(
        Settings(
            database_url=None,
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            workspace_mapping_file=None,
            runtime_root=tmp_path / "runtime",
        ),
        workspace_repository=workspace_repository,
        project_repository=project_repository,
        document_search_repository=InMemoryDocumentSearchRepository(),
        runtime_config_repository=runtime_repository,
    )
    client = TestClient(app)

    response = client.put(
        "/api/projects/backend1/runtime-config/fast",
        json={
            "files": [
                {
                    "relative_path": "compose.yml",
                    "content": (
                        "services:\n  app:\n    command: |-\n"
                        "    echo TOP_SECRET_MARKER\nnext: value\n"
                    ),
                }
            ]
        },
    )

    assert response.status_code == 422
    assert "compose.yml" in response.text
    assert "第 5 行" in response.text
    assert "TOP_SECRET_MARKER" not in response.text
    records = runtime_repository.list_files("backend1", "fast")
    assert [(record.relative_path, record.content) for record in records] == [
        ("deploy.sh", "#!/bin/sh\nexit 0\n")
    ]


def _project_update_app(tmp_path, *, runner_online: bool):
    workspace_root = tmp_path / "workspace"
    document = workspace_root / "docs/backend/AGENTS.md"
    document.parent.mkdir(parents=True)
    document.write_text("# Backend", encoding="utf-8")
    project_root = workspace_root / "backend"
    project_root.mkdir()
    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace1",
        name="Workspace",
        root_path=str(workspace_root),
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
    runtime_repository = InMemoryRuntimeConfigRepository()
    runtime_repository.replace_files(
        "backend1",
        "fast",
        [RuntimeConfigFileDraft("deploy.sh", "#!/bin/sh\nexit 0\n", True)],
    )
    runner_repository = InMemoryRuntimeRunnerRepository()
    if runner_online:
        runner_repository.register(
            runner_id="runner-1",
            hostname="mac",
            platform="darwin",
            version="1",
            capabilities=["docker"],
        )
    operation_repository = InMemoryRuntimeOperationRepository()
    app = create_app(
        Settings(
            database_url=None,
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            workspace_mapping_file=None,
            runtime_root=tmp_path / "runtime",
        ),
        workspace_repository=workspace_repository,
        project_repository=project_repository,
        document_search_repository=InMemoryDocumentSearchRepository(),
        runtime_config_repository=runtime_repository,
        runtime_runner_repository=runner_repository,
        runtime_operation_repository=operation_repository,
    )
    return app, operation_repository


def test_ui_project_update_is_queued_for_host_runtime_runner(tmp_path) -> None:
    app, operations = _project_update_app(tmp_path, runner_online=True)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/backend1/runtime-config/fast/execute",
            headers={"Origin": "http://127.0.0.1:49175"},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] is None
    assert body["workspace_id"] == "workspace1"
    assert body["kind"] == "project_update"
    assert body["trigger"] == "ui"
    assert body["status"] == "queued"
    assert body["steps"][0]["owner_id"] == "backend1"
    assert body["steps"][0]["mode"] == "fast"
    lease = operations.lease_next("runner-1", 30)
    assert lease is not None
    assert lease.operation.id == body["id"]


def test_ui_project_update_rejects_when_host_runtime_runner_is_offline(tmp_path) -> None:
    app, operations = _project_update_app(tmp_path, runner_online=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/backend1/runtime-config/fast/execute",
            headers={"Origin": "http://127.0.0.1:49175"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "宿主机 Runtime Runner 当前不可用"
    assert operations.list_operations("workspace1") == []
