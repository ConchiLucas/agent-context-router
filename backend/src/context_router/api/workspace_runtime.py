from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from context_router.repositories.project_repository import ProjectRepositoryError
from context_router.repositories.runtime_operation_repository import (
    RuntimeOperationRepositoryError,
)
from context_router.repositories.workspace_repository import WorkspaceRepositoryError
from context_router.repositories.workspace_runtime_repository import (
    WorkspaceRuntimeFileDraft as StoredRuntimeFileDraft,
)
from context_router.repositories.workspace_runtime_repository import (
    WorkspaceRuntimePolicyDraft as StoredRuntimePolicyDraft,
)
from context_router.repositories.workspace_runtime_repository import (
    WorkspaceRuntimeRepositoryError,
)
from context_router.schemas.workspace_runtime import (
    WorkspaceRuntimeConfigUpdate,
    WorkspaceRuntimePolicyUpdate,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workspace-runtime"])


@router.get("/runtime-config")
def get_workspace_runtime_config(workspace_id: str, request: Request) -> dict[str, object]:
    _workspace(request, workspace_id)
    repository = request.app.state.workspace_runtime_repository
    try:
        files = repository.list_files(workspace_id, "start")
        policy = repository.get_policy(workspace_id)
    except WorkspaceRuntimeRepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "workspace_id": workspace_id,
        "start": {
            "profile": "start",
            "files": [_file(item) for item in files],
            "updated_at": max((item.updated_at for item in files), default=None),
        },
        "policy": _policy(policy),
    }


@router.put("/runtime-config/start")
def replace_workspace_start_config(
    workspace_id: str,
    payload: WorkspaceRuntimeConfigUpdate,
    request: Request,
) -> dict[str, object]:
    _workspace(request, workspace_id)
    drafts = [
        StoredRuntimeFileDraft(
            relative_path=item.relative_path,
            content=item.content,
            executable=item.executable,
        )
        for item in payload.files
    ]
    try:
        files = request.app.state.workspace_runtime_repository.replace_files(
            workspace_id, "start", drafts
        )
    except WorkspaceRuntimeRepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "workspace_id": workspace_id,
        "profile": "start",
        "files": [_file(item) for item in files],
    }


@router.put("/runtime-policy")
def save_workspace_runtime_policy(
    workspace_id: str,
    payload: WorkspaceRuntimePolicyUpdate,
    request: Request,
) -> dict[str, object]:
    _workspace(request, workspace_id)
    try:
        project_ids = {
            item.id
            for item in request.app.state.project_repository.list_projects(
                workspace_id=workspace_id
            )
        }
    except ProjectRepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    unknown = [item for item in payload.project_order if item not in project_ids]
    if unknown:
        raise HTTPException(status_code=400, detail=f"项目不属于当前工作空间：{unknown[0]}")
    try:
        record = request.app.state.workspace_runtime_repository.save_policy(
            workspace_id,
            StoredRuntimePolicyDraft(
                project_order=tuple(payload.project_order),
                workspace_paths=tuple(payload.workspace_paths),
            ),
        )
    except WorkspaceRuntimeRepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _policy(record)


@router.get("/runtime-operations")
def list_workspace_runtime_operations(
    workspace_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    _workspace(request, workspace_id)
    try:
        records = request.app.state.runtime_operation_repository.list_operations(
            workspace_id, limit
        )
    except RuntimeOperationRepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [_operation(item) for item in records]


@router.get("/runtime-operations/{operation_id}")
def get_workspace_runtime_operation(
    workspace_id: str,
    operation_id: str,
    request: Request,
    log_characters: int = Query(default=10_000, ge=1, le=50_000),
) -> dict[str, object]:
    _workspace(request, workspace_id)
    service = request.app.state.workspace_runtime_orchestration_service
    try:
        result = service.get_operation(operation_id, log_characters)
    except Exception as exc:
        code = getattr(exc, "code", "runtime_operation_unavailable")
        status_code = 404 if code == "runtime_operation_not_found" else 503
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if result.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="运行操作不存在")
    return result.model_dump(mode="json", exclude_none=True)


def _workspace(request: Request, workspace_id: str) -> object:
    try:
        return request.app.state.workspace_repository.get_workspace(workspace_id)
    except WorkspaceRepositoryError as exc:
        raise HTTPException(status_code=404, detail="工作空间不存在") from exc


def _file(record: object) -> dict[str, object]:
    return {
        "id": record.id,
        "relative_path": record.relative_path,
        "content": record.content,
        "executable": record.executable,
        "sort_order": record.sort_order,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _policy(record: object | None) -> dict[str, object]:
    return {
        "project_order": list(record.project_order) if record else [],
        "workspace_paths": list(record.workspace_paths) if record else [],
        "created_at": record.created_at if record else None,
        "updated_at": record.updated_at if record else None,
    }


def _operation(record: object) -> dict[str, object]:
    return {
        "id": record.id,
        "task_id": record.task_id,
        "kind": record.kind,
        "trigger": record.trigger,
        "status": record.status,
        "changed_files": list(record.changed_files),
        "current_step": record.current_step,
        "runner_id": record.runner_id,
        "error_code": record.error_code,
        "error_message": record.error_message,
        "created_at": record.created_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
    }
