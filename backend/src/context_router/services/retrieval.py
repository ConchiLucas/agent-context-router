from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from context_router.db.models import Document, Project
from context_router.schemas.context import ContextDocument

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)


def retrieve_documents(
    session: Session,
    *,
    project: Project,
    task: str,
    max_documents: int,
) -> list[ContextDocument]:
    documents = session.scalars(
        select(Document).where(Document.project_id == project.id, Document.status == "active")
    ).all()
    task_tokens = _tokens(task)

    scored = [_score_document(document, task_tokens) for document in documents]
    scored.sort(key=lambda result: (-result.score, result.document_id))

    ranked: list[ContextDocument] = []
    for index, result in enumerate(scored[:max_documents], start=1):
        ranked.append(result.model_copy(update={"rank": index}))

    return ranked


def _score_document(
    document: Document,
    task_tokens: Counter[str],
) -> ContextDocument:
    searchable_terms = _document_terms(document)
    matched_terms = sorted(token for token in task_tokens if token in searchable_terms)
    metadata_score = _metadata_score(document, task_tokens)

    best_excerpt = document.content_markdown.strip().replace("\n", " ")[:180]
    content_terms = Counter(_tokens(document.content_markdown))
    content_score = sum(task_tokens[token] * content_terms[token] for token in task_tokens)

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


def _metadata_score(document: Document, task_tokens: Counter[str]) -> float:
    score = 0.0
    if document.area:
        score += 3.0 * task_tokens.get(document.area.lower(), 0)

    for tag in document.tags:
        score += 2.0 * task_tokens.get(tag.lower(), 0)

    title_terms = Counter(_tokens(document.title))
    type_terms = Counter(_tokens(document.doc_type.replace("_", " ")))
    score += sum(task_tokens[token] * title_terms[token] * 1.5 for token in task_tokens)
    score += sum(task_tokens[token] * type_terms[token] for token in task_tokens)
    return score


def _document_terms(document: Document) -> set[str]:
    terms = set(_tokens(document.title))
    terms.update(_tokens(document.doc_type.replace("_", " ")))
    if document.area:
        terms.add(document.area.lower())
    terms.update(tag.lower() for tag in document.tags)
    terms.update(_tokens(document.content_markdown))
    return terms


def _tokens(value: str) -> Counter[str]:
    return Counter(token.lower() for token in TOKEN_RE.findall(value))


def _reason(*, matched_terms: list[str], document: Document, score: float) -> str:
    if matched_terms:
        return (
            f"Matched task terms {', '.join(matched_terms)} against "
            f"{document.area or 'document metadata'} and content."
        )
    if score > 0:
        return "Matched indirectly through document metadata and content."
    return "Returned as lower-priority fallback because few stronger documents were available."
