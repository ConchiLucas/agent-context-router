from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from context_router.db.models import Document, Project, TraceEvent
from context_router.db.session import get_session
from context_router.schemas.documents import (
    DocumentCreate,
    DocumentListResponse,
    DocumentReadResponse,
    DocumentSummary,
    DocumentUpsertResponse,
)
from context_router.services.document_store import upsert_document

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


@read_router.get("", response_model=DocumentListResponse)
def list_documents(
    session: Annotated[Session, Depends(get_session)],
    project: str | None = Query(default=None),
    area: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> DocumentListResponse:
    query = select(Document).join(Document.project).order_by(Document.id)
    if project is not None:
        query = query.where(Project.slug == project)
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
                chunk_count=len(document.chunks),
            )
            for document in documents
        ]
    )


@read_router.get("/{document_id}", response_model=DocumentReadResponse)
def read_document(
    document_id: str,
    session: Annotated[Session, Depends(get_session)],
    trace_id: str | None = Query(default=None),
    reason: str | None = Query(default=None),
) -> DocumentReadResponse:
    document = session.scalar(select(Document).where(Document.id == document_id))
    if document is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    if trace_id is not None:
        if not reason:
            raise HTTPException(
                status_code=400,
                detail="reason is required when trace_id is present",
            )
        session.add(
            TraceEvent(
                trace_id=trace_id,
                event_type="read",
                payload={
                    "document_id": document.id,
                    "reason": reason,
                },
            )
        )
        session.commit()

    return DocumentReadResponse(
        id=document.id,
        title=document.title,
        source_path=document.source_path,
        doc_type=document.doc_type,
        area=document.area,
        tags=document.tags,
        status=document.status,
        content_markdown=document.content_markdown,
    )
