from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.schemas.context import PrepareTaskContextResult
from context_router.schemas.data_sources import WorkspaceDataSourceSummary
from context_router.schemas.projects import DocumentDetail, DocumentTreeNode
from context_router.schemas.workspaces import (
    WorkspaceCreate,
    WorkspaceEnabledUpdate,
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
from context_router.services.workspace_management import (
    WorkspaceManagementError,
    WorkspaceManagementService,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _service(request: Request) -> WorkspaceManagementService:
    return request.app.state.workspace_management_service


def _context_service(request: Request) -> ContextPreparationService:
    return request.app.state.context_preparation_service


def _http_error(exc: WorkspaceManagementError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[WorkspaceSummary])
def list_workspaces(request: Request) -> list[WorkspaceSummary]:
    try:
        return _service(request).list_workspaces()
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.post("", response_model=WorkspaceSummary, status_code=status.HTTP_201_CREATED)
def create_workspace(payload: WorkspaceCreate, request: Request) -> WorkspaceSummary:
    try:
        return _service(request).create_workspace(
            name=payload.name,
            workspace_type=payload.workspace_type,
            root_path=payload.root_path,
            enabled=payload.enabled,
        )
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


@router.get("/{workspace_id}", response_model=WorkspaceSummary)
def get_workspace(workspace_id: str, request: Request) -> WorkspaceSummary:
    try:
        return _service(request).get_workspace(workspace_id)
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc


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


@router.patch("/{workspace_id}/enabled", response_model=WorkspaceSummary)
def set_workspace_enabled(
    workspace_id: str,
    payload: WorkspaceEnabledUpdate,
    request: Request,
) -> WorkspaceSummary:
    try:
        return _service(request).set_workspace_enabled(
            workspace_id,
            enabled=payload.enabled,
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
) -> PrepareTaskContextResult:
    try:
        return _context_service(request).prepare_for_workspace(workspace_id)
    except ContextPreparationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
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
) -> WorkspaceDataSourceSummary:
    try:
        return _service(request).data_source_summary(workspace_id)
    except WorkspaceManagementError as exc:
        raise _http_error(exc) from exc
