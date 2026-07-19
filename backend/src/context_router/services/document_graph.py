from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from context_router.db.models import (
    Document,
    DocumentLink,
    Project,
    RetrievalHit,
    Trace,
    TraceEvent,
)


class DocumentGraphError(ValueError):
    pass


@dataclass(frozen=True)
class ReadDecision:
    depth: int
    read_mode: str


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


def authorize_mcp_read(
    session: Session,
    *,
    trace: Trace,
    document: Document,
    parent_document_id: str | None,
) -> ReadDecision:
    if document.project_id != trace.project_id:
        raise DocumentGraphError("Document does not belong to this task project")
    if document.status != "active" or not document.is_reachable:
        raise DocumentGraphError("Document is not reachable from mapped AGENTS.md")

    read_events = session.scalars(
        select(TraceEvent)
        .where(
            TraceEvent.trace_id == trace.id,
            TraceEvent.event_type == "read",
        )
        .order_by(TraceEvent.created_at)
    ).all()
    if not read_events:
        if parent_document_id is not None:
            raise DocumentGraphError("The first document read cannot have a parent")
        entry_hit = session.scalar(
            select(RetrievalHit.id).where(
                RetrievalHit.trace_id == trace.id,
                RetrievalHit.document_id == document.id,
            )
        )
        if entry_hit is None or document.source_path != "AGENTS.md":
            raise DocumentGraphError("The first document read must be mapped AGENTS.md")
        return ReadDecision(depth=1, read_mode="entry_read")

    if parent_document_id is None:
        raise DocumentGraphError("A parent document is required after the entry read")
    parent_event = next(
        (
            event
            for event in reversed(read_events)
            if event.payload.get("document_id") == parent_document_id
        ),
        None,
    )
    if parent_event is None:
        raise DocumentGraphError("Parent document was not read in this task")
    if not is_direct_document_link(
        session,
        source_document_id=parent_document_id,
        target_document_id=document.id,
    ):
        raise DocumentGraphError("Requested document is not a direct link from its parent")
    try:
        parent_depth = int(parent_event.payload.get("depth") or 1)
    except (TypeError, ValueError):
        parent_depth = 1
    return ReadDecision(depth=parent_depth + 1, read_mode="tree_read")
