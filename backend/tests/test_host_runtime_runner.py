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
        self.completed_forwarding: list[tuple[str, str, str, dict[str, object]]] = []

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

    def complete_forwarding_job(
        self,
        job_id: str,
        runner_id: str,
        lease_token: str,
        result: dict[str, object],
    ) -> None:
        self.completed_forwarding.append((job_id, runner_id, lease_token, result))


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
        "project_ids_by_relative_path": {
            ".": "project-root",
            "web-react": "project-web",
        },
        "lease_token": "l" * 48,
    }


def test_runner_executes_verified_fixed_entry_and_reports_success(tmp_path: Path) -> None:
    module = load_runner_module()
    runtime_root = tmp_path / "runtime"
    workspace_root = tmp_path / "workspaces" / "workspace1"
    workspace_root.mkdir(parents=True)
    create_snapshot(
        runtime_root,
        "#!/bin/sh\n"
        "printf 'runner-ok:%s\\n' \"$RUNTIME_WORKSPACE_ID\"\n"
        "printf 'environment:%s\\n' \"$C12_ENVIRONMENT\"\n"
        "printf '%s\\n' \"$RUNTIME_PROJECT_IDS\"\n",
    )
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
    log = (runtime_root / "runs/snapshot1/execution.log").read_text()
    assert "runner-ok:workspace1" in log
    assert "environment:local" in log
    assert ".\tproject-root" in log
    assert "web-react\tproject-web" in log


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


def test_runner_api_treats_connection_reset_as_recoverable(monkeypatch) -> None:
    module = load_runner_module()
    client = module.RunnerApiClient("http://127.0.0.1:49173", "x" * 48)

    def reset_connection(*_args, **_kwargs):
        raise ConnectionResetError("connection reset by peer")

    monkeypatch.setattr(module.urllib.request, "urlopen", reset_connection)

    with pytest.raises(module.RunnerError, match="控制面请求失败"):
        client.heartbeat_runner("runner-1")


def test_runner_executes_server_leased_forwarding_request(monkeypatch, tmp_path: Path) -> None:
    module = load_runner_module()

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "application/json", "Set-Cookie": "secret"}

        def __init__(self) -> None:
            self._chunks = [b'{"code":0}', b""]

        def read(self, _size: int) -> bytes:
            return self._chunks.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class FakeOpener:
        def open(self, request, timeout: int):
            assert request.full_url == "http://127.0.0.1:9000/read/page?pageNumber=1"
            assert request.method == "POST"
            assert timeout == 30
            assert request.headers["X-system-code"] == "mtp"
            return FakeResponse()

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *_args: FakeOpener())
    api = FakeApi()
    runner = module.HostRuntimeRunner(
        api=api,
        allowed_workspace_root=tmp_path,
        runtime_root=tmp_path,
    )
    runner.execute_forwarding_job(
        {
            "job_id": "job-1",
            "lease_token": "l" * 48,
            "request": {
                "method": "POST",
                "url": "http://127.0.0.1:9000/read/page",
                "headers": {"x-system-code": "mtp"},
                "query": {"pageNumber": 1},
                "body": {"pageSize": 10},
                "timeout_seconds": 30,
                "max_response_bytes": 1_048_576,
            },
        },
        runner_id="runner-1",
    )

    result = api.completed_forwarding[0]
    assert result[:3] == ("job-1", "runner-1", "l" * 48)
    assert result[3]["status_code"] == 200
    assert result[3]["response_body"] == '{"code":0}'
    assert result[3]["response_headers"] == {"content-type": "application/json"}


def test_runner_executes_allowlisted_host_action_with_default_local(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_runner_module()
    runtime_root = tmp_path / "runtime"
    workspace_root = tmp_path / "workspaces" / "workspace1"
    workspace_root.mkdir(parents=True)
    script_root = tmp_path / "script"
    script_root.mkdir()
    host_script = script_root / "ensure-panzhihua-host-runtime.sh"
    host_script.write_text(
        "#!/bin/sh\n"
        'printf \'command:%s environment:%s variable:%s\\n\' "$1" "$3" "$C12_ENVIRONMENT"\n'
    )
    host_script.chmod(0o750)
    monkeypatch.setattr(module, "HOST_SCRIPT_ROOT", script_root)
    monkeypatch.setattr(
        module,
        "HOST_ACTIONS",
        {"pzh.ensure-host-runtime": (host_script, "ensure", 10)},
    )
    api = FakeApi()
    runner = module.HostRuntimeRunner(
        api=api,
        allowed_workspace_root=tmp_path / "workspaces",
        runtime_root=runtime_root,
        heartbeat_seconds=1,
    )
    payload = {
        "operation": {
            "id": "operation-host",
            "workspace_id": "workspace1",
            "kind": "host_action",
            "action": "pzh.ensure-host-runtime",
            "workspace_host_root": str(workspace_root),
            "timeout_seconds": 10,
        },
        "steps": [
            {
                "id": "step-host",
                "owner_type": "workspace",
                "owner_id": "workspace1",
                "mode": "host",
                "snapshot_id": "host-snapshot",
                "snapshot_relative_path": ".",
                "entry_file": "deploy.sh",
                "log_relative_path": "runs/host-snapshot/execution.log",
                "project_relative_path": None,
            }
        ],
        "project_ids_by_relative_path": {},
        "lease_token": "h" * 48,
    }

    runner.execute_lease(payload)

    assert api.started == [("operation-host", "h" * 48)]
    assert api.completed == [("operation-host", "step-host", 0)]
    log = (runtime_root / "runs/host-snapshot/execution.log").read_text()
    assert "command:ensure environment:local variable:local" in log
