from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from context_router.db.models import Document, DocumentChunk, Project
from context_router.schemas.documents import DocumentCreate, DocumentUpsertResponse
from context_router.services.chunking import chunk_markdown


def upsert_document(
    session: Session,
    *,
    project: Project,
    document: DocumentCreate,
) -> DocumentUpsertResponse:
    saved = session.scalar(select(Document).where(Document.id == document.id))
    if saved is None:
        saved = Document(id=document.id, project_id=project.id, title=document.title)
        session.add(saved)

    saved.project_id = project.id
    saved.title = document.title
    saved.source_path = document.source_path
    saved.doc_type = document.doc_type
    saved.area = document.area
    saved.tags = document.tags
    saved.status = "active"
    saved.content_markdown = document.content_markdown

    session.flush()
    session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == saved.id))
    session.flush()

    chunks = chunk_markdown(document.content_markdown)
    for chunk in chunks:
        session.add(
            DocumentChunk(
                document_id=saved.id,
                heading_path=chunk.heading_path,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_estimate=chunk.token_estimate,
                embedding=None,
                chunk_metadata=chunk.metadata,
            )
        )

    session.flush()
    return DocumentUpsertResponse(
        id=saved.id,
        chunk_count=len(chunks),
        status=saved.status,
    )
