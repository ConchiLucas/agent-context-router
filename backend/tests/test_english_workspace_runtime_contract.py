import os
import subprocess
from pathlib import Path

import pytest
import yaml


def english_workspace_root() -> Path:
    configured = os.environ.get("ENGLISH_WORKSPACE_ROOT")
    if configured:
        return Path(configured)
    mounted = Path("/workspace/rob_english_word_workforce")
    if mounted.exists():
        return mounted
    return Path("/Users/conchi/workforce/rob_english_word_workforce")


def require_english_workspace() -> Path:
    root = english_workspace_root()
    required = root / "AGENTS.md"
    if not required.is_file():
        pytest.skip(f"英语工作空间契约夹具不可用：缺少 {required}")
    return root


def test_english_workspace_adopts_workspace_runtime_contract() -> None:
    root = require_english_workspace()
    agents = (root / "AGENTS.md").read_text()
    runtime_document = (root / "docs/shared/runtime-deployment-map.md").read_text()
    deploy = root / "deploy/context-router/workspace/start/deploy.sh"

    assert os.access(deploy, os.X_OK)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".env.local"],
        cwd=root,
        check=False,
    )
    assert ignored.returncode == 0
    for tool in (
        "apply_workspace_changes",
        "start_workspace",
        "get_workspace_operation",
    ):
        assert tool in agents
    assert "runtime-runner.workspace-id" in runtime_document
    assert "runtime-runner.project-id" in runtime_document


def test_english_workspace_exposes_canonical_deploy_sync_tree() -> None:
    root = require_english_workspace()
    expected_projects = {
        "word_select_dashboard/server",
        "word_select_dashboard/word-agent",
        "rob_english_word_back",
        "word_select_dashboard/web-react",
        "rob_english_word_front",
        "rob_english_word_cloze_web",
    }
    manifest_path = root / "deploy/context-router/manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 1
    assert set(manifest["project_order"]) == expected_projects
    workspace_entry = root / "deploy/context-router/workspace/start/deploy.sh"
    assert os.access(workspace_entry, os.X_OK)
    workspace_content = workspace_entry.read_text(encoding="utf-8")
    assert "RUNTIME_PROJECT_IDS" in workspace_content
    assert "deploy/context-router/full/deploy.sh" in workspace_content

    for relative_path in expected_projects:
        for mode in ("fast", "full"):
            entry = root / relative_path / f"deploy/context-router/{mode}/deploy.sh"
            assert os.access(entry, os.X_OK), str(entry)
            content = entry.read_text(encoding="utf-8")
            assert "RUNTIME_WORKSPACE_ID" in content
            assert "RUNTIME_PROJECT_ID" in content

        compose = (root / relative_path / "docker-compose.yml").read_text(encoding="utf-8")
        assert "runtime-runner.workspace-id" in compose
        assert "runtime-runner.project-id" in compose

    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "deploy/context-router/README.md" in agents
    assert "deploy/context-router/workspace/start/deploy.sh" in agents
