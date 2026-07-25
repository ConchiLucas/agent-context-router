from __future__ import annotations

import hashlib
from pathlib import Path

from context_router.repositories.document_search_repository import (
    DocumentSearchChunkWrite,
    DocumentSearchRepositoryError,
    DocumentSearchStore,
)
from context_router.services.document_tree import CachedDocument, DocumentCache
from context_router.services.markdown_search_parser import parse_markdown_search_chunks

DOCUMENT_SEARCH_INDEX_FORMAT_VERSION = 1


class DocumentSearchIndexError(RuntimeError):
    pass


class DocumentSearchIndexer:
    """Build the derived lexical index for one immutable document cache version."""

    def __init__(self, repository: DocumentSearchStore) -> None:
        self._repository = repository

    def ensure_project_index(
        self,
        *,
        project_id: str,
        cache: DocumentCache,
    ) -> None:
        try:
            state = self._repository.get_index_state(project_id)
        except DocumentSearchRepositoryError as exc:
            raise DocumentSearchIndexError(str(exc)) from exc

        if (
            state is not None
            and state.index_version == cache.version
            and state.index_format_version == DOCUMENT_SEARCH_INDEX_FORMAT_VERSION
        ):
            return
        self.rebuild_project_index(project_id=project_id, cache=cache)

    def rebuild_project_index(
        self,
        *,
        project_id: str,
        cache: DocumentCache,
    ) -> None:
        chunks = [
            chunk
            for document in sorted(cache.documents.values(), key=lambda item: item.id)
            for chunk in self._document_chunks(document, cache)
        ]
        try:
            self._repository.replace_project_index(
                project_id=project_id,
                index_version=cache.version,
                index_format_version=DOCUMENT_SEARCH_INDEX_FORMAT_VERSION,
                chunks=chunks,
            )
        except DocumentSearchRepositoryError as exc:
            raise DocumentSearchIndexError(str(exc)) from exc

    @staticmethod
    def _document_chunks(
        document: CachedDocument,
        cache: DocumentCache,
    ) -> list[DocumentSearchChunkWrite]:
        path = _relative_path(document, cache)
        content_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
        return [
            DocumentSearchChunkWrite(
                document_id=document.id,
                path=path,
                title=document.title,
                summary=document.summary,
                section=chunk.section,
                section_path=chunk.section_path,
                section_ordinal=chunk.section_ordinal,
                section_readable=chunk.section_readable,
                chunk_index=chunk.chunk_index,
                body_text=chunk.body_text,
                content_hash=content_hash,
            )
            for chunk in parse_markdown_search_chunks(document.content)
        ]


def _relative_path(document: CachedDocument, cache: DocumentCache) -> str:
    try:
        return Path(document.path).resolve().relative_to(cache.project_root).as_posix()
    except ValueError:
        if document.relative_path:
            return document.relative_path.removeprefix("./")
        return "AGENTS.md"
