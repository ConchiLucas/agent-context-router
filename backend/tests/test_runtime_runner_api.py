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
            json={"lease_token": lease_token, "exit_code": 0},
            headers=headers,
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "succeeded"
