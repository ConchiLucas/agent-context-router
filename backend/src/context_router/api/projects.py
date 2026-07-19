from fastapi import APIRouter, HTTPException, Request, status

from context_router.schemas.projects import (
    DocumentDetail,
    DocumentTreeNode,
    ProjectCreate,
    ProjectSummary,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

router = APIRouter(prefix="/projects", tags=["projects"])


def _registry(request: Request) -> ProjectRegistry:
    return request.app.state.project_registry


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
            agents_path=payload.agents_path,
        )
    except ProjectRegistryError as exc:
        raise _http_error(exc) from exc


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
