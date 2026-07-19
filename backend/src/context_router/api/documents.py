from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from context_router.db.models import Document, Project, Trace, TraceEvent
from context_router.db.session import get_session
from context_router.schemas.documents import (
    DocumentCreate,
    DocumentLinkSummary,
    DocumentListResponse,
    DocumentReadResponse,
    DocumentSummary,
    DocumentSyncRequest,
    DocumentSyncResponse,
    DocumentUpsertResponse,
)
from context_router.services.document_store import upsert_document
from context_router.services.local_document_reader import (
    LocalDocumentAccessError,
    LocalDocumentNotFoundError,
    read_document_content,
)
from context_router.services.markdown_sync import sync_markdown_documents
from context_router.services.tracing import new_trace_id

router = APIRouter(prefix="/api/projects/{project_slug}/documents", tags=["documents"])
read_router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=DocumentUpsertResponse)
def create_or_update_document(
    project_slug: str,
    document: DocumentCreate,
    session: Annotated[Session, Depends(get_session)],
) -> DocumentUpsertResponse:
    project = session.scalar(select(Project).where(Project.slug == project_slug))
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_slug}")

    result = upsert_document(session, project=project, document=document)
    session.commit()
    return result


@router.post("/sync-local", response_model=DocumentSyncResponse)
def sync_local_documents(
    project_slug: str,
    request: DocumentSyncRequest,
    session: Annotated[Session, Depends(get_session)],
) -> DocumentSyncResponse:
    project = session.scalar(select(Project).where(Project.slug == project_slug))
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_slug}")

    try:
        result = sync_markdown_documents(
            session,
            project=project,
            docs_dir=request.docs_dir,
            prune=request.prune,
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session.commit()
    return DocumentSyncResponse(
        project_slug=project.slug,
        docs_dir=str(result.docs_dir),
        indexed_count=len(result.indexed_document_ids),
        link_count=result.link_count,
        pruned_count=len(result.pruned_document_ids),
        indexed_document_ids=result.indexed_document_ids,
        pruned_document_ids=result.pruned_document_ids,
    )


@read_router.get("", response_model=DocumentListResponse)
def list_documents(
    session: Annotated[Session, Depends(get_session)],
    project: str | None = Query(default=None),
    area: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> DocumentListResponse:
    query = (
        select(Document)
        .join(Document.project)
        .options(selectinload(Document.outgoing_links))
        .order_by(Document.id)
    )
    if project is not None:
        query = query.where(Project.slug.in_(_project_slug_scope(session, project)))
    if area is not None:
        query = query.where(Document.area == area)
    if doc_type is not None:
        query = query.where(Document.doc_type == doc_type)
    if status is not None:
        query = query.where(Document.status == status)

    documents = session.scalars(query).all()
    if tag is not None:
        documents = [document for document in documents if tag in document.tags]

    return DocumentListResponse(
        documents=[
            DocumentSummary(
                id=document.id,
                project_slug=document.project.slug,
                title=document.title,
                source_path=document.source_path,
                doc_type=document.doc_type,
                area=document.area,
                tags=document.tags,
                status=document.status,
                links=_document_links(document),
            )
            for document in documents
        ]
    )


def _project_slug_scope(session: Session, project_slug: str) -> list[str]:
    project = session.scalar(select(Project).where(Project.slug == project_slug))
    if project is None:
        return [project_slug]

    slugs = [project.slug]
    pending_ids = [project.id]
    while pending_ids:
        children = session.scalars(
            select(Project).where(Project.parent_project_id.in_(pending_ids))
        ).all()
        slugs.extend(child.slug for child in children)
        pending_ids = [child.id for child in children]
    return slugs


@read_router.get("/{document_id}", response_model=DocumentReadResponse)
def read_document(
    document_id: str,
    session: Annotated[Session, Depends(get_session)],
    trace_id: str | None = Query(default=None),
    parent_document_id: str | None = Query(default=None),
    depth: int | None = Query(default=None, ge=1),
    reason: str | None = Query(default=None),
    source: str | None = Query(default=None),
    untracked: bool = Query(default=False),
) -> DocumentReadResponse:
    document = session.scalar(select(Document).where(Document.id == document_id))
    if document is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    try:
        content_markdown = read_document_content(document)
    except LocalDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LocalDocumentAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved_trace_id: str | None = None
    if not untracked:
        trace = _resolve_or_create_trace(
            session,
            document=document,
            trace_id=trace_id,
            source=source,
        )
        resolved_trace_id = trace.id
        session.add(
            TraceEvent(
                trace_id=trace.id,
                event_type="read",
                payload={
                    "document_id": document.id,
                    "document_title": document.title,
                    "doc_type": document.doc_type,
                    "project_slug": document.project.slug,
                    "parent_document_id": parent_document_id,
                    "depth": depth,
                    "source": source,
                    "read_mode": _read_mode(
                        session=session,
                        trace=trace,
                        requested_trace_id=trace_id,
                        parent_document_id=parent_document_id,
                    ),
                },
            )
        )
        session.commit()

    return DocumentReadResponse(
        id=document.id,
        trace_id=resolved_trace_id,
        title=document.title,
        source_path=document.source_path,
        doc_type=document.doc_type,
        area=document.area,
        tags=document.tags,
        status=document.status,
        content_markdown=content_markdown,
        links=_document_links(document),
    )


def _document_links(document: Document) -> list[DocumentLinkSummary]:
    return [
        DocumentLinkSummary(
            target_document_id=link.target_document_id,
            target_path=link.target_path,
            label=link.label,
            relation_type=link.relation_type,
            sort_order=link.sort_order,
        )
        for link in sorted(document.outgoing_links, key=lambda item: item.sort_order)
    ]


def _read_mode(
    *,
    session: Session,
    trace: Trace,
    requested_trace_id: str | None,
    parent_document_id: str | None,
) -> str:
    if parent_document_id:
        return "tree_read"
    if requested_trace_id == trace.id:
        prepare_event_id = session.scalar(
            select(TraceEvent.id)
            .where(
                TraceEvent.trace_id == trace.id,
                TraceEvent.event_type == "prepare",
            )
            .limit(1)
        )
        if prepare_event_id is not None:
            return "prepare_fallback"
        return "current_trace"
    return "direct_read"


def _resolve_or_create_trace(
    session: Session,
    *,
    document: Document,
    trace_id: str | None,
    source: str | None,
) -> Trace:
    if trace_id:
        trace = session.scalar(select(Trace).where(Trace.id == trace_id))
        if trace is not None:
            return trace

    trace = Trace(
        id=new_trace_id(),
        project_id=document.project_id,
        task=f"读取文档：{document.title}",
        area=document.area,
        entrypoint_path=document.source_path,
        entrypoint_rule="direct-read",
        route_hint=document.doc_type,
        source=source,
    )
    session.add(trace)
    session.flush()
    return trace
