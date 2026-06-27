from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
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
def list_projects(
    session: Annotated[Session, Depends(get_session)],
    include_children: Annotated[
        bool,
        Query(description="Include child projects in the list response."),
    ] = False,
) -> ProjectListResponse:
    query = select(Project).options(*_project_load_options()).order_by(Project.slug)
    if not include_children:
        query = query.where(Project.parent_project_id.is_(None))

    projects = session.scalars(query).all()
    return ProjectListResponse(projects=[_project_summary(project) for project in projects])


@router.post("", response_model=ProjectResponse)
def create_project(
    project: ProjectCreate,
    session: Annotated[Session, Depends(get_session)],
) -> ProjectResponse:
    parent_id: str | None = None
    if project.parent_slug:
        parent = session.scalar(select(Project).where(Project.slug == project.parent_slug))
        if parent is None:
            raise HTTPException(
                status_code=404,
                detail=f"Parent project not found: {project.parent_slug}",
            )
        parent_id = parent.id

    saved = Project(
        slug=project.slug,
        name=project.name,
        root_path=project.root_path,
        description=project.description,
        parent_project_id=parent_id,
    )
    session.add(saved)
    session.commit()
    session.refresh(saved)
    return _project_response(saved)


@router.get("/{project_slug}", response_model=ProjectDetailResponse)
def get_project(
    project_slug: str,
    session: Annotated[Session, Depends(get_session)],
) -> ProjectDetailResponse:
    project = session.scalar(
        select(Project).where(Project.slug == project_slug).options(*_project_load_options())
    )
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_slug}")

    summary = _project_summary(project)
    return ProjectDetailResponse(
        **summary.model_dump(),
        children=[
            _project_summary(child)
            for child in sorted(project.children, key=lambda child: child.slug)
        ],
        routing_template=_routing_template(project.slug),
    )


def _project_load_options():
    return (
        selectinload(Project.parent),
        selectinload(Project.documents),
        selectinload(Project.traces),
        selectinload(Project.children).selectinload(Project.documents),
        selectinload(Project.children).selectinload(Project.traces),
        selectinload(Project.children).selectinload(Project.children),
    )


def _project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        slug=project.slug,
        name=project.name,
        root_path=project.root_path,
        description=project.description,
        parent_slug=project.parent.slug if project.parent else None,
    )


def _project_summary(project: Project) -> ProjectSummary:
    project_tree = list(_iter_project_tree(project))
    documents = [document for tree_project in project_tree for document in tree_project.documents]
    traces = [trace for tree_project in project_tree for trace in tree_project.traces]
    return ProjectSummary(
        id=project.id,
        slug=project.slug,
        name=project.name,
        root_path=project.root_path,
        description=project.description,
        parent_slug=project.parent.slug if project.parent else None,
        document_count=len(documents),
        active_document_count=sum(1 for document in documents if document.status == "active"),
        trace_count=len(traces),
        child_project_count=len(project.children),
    )


def _iter_project_tree(project: Project):
    yield project
    for child in project.children:
        yield from _iter_project_tree(child)


def _routing_template(project_slug: str) -> str:
    return f"""# AI Context Index

This file is for AI coding agents. Keep it short. Do not paste full project knowledge here.

## First step for any task

You can generate this file with:

```bash
ctx project init-index --project {project_slug} --area <area>
```

Run:

```bash
ctx prepare --project {project_slug} --task "<copy the user's task>"
```

If this task clearly belongs to one area, route it directly:

```bash
ctx prepare --project {project_slug} --area <area> \\
  --entrypoint-path AI_CONTEXT_INDEX.md \\
  --entrypoint-rule "<matched rule>" \\
  --task "<copy the user's task>"
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
