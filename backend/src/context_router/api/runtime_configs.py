from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.repositories.runtime_config_repository import (
    RuntimeConfigFileDraft,
    RuntimeConfigFileRecord,
    RuntimeConfigRepositoryError,
    RuntimeConfigStore,
)
from context_router.repositories.runtime_run_repository import RuntimeRunRecord
from context_router.schemas.runtime_configs import (
    ProjectRuntimeConfig,
    RuntimeConfigFile,
    RuntimeConfigMode,
    RuntimeConfigModeUpdate,
    RuntimeMaterializationResult,
    RuntimeMode,
    RuntimeRunLog,
    RuntimeRunSummary,
)
from context_router.schemas.workspace_runtime import RuntimeOperationView
from context_router.services.project_registry import ProjectRegistryError
from context_router.services.runtime_execution import RuntimeExecutionError
from context_router.services.runtime_materialization import RuntimeMaterializationError
from context_router.services.workspace_runtime_orchestration import (
    WorkspaceRuntimeOrchestrationError,
)

router = APIRouter(prefix="/projects", tags=["project-runtime-config"])


def _repository(request: Request) -> RuntimeConfigStore:
    return request.app.state.runtime_config_repository


def _project(request: Request, project_id: str):
    try:
        return request.app.state.project_registry.get_project_summary(project_id)
    except ProjectRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在",
        ) from exc


def _mode(mode: RuntimeMode, records: list[RuntimeConfigFileRecord]) -> RuntimeConfigMode:
    files = [
        RuntimeConfigFile(
            id=item.id,
            relative_path=item.relative_path,
            content=item.content,
            executable=item.executable,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in records
    ]
    return RuntimeConfigMode(
        mode=mode,
        files=files,
        updated_at=max((item.updated_at for item in records), default=None),
    )


def _run(record: RuntimeRunRecord) -> RuntimeRunSummary:
    return RuntimeRunSummary(
        id=record.id,
        project_id=record.project_id,
        mode=record.mode,  # type: ignore[arg-type]
        trigger=record.trigger,  # type: ignore[arg-type]
        status=record.status,  # type: ignore[arg-type]
        snapshot_id=record.snapshot_id,
        materialized_path=record.materialized_path,
        project_root=record.project_root,
        entry_file=record.entry_file,
        changed_files=list(record.changed_files),
        decision_reason=record.decision_reason,
        exit_code=record.exit_code,
        error_message=record.error_message,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


@router.get(
    "/{project_id}/runtime-config",
    response_model=ProjectRuntimeConfig,
)
def get_project_runtime_config(
    project_id: str,
    request: Request,
) -> ProjectRuntimeConfig:
    project = _project(request, project_id)
    try:
        fast = _mode("fast", _repository(request).list_files(project_id, "fast"))
        full = _mode("full", _repository(request).list_files(project_id, "full"))
    except RuntimeConfigRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return ProjectRuntimeConfig(project=project, fast=fast, full=full)


@router.put(
    "/{project_id}/runtime-config/{mode}",
    response_model=RuntimeConfigMode,
)
def save_project_runtime_config(
    project_id: str,
    mode: RuntimeMode,
    payload: RuntimeConfigModeUpdate,
    request: Request,
) -> RuntimeConfigMode:
    _project(request, project_id)
    drafts = [
        RuntimeConfigFileDraft(
            relative_path=item.relative_path,
            content=item.content,
            executable=item.executable,
        )
        for item in payload.files
    ]
    try:
        records = _repository(request).replace_files(project_id, mode, drafts)
    except RuntimeConfigRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return _mode(mode, records)


@router.post(
    "/{project_id}/runtime-config/{mode}/materialize",
    response_model=RuntimeMaterializationResult,
)
def materialize_project_runtime_config(
    project_id: str,
    mode: RuntimeMode,
    request: Request,
) -> RuntimeMaterializationResult:
    _project(request, project_id)
    try:
        files = _repository(request).list_files(project_id, mode)
        result = request.app.state.runtime_materialization_service.materialize(
            project_id,
            mode,
            files,
        )
    except RuntimeConfigRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except RuntimeMaterializationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return RuntimeMaterializationResult(
        snapshot_id=result.snapshot_id,
        project_id=result.project_id,
        mode=mode,
        materialized_path=result.materialized_path,
        file_count=result.file_count,
        total_bytes=result.total_bytes,
        manifest_sha256=result.manifest_sha256,
        created_at=result.created_at,
    )


@router.post(
    "/{project_id}/runtime-config/{mode}/execute",
    response_model=RuntimeOperationView,
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_project_runtime_config(
    project_id: str,
    mode: RuntimeMode,
    request: Request,
) -> RuntimeOperationView:
    _project(request, project_id)
    try:
        return request.app.state.workspace_runtime_orchestration_service.update_project(
            project_id=project_id,
            mode=mode,
            trigger="ui",
        )
    except WorkspaceRuntimeOrchestrationError as exc:
        response_status = (
            status.HTTP_404_NOT_FOUND
            if exc.code in {"project_not_found", "workspace_not_found"}
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=response_status,
            detail=str(exc),
        ) from exc


@router.get(
    "/{project_id}/runtime-runs",
    response_model=list[RuntimeRunSummary],
)
def list_project_runtime_runs(
    project_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[RuntimeRunSummary]:
    _project(request, project_id)
    try:
        records = request.app.state.runtime_execution_service.list_runs(project_id, limit)
    except RuntimeExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return [_run(item) for item in records]


@router.get(
    "/{project_id}/runtime-runs/{run_id}",
    response_model=RuntimeRunSummary,
)
def get_project_runtime_run(
    project_id: str,
    run_id: str,
    request: Request,
) -> RuntimeRunSummary:
    _project(request, project_id)
    try:
        record = request.app.state.runtime_execution_service.get_run(run_id)
    except RuntimeExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    if record.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="运行任务不存在",
        )
    return _run(record)


@router.get(
    "/{project_id}/runtime-runs/{run_id}/log",
    response_model=RuntimeRunLog,
)
def get_project_runtime_run_log(
    project_id: str,
    run_id: str,
    request: Request,
    max_characters: int = Query(default=50_000, ge=1_000, le=200_000),
) -> RuntimeRunLog:
    record = get_project_runtime_run(project_id, run_id, request)
    try:
        content, truncated = request.app.state.runtime_execution_service.read_log(
            run_id,
            max_characters,
        )
    except RuntimeExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return RuntimeRunLog(
        run_id=run_id,
        status=record.status,
        content=content,
        truncated=truncated,
    )
