from datetime import UTC, datetime
from time import perf_counter
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
    DocumentSyncResponse,
    DocumentUpsertResponse,
)
from context_router.services.document_graph import (
    DocumentGraphError,
    ReadDecision,
    authorize_mcp_read,
)
from context_router.services.document_mapping import DocumentMappingError
from context_router.services.document_store import upsert_document
from context_router.services.local_document_reader import (
    LocalDocumentAccessError,
    LocalDocumentNotFoundError,
    read_document_content,
)
from context_router.services.markdown_sync import MarkdownSyncError, sync_mapped_documents
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
    session: Annotated[Session, Depends(get_session)],
) -> DocumentSyncResponse:
    project = session.scalar(select(Project).where(Project.slug == project_slug))
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_slug}")

    try:
        result = sync_mapped_documents(session, project=project)
    except (DocumentMappingError, MarkdownSyncError) as exc:
        session.rollback()
        failed_project = session.scalar(select(Project).where(Project.slug == project_slug))
        if failed_project is not None:
            failed_project.last_sync_status = "failed"
            session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    project.last_synced_at = datetime.now(UTC)
    project.last_sync_status = "success"
    project.last_sync_summary = result.summary
    session.commit()
    return DocumentSyncResponse(
        project_slug=project.slug,
        docs_path=result.docs_path,
        indexed_count=len(result.indexed_document_ids),
        reachable_count=result.reachable_count,
        orphan_count=result.orphan_count,
        broken_link_count=result.broken_link_count,
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
    source: str | None = Query(default=None),
    untracked: bool = Query(default=False),
) -> DocumentReadResponse:
    if source == "mcp" and trace_id is None:
        raise HTTPException(status_code=422, detail="trace_id is required for MCP document reads")

    started_at = perf_counter()
    document = session.scalar(select(Document).where(Document.id == document_id))
    if document is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    trace: Trace | None = None
    read_decision: ReadDecision | None = None
    if source == "mcp":
        trace = session.scalar(select(Trace).where(Trace.id == trace_id))
        if trace is None:
            raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
        try:
            read_decision = authorize_mcp_read(
                session,
                trace=trace,
                document=document,
                parent_document_id=parent_document_id,
            )
        except DocumentGraphError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        content_markdown = read_document_content(document)
    except LocalDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LocalDocumentAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved_trace_id: str | None = None
    if not untracked:
        if trace is None:
            trace = _resolve_or_create_trace(
                session,
                document=document,
                trace_id=trace_id,
                source=source,
            )
        resolved_trace_id = trace.id
        if read_decision is not None:
            depth = read_decision.depth
            read_mode = read_decision.read_mode
        else:
            depth = _derive_read_depth(
                session,
                trace=trace,
                parent_document_id=parent_document_id,
            )
            read_mode = _read_mode(
                session=session,
                trace=trace,
                requested_trace_id=trace_id,
                parent_document_id=parent_document_id,
            )
        duration_ms = round((perf_counter() - started_at) * 1000, 3)
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
                    "read_mode": read_mode,
                    "duration_ms": duration_ms,
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
        links=_document_links(document, for_mcp=source == "mcp"),
    )


def _document_links(
    document: Document,
    *,
    for_mcp: bool = False,
) -> list[DocumentLinkSummary]:
    return [
        DocumentLinkSummary(
            target_document_id=link.target_document_id,
            target_path=link.target_path,
            label=link.label,
            relation_type=link.relation_type,
            sort_order=link.sort_order,
        )
        for link in sorted(document.outgoing_links, key=lambda item: item.sort_order)
        if not for_mcp
        or (
            link.target_document is not None
            and link.target_document.project_id == document.project_id
            and link.target_document.status == "active"
            and link.target_document.is_reachable
        )
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
        if source == "mcp":
            raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

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


def _derive_read_depth(
    session: Session,
    *,
    trace: Trace,
    parent_document_id: str | None,
) -> int:
    if parent_document_id is None:
        return 1

    read_events = session.scalars(
        select(TraceEvent)
        .where(
            TraceEvent.trace_id == trace.id,
            TraceEvent.event_type == "read",
        )
        .order_by(TraceEvent.created_at.desc())
    ).all()
    for event in read_events:
        if event.payload.get("document_id") != parent_document_id:
            continue
        try:
            return int(event.payload.get("depth") or 1) + 1
        except (TypeError, ValueError):
            return 2

    raise HTTPException(
        status_code=422,
        detail=f"Parent document was not read in this trace: {parent_document_id}",
    )
