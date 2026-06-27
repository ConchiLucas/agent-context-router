from sqlalchemy import select
from sqlalchemy.orm import Session

from context_router.db.models import Document, Project
from context_router.schemas.documents import DocumentCreate, DocumentUpsertResponse


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
    return DocumentUpsertResponse(
        id=saved.id,
        status=saved.status,
    )
