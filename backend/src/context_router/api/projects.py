from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from context_router.db.models import Project
from context_router.db.session import get_session
from context_router.schemas.projects import (
    ProjectCreate,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectSummary,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
def list_projects(session: Annotated[Session, Depends(get_session)]) -> ProjectListResponse:
    projects = session.scalars(
        select(Project).options(selectinload(Project.documents)).order_by(Project.slug)
    ).all()
    return ProjectListResponse(projects=[_project_summary(project) for project in projects])


@router.post("", response_model=ProjectResponse)
def create_project(
    project: ProjectCreate,
    session: Annotated[Session, Depends(get_session)],
) -> ProjectResponse:
    saved = Project(
        slug=project.slug,
        name=project.name,
        root_path=project.root_path,
        description=project.description,
    )
    session.add(saved)
    session.commit()
    session.refresh(saved)
    return ProjectResponse.model_validate(saved)


@router.get("/{project_slug}", response_model=ProjectDetailResponse)
def get_project(
    project_slug: str,
    session: Annotated[Session, Depends(get_session)],
) -> ProjectDetailResponse:
    project = session.scalar(
        select(Project).where(Project.slug == project_slug).options(selectinload(Project.documents))
    )
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_slug}")

    summary = _project_summary(project)
    return ProjectDetailResponse(
        **summary.model_dump(),
        routing_template=_routing_template(project.slug),
    )


def _project_summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        id=project.id,
        slug=project.slug,
        name=project.name,
        root_path=project.root_path,
        description=project.description,
        document_count=len(project.documents),
        active_document_count=sum(
            1 for document in project.documents if document.status == "active"
        ),
    )


def _routing_template(project_slug: str) -> str:
    return f"""# AI Context Index

This file is for AI coding agents. Keep it short. Do not paste full project knowledge here.

## First step for any task

Run:

```bash
ctx prepare --project {project_slug} --task "<copy the user's task>"
```

Use the returned `trace_id` for follow-up reads.

## Read a specific document only when needed

Run:

```bash
ctx read <doc-id> --trace <trace-id> --reason "<why this document is needed>"
```

## Rules

- Do not read large docs manually before running `ctx prepare`.
- Prefer the documents returned by `ctx prepare`.
- If needed context is missing, mention the missing document in the final response.
"""
