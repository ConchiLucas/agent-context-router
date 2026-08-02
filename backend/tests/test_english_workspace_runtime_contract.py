import os
import subprocess
from pathlib import Path

import yaml


def english_workspace_root() -> Path:
    configured = os.environ.get("ENGLISH_WORKSPACE_ROOT")
    if configured:
        return Path(configured)
    mounted = Path("/workspace/rob_english_word_workforce")
    if mounted.exists():
        return mounted
    return Path("/Users/conchi/workforce/rob_english_word_workforce")


def test_english_workspace_adopts_workspace_runtime_contract() -> None:
    root = english_workspace_root()
    agents = (root / "AGENTS.md").read_text()
    runtime_document = (root / "docs/shared/runtime-deployment-map.md").read_text()
    deploy = root / "deploy-compose-full.sh"

    assert os.access(deploy, os.X_OK)
    assert (root / ".env.example").is_file()
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
    assert '"$WORKSPACE_HOST_ROOT/deploy-compose-full.sh"' in runtime_document
    assert "不使用 Docker/launchd 开机自启动" in runtime_document


def test_english_workspace_exposes_canonical_deploy_sync_tree() -> None:
    root = english_workspace_root()
    expected_projects = {
        "word_select_dashboard/server": "word-select-dashboard-server",
        "word_select_dashboard/word-agent": "word-agent",
        "rob_english_word_back": "rob-english-word-back",
        "word_select_dashboard/web-react": "word-select-dashboard-web",
        "rob_english_word_front": "rob-english-word-front",
        "rob_english_word_cloze_web": "rob-english-word-cloze-web",
    }
    manifest_path = root / "deploy/context-router/manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 1
    assert set(manifest["project_order"]) == set(expected_projects)
    workspace_entry = root / "deploy/context-router/workspace/start/deploy.sh"
    assert os.access(workspace_entry, os.X_OK)
    assert "deploy-compose-full.sh" in workspace_entry.read_text(encoding="utf-8")

    for relative_path, project_key in expected_projects.items():
        for mode in ("fast", "full"):
            entry = root / relative_path / f"deploy/context-router/{mode}/deploy.sh"
            assert os.access(entry, os.X_OK), str(entry)
            content = entry.read_text(encoding="utf-8")
            assert "WORKSPACE_HOST_ROOT" in content
            assert f"--project {project_key}" in content

    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "deploy/context-router/README.md" in agents
    assert "deploy/context-router/workspace/start/deploy.sh" in agents
