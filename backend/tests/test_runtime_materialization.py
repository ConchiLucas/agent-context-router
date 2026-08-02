import json
from pathlib import Path

from context_router.repositories.workspace_runtime_repository import (
    InMemoryWorkspaceRuntimeRepository,
    WorkspaceRuntimeFileDraft,
)
from context_router.services.runtime_materialization import RuntimeMaterializationService


def test_materializes_workspace_snapshot_with_general_owner_manifest(tmp_path: Path) -> None:
    repository = InMemoryWorkspaceRuntimeRepository()
    files = repository.replace_files(
        "workspace1",
        "start",
        [WorkspaceRuntimeFileDraft("deploy.sh", "#!/bin/sh\nexit 0\n", True)],
    )

    result = RuntimeMaterializationService(tmp_path).materialize_workspace("workspace1", files)

    assert result.owner_type == "workspace"
    assert result.owner_id == "workspace1"
    assert result.profile == "start"
    assert result.snapshot_relative_path.startswith("workspaces/workspace1/start/")
    manifest = json.loads((Path(result.materialized_path) / ".runtime-manifest.json").read_text())
    assert manifest["owner_type"] == "workspace"
    assert manifest["owner_id"] == "workspace1"
    assert manifest["profile"] == "start"
