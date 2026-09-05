from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.api.runtime_runner import router
from context_router.config import Settings
from context_router.repositories.runtime_operation_repository import (
    InMemoryRuntimeOperationRepository,
    RuntimeOperationDraft,
    RuntimeOperationStepDraft,
)
from context_router.repositories.runtime_runner_repository import (
    InMemoryRuntimeRunnerRepository,
)


class FakeForwardingContextService:
    def __init__(self) -> None:
        self.completed: list[dict[str, object]] = []

    def lease_host_job(self, *, runner_id: str, lease_seconds: int):
        return {
            "job_id": "job-1",
            "lease_token": "l" * 48,
            "request": {
                "method": "POST",
                "url": "http://127.0.0.1:9000/read/page",
                "headers": {"X-System-Code": "mtp"},
                "query": {},
                "body": {"pageNumber": 1},
                "timeout_seconds": 30,
                "max_response_bytes": 1_048_576,
            },
        }

    def complete_host_job(self, **payload) -> None:
        self.completed.append(payload)


def build_app(tmp_path: Path) -> tuple[FastAPI, str]:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(mode=0o700)
    token = "a" * 48
    token_path = runtime_root / "runner.token"
    token_path.write_text(token)
    token_path.chmod(0o600)
    app = FastAPI()
    app.state.settings = Settings(
        runtime_root=runtime_root,
        runtime_runner_token_path=token_path,
        runtime_runner_lease_seconds=30,
    )
    app.state.runtime_runner_repository = InMemoryRuntimeRunnerRepository()
    app.state.runtime_operation_repository = InMemoryRuntimeOperationRepository()
    app.state.interface_forwarding_context_service = FakeForwardingContextService()
    app.include_router(router, prefix="/api")
    return app, token


def authorize(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_runner_api_requires_bearer_token_and_rejects_browser(tmp_path: Path) -> None:
    app, token = build_app(tmp_path)
    payload = {
        "runner_id": "runner-1",
        "hostname": "mac",
        "platform": "darwin",
        "version": "1",
        "capabilities": ["docker"],
    }
    with TestClient(app) as client:
        assert client.post("/api/runtime-runner/register", json=payload).status_code == 401
        assert (
            client.post(
                "/api/runtime-runner/register",
                json=payload,
                headers=authorize("wrong-token-value-that-is-long-enough"),
            ).status_code
            == 401
        )
        headers = {**authorize(token), "Origin": "http://127.0.0.1:49175"}
        assert (
            client.post("/api/runtime-runner/register", json=payload, headers=headers).status_code
            == 403
        )


def test_runner_can_register_lease_and_complete_operation(tmp_path: Path) -> None:
    app, token = build_app(tmp_path)
    operations = app.state.runtime_operation_repository
    operation = operations.create_operation(
        RuntimeOperationDraft(
            task_id=7,
            workspace_id="workspace1",
            kind="start_workspace",
            trigger="mcp",
            changed_files=(),
            steps=(
                RuntimeOperationStepDraft(
                    owner_type="workspace",
                    owner_id="workspace1",
                    mode="start",
                    snapshot_id="snapshot1",
                    snapshot_relative_path="workspaces/workspace1/start/snapshot1",
                    changed_files=(),
                    decision_reason="start",
                    log_relative_path="runs/snapshot1/execution.log",
                ),
            ),
        )
    )
    headers = authorize(token)
    with TestClient(app) as client:
        registered = client.post(
            "/api/runtime-runner/register",
            json={
                "runner_id": "runner-1",
                "hostname": "mac",
                "platform": "darwin",
                "version": "1",
                "capabilities": ["docker"],
            },
            headers=headers,
        )
        assert registered.status_code == 200
        lease = client.post(
            "/api/runtime-runner/lease",
            json={"runner_id": "runner-1"},
            headers=headers,
        )
        assert lease.status_code == 200
        body = lease.json()
        assert body["operation"]["id"] == operation.id
        assert body["operation"]["environment"] == "local"
        assert body["operation"]["action"] is None
        assert body["project_ids_by_relative_path"] == {}
        assert body["steps"][0]["snapshot_relative_path"].startswith("workspaces/")
        assert "content" not in str(body)
        lease_token = body["lease_token"]

        wrong = client.post(
            f"/api/runtime-runner/operations/{operation.id}/started",
            json={"lease_token": "x" * 32},
            headers=headers,
        )
        assert wrong.status_code == 409
        started = client.post(
            f"/api/runtime-runner/operations/{operation.id}/started",
            json={"lease_token": lease_token},
            headers=headers,
        )
        assert started.status_code == 200
        step_id = body["steps"][0]["id"]
        completed = client.post(
            f"/api/runtime-runner/operations/{operation.id}/steps/{step_id}/complete",
            json={
                "lease_token": lease_token,
                "exit_code": 0,
                "readiness": {
                    "revision": 9,
                    "infrastructure": {"status": "ready", "duration_ms": 1000},
                    "services": {"status": "ready", "duration_ms": 2000},
                    "business": {"status": "ready", "duration_ms": 300},
                },
            },
            headers=headers,
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "succeeded"
        assert operations.list_steps(operation.id)[0].readiness == {
            "revision": 9,
            "infrastructure": {
                "status": "ready",
                "duration_ms": 1000,
                "error_message": None,
            },
            "services": {
                "status": "ready",
                "duration_ms": 2000,
                "error_message": None,
            },
            "business": {
                "status": "ready",
                "duration_ms": 300,
                "error_message": None,
            },
        }


def test_runner_can_lease_and_complete_forwarding_job(tmp_path: Path) -> None:
    app, token = build_app(tmp_path)
    headers = authorize(token)
    with TestClient(app) as client:
        registered = client.post(
            "/api/runtime-runner/register",
            json={
                "runner_id": "runner-forwarding",
                "hostname": "mac",
                "platform": "darwin",
                "version": "1",
                "capabilities": ["interface-forwarding"],
            },
            headers=headers,
        )
        assert registered.status_code == 200

        leased = client.post(
            "/api/runtime-runner/forwarding/lease",
            json={"runner_id": "runner-forwarding"},
            headers=headers,
        )
        assert leased.status_code == 200
        assert leased.json()["job"]["job_id"] == "job-1"

        completed = client.post(
            "/api/runtime-runner/forwarding/jobs/job-1/complete",
            json={
                "runner_id": "runner-forwarding",
                "lease_token": "l" * 48,
                "status_code": 200,
                "response_body": '{"code":0}',
                "response_headers": {"content-type": "application/json"},
                "response_bytes": 10,
                "response_truncated": False,
                "duration_ms": 12,
            },
            headers=headers,
        )
        assert completed.status_code == 200
        saved = app.state.interface_forwarding_context_service.completed[0]
        assert saved["runner_id"] == "runner-forwarding"
        assert saved["status_code"] == 200
