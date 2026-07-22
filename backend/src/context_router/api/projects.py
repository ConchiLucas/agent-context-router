from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.schemas.context import PrepareTaskContextResult
from context_router.schemas.projects import (
    DocumentDetail,
    DocumentTreeNode,
    ProjectCreate,
    ProjectEnabledUpdate,
    ProjectSummary,
    ProjectUpdate,
)
from context_router.services.context_preparation import (
    ContextPreparationError,
    ContextPreparationService,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

router = APIRouter(prefix="/projects", tags=["projects"])


def _registry(request: Request) -> ProjectRegistry:
    return request.app.state.project_registry


def _context_service(request: Request) -> ContextPreparationService:
    return request.app.state.context_preparation_service


def _http_error(exc: ProjectRegistryError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[ProjectSummary])
def list_projects(request: Request) -> list[ProjectSummary]:
    return _registry(request).list_projects()


@router.post("", response_model=ProjectSummary, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request) -> ProjectSummary:
    try:
        return _registry(request).add_project(
            name=payload.name,
            project_type=payload.project_type,
            agents_path=payload.agents_path,
        )
    except ProjectRegistryError as exc:
        raise _http_error(exc) from exc


@router.put("/{project_id}", response_model=ProjectSummary)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    request: Request,
) -> ProjectSummary:
    try:
        return _registry(request).update_project(
            project_id,
            name=payload.name,
            project_type=payload.project_type,
            agents_path=payload.agents_path,
        )
    except ProjectRegistryError as exc:
        raise _http_error(exc) from exc


@router.patch("/{project_id}/enabled", response_model=ProjectSummary)
def set_project_enabled(
    project_id: str,
    payload: ProjectEnabledUpdate,
    request: Request,
) -> ProjectSummary:
    try:
        return _registry(request).set_project_enabled(
            project_id,
            enabled=payload.enabled,
        )
    except ProjectRegistryError as exc:
        raise _http_error(exc) from exc


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, request: Request) -> Response:
    try:
        _registry(request).delete_project(project_id)
    except ProjectRegistryError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{project_id}/refresh", response_model=ProjectSummary)
def refresh_project(project_id: str, request: Request) -> ProjectSummary:
    try:
        return _registry(request).refresh_project(project_id)
    except ProjectRegistryError as exc:
        raise _http_error(exc) from exc


@router.get("/{project_id}/tree", response_model=DocumentTreeNode)
def get_project_tree(project_id: str, request: Request) -> DocumentTreeNode:
    try:
        return _registry(request).get_tree(project_id)
    except ProjectRegistryError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{project_id}/prepare-preview",
    response_model=PrepareTaskContextResult,
    response_model_exclude_none=True,
)
def prepare_project_preview(
    project_id: str,
    request: Request,
) -> PrepareTaskContextResult:
    try:
        return _context_service(request).prepare_for_project(project_id)
    except ContextPreparationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/{project_id}/documents/{document_id}",
    response_model=DocumentDetail,
)
def get_document_detail(
    project_id: str,
    document_id: str,
    request: Request,
) -> DocumentDetail:
    try:
        return _registry(request).get_document(project_id, document_id)
    except ProjectRegistryError as exc:
        raise _http_error(exc) from exc
