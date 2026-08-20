
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from context_router.schemas.context import PrepareTaskContextResult
from context_router.schemas.data_sources import WorkspaceDataSourceSummary
from context_router.schemas.projects import DocumentDetail, DocumentTreeNode
from context_router.schemas.workspace_shared_files import WorkspaceSharedFilesResult
from context_router.schemas.workspaces import (
    WorkspaceContainerBulkAction,
    WorkspaceContainerBulkActionResult,
    WorkspaceContainerSummary,
    WorkspaceCreate,
    WorkspaceProjectCreate,
    WorkspaceProjectSummary,
    WorkspaceProjectUpdate,
    WorkspaceSummary,
    WorkspaceUpdate,
)
from context_router.services.context_preparation import (
    ContextPreparationError,
    ContextPreparationService,
)
from context_router.services.workspace_containers import WorkspaceContainerError
from context_router.services.workspace_management import (
    WorkspaceManagementError,
    WorkspaceManagementService,
)
from context_router.services.workspace_shared_files import (
    WorkspaceSharedFilesError,
    WorkspaceSharedFilesService,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _service(request: Request) -> WorkspaceManagementService:
    return request.app.state.workspace_management_service


def _context_service(request: Request) -> ContextPreparationService:
    return request.app.state.context_preparation_service


def _shared_files_service(request: Request) -> WorkspaceSharedFilesService:
    return request.app.state.workspace_shared_files_service


def _http_error(exc: WorkspaceManagementError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[WorkspaceSummary])
def list_workspaces(request: Request) -> list[WorkspaceSummary]:
    try:
        return _service(request).list_workspaces()
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.post("/reload-local-mapping", response_model=list[WorkspaceSummary])
def reload_local_mapping(request: Request) -> list[WorkspaceSummary]:
    try:
        return _service(request).reload_local_mapping()
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.post("", response_model=WorkspaceSummary, status_code=status.HTTP_201_CREATED)
def create_workspace(payload: WorkspaceCreate, request: Request) -> WorkspaceSummary:
    try:
        return _service(request).create_workspace(
            name=payload.name,
            workspace_type=payload.workspace_type,
            root_path=payload.root_path,
        )
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.get("/{workspace_id}", response_model=WorkspaceSummary)
def get_workspace(workspace_id: str, request: Request) -> WorkspaceSummary:
    try:
        return _service(request).get_workspace(workspace_id)
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{workspace_id}/containers",
    response_model=list[WorkspaceContainerSummary],
)
def list_workspace_containers(
    workspace_id: str,
    request: Request,
) -> list[WorkspaceContainerSummary]:
    try:
        service = _service(request)
        service.get_workspace(workspace_id)
        projects = service.list_projects(workspace_id)
        return request.app.state.workspace_container_service.list_containers(
            workspace_id,
            project_names={project.id: project.name for project in projects},
            project_kinds={project.id: project.project_kind for project in projects},
        )
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc
    except WorkspaceContainerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post(
    "/{workspace_id}/containers/bulk-action",
    response_model=WorkspaceContainerBulkActionResult,
)
def run_workspace_container_bulk_action(
    workspace_id: str,
    payload: WorkspaceContainerBulkAction,
    request: Request,
) -> WorkspaceContainerBulkActionResult:
    try:
        service = _service(request)
        service.get_workspace(workspace_id)
        projects = service.list_projects(workspace_id)
        target_count, failures = request.app.state.workspace_container_service.bulk_action(
            workspace_id,
            {project.id for project in projects if project.project_kind == payload.project_kind},
            action=payload.action,
        )
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc
    except WorkspaceContainerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    failed_count = len(failures)
    return WorkspaceContainerBulkActionResult(
        workspace_id=workspace_id,
        action=payload.action,
        project_kind=payload.project_kind,
        target_count=target_count,
        succeeded_count=target_count - failed_count,
        failed_count=failed_count,
        failed_containers=failures,
    )


@router.get("/{workspace_id}/containers/{container_id}/logs/stream")
def stream_workspace_container_logs(
    workspace_id: str,
    container_id: str,
    request: Request,
    tail: int = Query(default=200, ge=1, le=1000),
) -> StreamingResponse:
    try:
        _service(request).get_workspace(workspace_id)
        events = request.app.state.workspace_container_service.stream_logs(
            workspace_id,
            container_id,
            tail=tail,
            since=request.headers.get("last-event-id"),
        )
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc
    except WorkspaceContainerError as exc:
        not_found = str(exc) in {"容器不存在", "容器不属于当前工作空间"}
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND if not_found else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(exc),
        ) from exc
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.put("/{workspace_id}", response_model=WorkspaceSummary)
def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdate,
    request: Request,
) -> WorkspaceSummary:
    try:
        return _service(request).update_workspace(
            workspace_id,
            name=payload.name,
            workspace_type=payload.workspace_type,
            root_path=payload.root_path,
        )
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: str, request: Request) -> Response:
    try:
        _service(request).delete_workspace(workspace_id)
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{workspace_id}/projects",
    response_model=list[WorkspaceProjectSummary],
)
def list_workspace_projects(
    workspace_id: str,
    request: Request,
) -> list[WorkspaceProjectSummary]:
    try:
        return _service(request).list_projects(workspace_id)
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{workspace_id}/projects",
    response_model=WorkspaceProjectSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_project(
    workspace_id: str,
    payload: WorkspaceProjectCreate,
    request: Request,
) -> WorkspaceProjectSummary:
    try:
        return _service(request).create_project(
            workspace_id,
            name=payload.name,
            relative_path=payload.relative_path,
            document_relative_path=payload.document_relative_path,
            project_kind=payload.project_kind,
        )
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.put(
    "/{workspace_id}/projects/{project_id}",
    response_model=WorkspaceProjectSummary,
)
def update_workspace_project(
    workspace_id: str,
    project_id: str,
    payload: WorkspaceProjectUpdate,
    request: Request,
) -> WorkspaceProjectSummary:
    try:
        return _service(request).update_project(
            workspace_id,
            project_id,
            name=payload.name,
            relative_path=payload.relative_path,
            document_relative_path=payload.document_relative_path,
            project_kind=payload.project_kind,
        )
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{workspace_id}/refresh",
    response_model=WorkspaceSummary,
)
def refresh_workspace(
    workspace_id: str,
    request: Request,
) -> WorkspaceSummary:
    try:
        return _service(request).refresh_workspace(workspace_id)
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{workspace_id}/shared-files/restore",
    response_model=WorkspaceSharedFilesResult,
)
def restore_workspace_shared_files(
    workspace_id: str,
    request: Request,
) -> WorkspaceSharedFilesResult:
    try:
        return _shared_files_service(request).restore(workspace_id)
    except WorkspaceSharedFilesError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{workspace_id}/shared-files/publish",
    response_model=WorkspaceSharedFilesResult,
)
def publish_workspace_shared_files(
    workspace_id: str,
    request: Request,
) -> WorkspaceSharedFilesResult:
    try:
        return _shared_files_service(request).publish(workspace_id)
    except WorkspaceSharedFilesError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/{workspace_id}/tree",
    response_model=DocumentTreeNode,
)
def get_workspace_tree(
    workspace_id: str,
    request: Request,
) -> DocumentTreeNode:
    try:
        return _service(request).workspace_tree(workspace_id)
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{workspace_id}/prepare-preview",
    response_model=PrepareTaskContextResult,
    response_model_exclude_none=True,
)
def prepare_workspace_preview(
    workspace_id: str,
    request: Request,
    environment: str | None = None,
) -> PrepareTaskContextResult:
    try:
        return _context_service(request).prepare_for_workspace(
            workspace_id,
            environment=environment,
        )
    except ContextPreparationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{exc.code}: {exc}",
        ) from exc


@router.get(
    "/{workspace_id}/documents/{document_id}",
    response_model=DocumentDetail,
)
def get_workspace_document(
    workspace_id: str,
    document_id: str,
    request: Request,
) -> DocumentDetail:
    try:
        return _service(request).workspace_document(workspace_id, document_id)
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{workspace_id}/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workspace_project(
    workspace_id: str,
    project_id: str,
    request: Request,
) -> Response:
    try:
        _service(request).delete_project(workspace_id, project_id)
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{workspace_id}/data-source-summary",
    response_model=WorkspaceDataSourceSummary,
)
def get_workspace_data_source_summary(
    workspace_id: str,
    request: Request,
    environment: str | None = None,
) -> WorkspaceDataSourceSummary:
    try:
        return _service(request).data_source_summary(
            workspace_id,
            environment=environment,
        )
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc
