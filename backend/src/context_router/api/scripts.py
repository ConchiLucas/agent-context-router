from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from context_router.db.models import Project
from context_router.db.session import get_session
from context_router.schemas.scripts import (
    WorkspaceScriptDetail,
    WorkspaceScriptListResponse,
    WorkspaceScriptSummary,
)
from context_router.services.workspace_scripts import (
    get_workspace_script,
    import_panzhihua_scripts_once,
    list_workspace_scripts,
)

router = APIRouter(prefix="/api/projects", tags=["scripts"])


@router.get("/{project_slug}/scripts", response_model=WorkspaceScriptListResponse)
def list_project_scripts(
    project_slug: str,
    session: Annotated[Session, Depends(get_session)],
) -> WorkspaceScriptListResponse:
    project = _require_project(session, project_slug)
    import_panzhihua_scripts_once(session)
    session.commit()
    scripts = list_workspace_scripts(session, project=project)
    return WorkspaceScriptListResponse(
        project_slug=project.slug,
        scripts=[_script_summary(project.slug, script) for script in scripts],
    )


@router.get("/{project_slug}/scripts/{script_slug}", response_model=WorkspaceScriptDetail)
def get_project_script(
    project_slug: str,
    script_slug: str,
    session: Annotated[Session, Depends(get_session)],
) -> WorkspaceScriptDetail:
    project = _require_project(session, project_slug)
    script = get_workspace_script(session, project=project, script_slug=script_slug)
    if script is None:
        raise HTTPException(status_code=404, detail=f"Script not found: {script_slug}")
    summary = _script_summary(project.slug, script)
    return WorkspaceScriptDetail(**summary.model_dump(), content=script.content)


def _require_project(session: Session, project_slug: str) -> Project:
    project = session.scalar(select(Project).where(Project.slug == project_slug))
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_slug}")
    return project


def _script_summary(project_slug: str, script) -> WorkspaceScriptSummary:
    return WorkspaceScriptSummary(
        id=script.id,
        project_slug=project_slug,
        slug=script.slug,
        name=script.name,
        description=script.description,
        kind=script.kind,
        relative_path=script.relative_path,
        imported_at=script.imported_at,
        updated_at=script.updated_at,
    )
