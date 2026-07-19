from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from context_router.db.models import Document, Project
from context_router.schemas.context import ContextDocument
from context_router.services.local_document_reader import (
    LocalDocumentReadError,
    read_document_content,
)

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
CJK_RE = re.compile(r"^[\u4e00-\u9fff]+$")
CONTENT_TERM_CAP = 3

ALWAYS_AVAILABLE_DOC_TYPES = {
    "agent_index",
    "routing_index",
    "usage_guide",
    "usage_step",
    "routing_guide",
    "project_entry_guide",
}


def retrieve_documents(
    session: Session,
    *,
    project: Project,
    task: str,
    area: str | None = None,
    max_documents: int,
) -> list[ContextDocument]:
    query = select(Document).where(
        Document.project_id.in_(_project_scope_ids(session, project)),
        Document.status == "active",
    )
    if area:
        query = query.where(
            or_(
                Document.area == area,
                Document.area.is_(None),
                Document.doc_type.in_(ALWAYS_AVAILABLE_DOC_TYPES),
            )
        )

    documents = session.scalars(query).all()
    task_tokens = _tokens(task)

    scored = [
        _score_document(
            document,
            task_tokens,
            root_project=project,
            requested_area=area,
        )
        for document in documents
    ]
    scored.sort(key=lambda result: (-result.score, result.document_id))

    ranked: list[ContextDocument] = []
    for index, result in enumerate(scored[:max_documents], start=1):
        ranked.append(result.model_copy(update={"rank": index}))

    return ranked


def _project_scope_ids(session: Session, project: Project) -> list[str]:
    project_ids = [project.id]
    pending_ids = [project.id]
    while pending_ids:
        children = session.scalars(
            select(Project).where(Project.parent_project_id.in_(pending_ids))
        ).all()
        child_ids = [child.id for child in children]
        project_ids.extend(child_ids)
        pending_ids = child_ids
    return project_ids


def _score_document(
    document: Document,
    task_tokens: Counter[str],
    *,
    root_project: Project,
    requested_area: str | None,
) -> ContextDocument:
    content_markdown = _document_content(document)
    searchable_terms = _document_terms(document, content_markdown=content_markdown)
    matched_terms = sorted(token for token in task_tokens if token in searchable_terms)
    metadata_score = _metadata_score(
        document,
        task_tokens,
        root_project=root_project,
        requested_area=requested_area,
    )

    best_excerpt = content_markdown.strip().replace("\n", " ")[:180]
    content_terms = Counter(_tokens(content_markdown))
    content_score = sum(
        task_tokens[token] * min(content_terms[token], CONTENT_TERM_CAP) for token in task_tokens
    )

    score = metadata_score + float(content_score)
    reason = _reason(matched_terms=matched_terms, document=document, score=score)
    return ContextDocument(
        document_id=document.id,
        title=document.title,
        reason=reason,
        score=round(score, 4),
        excerpt=best_excerpt,
        rank=0,
    )


def _metadata_score(
    document: Document,
    task_tokens: Counter[str],
    *,
    root_project: Project,
    requested_area: str | None,
) -> float:
    score = 0.0
    if requested_area and document.area == requested_area:
        score += 10.0
        if document.doc_type == "area_route":
            score += 10.0

    if document.project_id == root_project.id:
        score += 4.0

    if document.area:
        score += 3.0 * task_tokens.get(document.area.lower(), 0)

    for tag in document.tags:
        score += 2.0 * task_tokens.get(tag.lower(), 0)

    title_terms = Counter(_tokens(document.title))
    id_terms = Counter(_tokens(document.id.replace("-", " ").replace("_", " ")))
    source_terms = Counter(_tokens(document.source_path.replace("-", " ").replace("_", " ")))
    project_terms = Counter(_tokens(document.project.slug.replace("-", " ").replace("_", " ")))
    type_terms = Counter(_tokens(document.doc_type.replace("_", " ")))
    score += sum(task_tokens[token] * title_terms[token] * 1.5 for token in task_tokens)
    score += sum(task_tokens[token] * id_terms[token] * 3.0 for token in task_tokens)
    score += sum(task_tokens[token] * source_terms[token] * 1.0 for token in task_tokens)
    score += sum(task_tokens[token] * project_terms[token] * 2.0 for token in task_tokens)
    score += sum(task_tokens[token] * type_terms[token] for token in task_tokens)
    return score


def _document_terms(document: Document, *, content_markdown: str) -> set[str]:
    terms = set(_tokens(document.title))
    terms.update(_tokens(document.id.replace("-", " ").replace("_", " ")))
    terms.update(_tokens(document.source_path.replace("-", " ").replace("_", " ")))
    terms.update(_tokens(document.project.slug.replace("-", " ").replace("_", " ")))
    terms.update(_tokens(document.doc_type.replace("_", " ")))
    if document.area:
        terms.add(document.area.lower())
    terms.update(tag.lower() for tag in document.tags)
    terms.update(_tokens(content_markdown))
    return terms


def _document_content(document: Document) -> str:
    try:
        return read_document_content(document)
    except LocalDocumentReadError:
        return document.content_markdown


def _tokens(value: str) -> Counter[str]:
    tokens: list[str] = []
    for raw_token in TOKEN_RE.findall(value):
        token = raw_token.lower()
        tokens.append(token)
        if CJK_RE.fullmatch(token) and len(token) > 2:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return Counter(tokens)


def _reason(*, matched_terms: list[str], document: Document, score: float) -> str:
    if matched_terms:
        return (
            f"Matched task terms {', '.join(matched_terms)} against "
            f"{document.area or 'document metadata'} and content."
        )
    if score > 0:
        return "Matched indirectly through document metadata and content."
    return "Returned as lower-priority fallback because few stronger documents were available."
