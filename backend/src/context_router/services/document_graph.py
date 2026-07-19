from __future__ import annotations

from collections import deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from context_router.db.models import Document, DocumentLink, Project


class DocumentGraphError(ValueError):
    pass


def shortest_reachable_depths(
    *,
    root_id: str,
    outgoing: dict[str, list[str]],
) -> dict[str, int]:
    depths = {root_id: 1}
    pending = deque([root_id])
    while pending:
        source = pending.popleft()
        for target in outgoing.get(source, []):
            if target in depths:
                continue
            depths[target] = depths[source] + 1
            pending.append(target)
    return depths


def project_entry_document(session: Session, project: Project) -> Document:
    document = session.scalar(
        select(Document).where(
            Document.project_id == project.id,
            Document.source_path == "AGENTS.md",
            Document.doc_type == "agent_index",
            Document.status == "active",
            Document.is_reachable.is_(True),
            Document.graph_depth == 1,
        )
    )
    if document is None:
        raise DocumentGraphError(f"Mapped AGENTS.md is not indexed for project: {project.slug}")
    return document


def is_direct_document_link(
    session: Session,
    *,
    source_document_id: str,
    target_document_id: str,
) -> bool:
    link_id = session.scalar(
        select(DocumentLink.id)
        .where(
            DocumentLink.source_document_id == source_document_id,
            DocumentLink.target_document_id == target_document_id,
        )
        .limit(1)
    )
    return link_id is not None
