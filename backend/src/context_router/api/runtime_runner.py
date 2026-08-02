from __future__ import annotations

import hmac
import stat
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from context_router.repositories.runtime_operation_repository import (
    RuntimeOperationRepositoryError,
    RuntimeStepResult,
)
from context_router.repositories.runtime_runner_repository import (
    RuntimeRunnerRepositoryError,
)
from context_router.schemas.workspace_runtime import (
    RunnerLeaseRequest,
    RunnerOperationRequest,
    RunnerRegistration,
    RunnerStepResultRequest,
)

router = APIRouter(prefix="/runtime-runner", tags=["runtime-runner"])


@router.get("/status")
def runner_status(request: Request) -> dict[str, object]:
    _authorize(request)
    settings = request.app.state.settings
    try:
        available = request.app.state.runtime_runner_repository.is_available(
            settings.runtime_runner_heartbeat_ttl_seconds
        )
    except RuntimeRunnerRepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"available": available}


@router.post("/register")
def register_runner(payload: RunnerRegistration, request: Request) -> dict[str, object]:
    _authorize(request)
    try:
        record = request.app.state.runtime_runner_repository.register(
            runner_id=payload.runner_id,
            hostname=payload.hostname,
            platform=payload.platform,
            version=payload.version,
            capabilities=payload.capabilities,
        )
    except RuntimeRunnerRepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _runner(record)


@router.post("/heartbeat")
def heartbeat_runner(payload: RunnerLeaseRequest, request: Request) -> dict[str, object]:
    _authorize(request)
    try:
        record = request.app.state.runtime_runner_repository.heartbeat(payload.runner_id)
    except RuntimeRunnerRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _runner(record)


@router.post("/lease")
def lease_operation(payload: RunnerLeaseRequest, request: Request) -> dict[str, object]:
    _authorize(request)
    settings = request.app.state.settings
    runner_repository = request.app.state.runtime_runner_repository
    if runner_repository.get(payload.runner_id) is None:
        raise HTTPException(status_code=409, detail="host_runner_not_registered")
    operations = request.app.state.runtime_operation_repository
    try:
        operations.reconcile_expired()
        lease = operations.lease_next(
            payload.runner_id,
            settings.runtime_runner_lease_seconds,
        )
    except RuntimeOperationRepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if lease is None:
        return {"operation": None, "steps": [], "lease_token": None}
    workspace_host_root = _workspace_host_root(request, lease.operation.workspace_id)
    projects = _project_relative_paths(request, lease.operation.workspace_id)
    return {
        "operation": {
            "id": lease.operation.id,
            "workspace_id": lease.operation.workspace_id,
            "kind": lease.operation.kind,
            "status": lease.operation.status,
            "workspace_host_root": workspace_host_root,
            "timeout_seconds": settings.runtime_execution_timeout_seconds,
        },
        "steps": [
            {
                "id": step.id,
                "sequence": step.sequence,
                "owner_type": step.owner_type,
                "owner_id": step.owner_id,
                "mode": step.mode,
                "snapshot_id": step.snapshot_id,
                "snapshot_relative_path": step.snapshot_relative_path,
                "entry_file": "deploy.sh",
                "log_relative_path": step.log_relative_path,
                "project_relative_path": projects.get(step.owner_id),
            }
            for step in lease.steps
        ],
        "lease_token": lease.lease_token,
    }


@router.post("/operations/{operation_id}/started")
def operation_started(
    operation_id: str,
    payload: RunnerOperationRequest,
    request: Request,
) -> dict[str, object]:
    _authorize(request)
    try:
        record = request.app.state.runtime_operation_repository.mark_started(
            operation_id, payload.lease_token
        )
    except RuntimeOperationRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _operation(record)


@router.post("/operations/{operation_id}/heartbeat")
def operation_heartbeat(
    operation_id: str,
    payload: RunnerOperationRequest,
    request: Request,
) -> dict[str, object]:
    _authorize(request)
    try:
        record = request.app.state.runtime_operation_repository.heartbeat(
            operation_id,
            payload.lease_token,
            request.app.state.settings.runtime_runner_lease_seconds,
        )
    except RuntimeOperationRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _operation(record)


@router.post("/operations/{operation_id}/steps/{step_id}/complete")
def complete_step(
    operation_id: str,
    step_id: str,
    payload: RunnerStepResultRequest,
    request: Request,
) -> dict[str, object]:
    _authorize(request)
    try:
        record = request.app.state.runtime_operation_repository.complete_step(
            operation_id,
            step_id,
            payload.lease_token,
            RuntimeStepResult(
                exit_code=payload.exit_code,
                error_code=payload.error_code,
                error_message=payload.error_message,
            ),
        )
    except RuntimeOperationRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _operation(record)


@router.post("/operations/{operation_id}/complete")
def complete_operation(
    operation_id: str,
    payload: RunnerOperationRequest,
    request: Request,
) -> dict[str, object]:
    _authorize(request)
    operations = request.app.state.runtime_operation_repository
    try:
        operations.heartbeat(
            operation_id,
            payload.lease_token,
            request.app.state.settings.runtime_runner_lease_seconds,
        )
        record = operations.get_operation(operation_id)
    except RuntimeOperationRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None or record.status not in {"succeeded", "failed", "interrupted"}:
        raise HTTPException(status_code=409, detail="runtime_operation_not_terminal")
    return _operation(record)


def _authorize(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.runtime_runner_api_enabled:
        raise HTTPException(status_code=404, detail="runtime_runner_api_disabled")
    if any(
        request.headers.get(name) is not None
        for name in ("origin", "sec-fetch-mode", "sec-fetch-site")
    ):
        raise HTTPException(status_code=403, detail="runtime_runner_browser_forbidden")
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="runtime_runner_unauthorized",
        )
    expected = _load_token(settings.runtime_runner_token_path)
    provided = header.removeprefix("Bearer ")
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="runtime_runner_unauthorized",
        )


def _load_token(token_path: Path) -> str:
    try:
        metadata = token_path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError("token path is not a regular file")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise OSError("token permissions are too broad")
        value = token_path.read_text(encoding="utf-8").strip()
        if len(value) < 32:
            raise OSError("token is too short")
        return value
    except OSError as exc:
        raise HTTPException(status_code=503, detail="runtime_runner_token_unavailable") from exc


def _workspace_host_root(request: Request, workspace_id: str) -> str:
    repository = getattr(request.app.state, "workspace_repository", None)
    if repository is not None:
        try:
            return str(repository.get_workspace(workspace_id).root_path)
        except Exception:
            pass
    return str(request.app.state.settings.workspace_host_root)


def _project_relative_paths(request: Request, workspace_id: str) -> dict[str, str]:
    repository = getattr(request.app.state, "project_repository", None)
    if repository is None:
        return {}
    try:
        return {
            item.id: item.relative_path
            for item in repository.list_projects(workspace_id=workspace_id)
        }
    except Exception:
        return {}


def _runner(record: object) -> dict[str, object]:
    return {
        "runner_id": record.id,
        "hostname": record.hostname,
        "platform": record.platform,
        "version": record.version,
        "capabilities": list(record.capabilities),
        "status": record.status,
        "started_at": record.started_at,
        "last_heartbeat_at": record.last_heartbeat_at,
    }


def _operation(record: object) -> dict[str, object]:
    return {
        "id": record.id,
        "workspace_id": record.workspace_id,
        "status": record.status,
        "current_step": record.current_step,
        "error_code": record.error_code,
        "error_message": record.error_message,
    }
