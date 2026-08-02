import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def load_runner_module() -> object:
    path = Path(__file__).parents[2] / "scripts" / "context_router_host_runner.py"
    spec = importlib.util.spec_from_file_location("context_router_host_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeApi:
    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.completed: list[tuple[str, str, int]] = []

    def started_operation(self, operation_id: str, lease_token: str) -> None:
        self.started.append((operation_id, lease_token))

    def heartbeat_operation(self, operation_id: str, lease_token: str) -> None:
        pass

    def complete_step(
        self,
        operation_id: str,
        step_id: str,
        lease_token: str,
        exit_code: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.completed.append((operation_id, step_id, exit_code))


def create_snapshot(runtime_root: Path, content: str) -> Path:
    snapshot = runtime_root / "workspaces" / "workspace1" / "start" / "snapshot1"
    snapshot.mkdir(parents=True)
    entry = snapshot / "deploy.sh"
    entry.write_text(content)
    entry.chmod(0o750)
    encoded = content.encode()
    manifest = {
        "schema_version": 1,
        "snapshot_id": "snapshot1",
        "owner_type": "workspace",
        "owner_id": "workspace1",
        "profile": "start",
        "created_at": "2026-08-02T00:00:00+00:00",
        "file_count": 1,
        "total_bytes": len(encoded),
        "files": [
            {
                "relative_path": "deploy.sh",
                "executable": True,
                "size_bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        ],
    }
    canonical = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    (snapshot / ".runtime-manifest.json").write_text(json.dumps(manifest))
    return snapshot


def lease(runtime_root: Path, workspace_root: Path) -> dict[str, object]:
    return {
        "operation": {
            "id": "operation1",
            "workspace_id": "workspace1",
            "kind": "start_workspace",
            "workspace_host_root": str(workspace_root),
            "timeout_seconds": 10,
        },
        "steps": [
            {
                "id": "step1",
                "owner_type": "workspace",
                "owner_id": "workspace1",
                "mode": "start",
                "snapshot_id": "snapshot1",
                "snapshot_relative_path": "workspaces/workspace1/start/snapshot1",
                "entry_file": "deploy.sh",
                "log_relative_path": "runs/snapshot1/execution.log",
                "project_relative_path": None,
            }
        ],
        "lease_token": "l" * 48,
    }


def test_runner_executes_verified_fixed_entry_and_reports_success(tmp_path: Path) -> None:
    module = load_runner_module()
    runtime_root = tmp_path / "runtime"
    workspace_root = tmp_path / "workspaces" / "workspace1"
    workspace_root.mkdir(parents=True)
    create_snapshot(runtime_root, "#!/bin/sh\nprintf 'runner-ok\\n'\n")
    api = FakeApi()
    runner = module.HostRuntimeRunner(
        api=api,
        allowed_workspace_root=tmp_path / "workspaces",
        runtime_root=runtime_root,
        heartbeat_seconds=1,
    )

    runner.execute_lease(lease(runtime_root, workspace_root))

    assert api.started == [("operation1", "l" * 48)]
    assert api.completed == [("operation1", "step1", 0)]
    assert "runner-ok" in (runtime_root / "runs/snapshot1/execution.log").read_text()


def test_runner_rejects_manifest_mismatch_without_executing(tmp_path: Path) -> None:
    module = load_runner_module()
    runtime_root = tmp_path / "runtime"
    workspace_root = tmp_path / "workspaces" / "workspace1"
    workspace_root.mkdir(parents=True)
    snapshot = create_snapshot(runtime_root, "#!/bin/sh\nexit 0\n")
    (snapshot / "deploy.sh").write_text("#!/bin/sh\nexit 9\n")
    api = FakeApi()
    runner = module.HostRuntimeRunner(
        api=api,
        allowed_workspace_root=tmp_path / "workspaces",
        runtime_root=runtime_root,
        heartbeat_seconds=1,
    )

    runner.execute_lease(lease(runtime_root, workspace_root))

    assert api.started == []
    assert api.completed[0][2] != 0


def test_runner_rejects_symlink_snapshot(tmp_path: Path) -> None:
    module = load_runner_module()
    runtime_root = tmp_path / "runtime"
    workspace_root = tmp_path / "workspaces" / "workspace1"
    workspace_root.mkdir(parents=True)
    target = create_snapshot(runtime_root, "#!/bin/sh\nexit 0\n")
    alias = runtime_root / "workspaces/workspace1/start/alias"
    alias.symlink_to(target, target_is_directory=True)
    payload = lease(runtime_root, workspace_root)
    payload["steps"][0]["snapshot_relative_path"] = "workspaces/workspace1/start/alias"
    api = FakeApi()
    runner = module.HostRuntimeRunner(
        api=api,
        allowed_workspace_root=tmp_path / "workspaces",
        runtime_root=runtime_root,
        heartbeat_seconds=1,
    )

    runner.execute_lease(payload)

    assert api.started == []
    assert api.completed[0][2] != 0


def test_runner_token_requires_private_regular_file(tmp_path: Path) -> None:
    module = load_runner_module()
    token = tmp_path / "runner.token"
    token.write_text("x" * 48)
    token.chmod(0o644)

    with pytest.raises(module.RunnerSecurityError, match="0600"):
        module.load_private_token(token)
