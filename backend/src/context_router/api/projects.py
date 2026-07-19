from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from context_router.db.models import Project
from context_router.db.session import get_session
from context_router.schemas.projects import (
    DocumentMappingRequest,
    DocumentMappingResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectSummary,
    SyncSummary,
)
from context_router.services.document_mapping import (
    DocumentMappingConflictError,
    DocumentMappingError,
    assign_document_mapping,
    resolve_document_root,
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


@router.put(
    "/{project_slug}/document-mapping",
    response_model=DocumentMappingResponse,
)
def update_document_mapping(
    project_slug: str,
    request: DocumentMappingRequest,
    session: Annotated[Session, Depends(get_session)],
) -> DocumentMappingResponse:
    project = session.scalar(select(Project).where(Project.slug == project_slug))
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_slug}")

    try:
        assign_document_mapping(
            session,
            project=project,
            docs_path=request.docs_path,
        )
    except DocumentMappingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DocumentMappingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session.commit()
    session.refresh(project)
    return DocumentMappingResponse(
        project_slug=project.slug,
        docs_path=project.docs_path or "",
        last_synced_at=project.last_synced_at,
        last_sync_status=project.last_sync_status,
        last_sync_summary=project.last_sync_summary,
    )


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
    mapping_status = _mapping_status(project)
    return ProjectResponse(
        id=project.id,
        slug=project.slug,
        name=project.name,
        root_path=project.root_path,
        docs_path=project.docs_path,
        description=project.description,
        parent_slug=project.parent.slug if project.parent else None,
        mapping_status=mapping_status,
        last_synced_at=project.last_synced_at,
        last_sync_status=project.last_sync_status,
        sync_summary=SyncSummary.model_validate(project.last_sync_summary or {}),
    )


def _project_summary(project: Project) -> ProjectSummary:
    project_tree = list(_iter_project_tree(project))
    documents = [document for tree_project in project_tree for document in tree_project.documents]
    traces = [
        trace
        for tree_project in project_tree
        for trace in tree_project.traces
        if trace.source == "mcp"
    ]
    return ProjectSummary(
        id=project.id,
        slug=project.slug,
        name=project.name,
        root_path=project.root_path,
        docs_path=project.docs_path,
        description=project.description,
        parent_slug=project.parent.slug if project.parent else None,
        mapping_status=_mapping_status(project),
        last_synced_at=project.last_synced_at,
        last_sync_status=project.last_sync_status,
        sync_summary=SyncSummary.model_validate(project.last_sync_summary or {}),
        document_count=len(documents),
        active_document_count=sum(1 for document in documents if document.status == "active"),
        trace_count=len(traces),
        child_project_count=len(project.children),
    )


def _mapping_status(project: Project) -> str:
    if not project.docs_path:
        return "not_mapped"
    try:
        resolve_document_root(project)
    except DocumentMappingError:
        return "invalid"
    if project.last_sync_status == "failed":
        return "sync_failed"
    if project.last_synced_at is None:
        return "not_synced"
    return "ready"


def _iter_project_tree(project: Project):
    yield project
    for child in project.children:
        yield from _iter_project_tree(child)


def _routing_template(project_slug: str) -> str:
    return f"""# AI_CONTEXT_INDEX.md

本文件是 AI 的上下文树索引入口，只列下一层文档和适用任务。

## 使用方式

- 开始任务时调用 MCP 工具 `prepare_task_context`，传入 task 和 cwd。
- 从返回的候选文档中选择需要的内容。
- 读取候选文档时调用 `read_context_document`，并传回 trace_id。
- 源码、配置、表结构等实时内容可以直接查项目目录。

## 项目标识

- project: `{project_slug}`
- 通常由 cwd 自动识别，不需要 AI 手工指定。

## 下一层文档

- `<doc-id>`：填写下一层文档用途。
  - 适用任务：描述 AI 在什么情况下需要它。

## Rules

- 不要一开始读取全部说明文档。
- 只读取当前任务需要的候选文档。
- 如果文档树缺少合适入口，在最终回复中说明缺口。
"""
