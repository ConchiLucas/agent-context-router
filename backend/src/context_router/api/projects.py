from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.schemas.projects import (
    ProjectCreate,
    ProjectSummary,
    ProjectUpdate,
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
            project_type=payload.project_type,
            project_kind=payload.project_kind,
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
            project_kind=payload.project_kind,
            agents_path=payload.agents_path,
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
