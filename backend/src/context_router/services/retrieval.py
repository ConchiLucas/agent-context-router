from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from context_router.db.models import Document, Project
from context_router.schemas.context import ContextDocument
from context_router.services.embeddings import EmbeddingProvider, cosine_similarity

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)


def retrieve_documents(
    session: Session,
    *,
    project: Project,
    task: str,
    max_documents: int,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[ContextDocument]:
    documents = session.scalars(
        select(Document)
        .where(Document.project_id == project.id, Document.status == "active")
        .options(selectinload(Document.chunks))
    ).all()
    task_tokens = _tokens(task)
    task_embedding = None
    if embedding_provider is not None:
        task_embedding = embedding_provider.embed([task])[0]

    scored = [
        _score_document(document, task_tokens, task_embedding=task_embedding)
        for document in documents
    ]
    scored.sort(key=lambda result: (-result.score, result.document_id))

    ranked: list[ContextDocument] = []
    for index, result in enumerate(scored[:max_documents], start=1):
        ranked.append(result.model_copy(update={"rank": index}))

    return ranked


def _score_document(
    document: Document,
    task_tokens: Counter[str],
    *,
    task_embedding: list[float] | None,
) -> ContextDocument:
    searchable_terms = _document_terms(document)
    matched_terms = sorted(token for token in task_tokens if token in searchable_terms)
    metadata_score = _metadata_score(document, task_tokens)

    best_chunk_id: str | None = None
    best_excerpt = document.content_markdown.strip().replace("\n", " ")[:180]
    best_chunk_score = 0.0

    for chunk in document.chunks:
        chunk_terms = Counter(_tokens(chunk.content))
        chunk_score = sum(task_tokens[token] * chunk_terms[token] for token in task_tokens)
        chunk_score += cosine_similarity(task_embedding, chunk.embedding)
        if chunk_score > best_chunk_score:
            best_chunk_score = float(chunk_score)
            best_chunk_id = chunk.id
            best_excerpt = chunk.content.strip().replace("\n", " ")[:180]

    score = metadata_score + best_chunk_score
    reason = _reason(matched_terms=matched_terms, document=document, score=score)
    return ContextDocument(
        document_id=document.id,
        title=document.title,
        reason=reason,
        score=round(score, 4),
        excerpt=best_excerpt,
        chunk_id=best_chunk_id,
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
    for chunk in document.chunks:
        terms.update(_tokens(chunk.content))
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
