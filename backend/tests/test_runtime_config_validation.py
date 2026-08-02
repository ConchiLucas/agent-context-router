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
