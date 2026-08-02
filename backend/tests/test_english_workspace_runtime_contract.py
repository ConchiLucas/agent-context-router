import os
import subprocess
from pathlib import Path


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
