from __future__ import annotations

from context_router.repositories.document_read_stats_repository import (
    DocumentReadStatsRepositoryError,
    DocumentReadStatsStore,
)
from context_router.schemas.document_read_stats import (
    DocumentReadStatItem,
    DocumentReadTaskItem,
)


class DocumentReadStatsServiceError(RuntimeError):
    pass


class DocumentReadStatsService:
    def __init__(self, repository: DocumentReadStatsStore) -> None:
        self._repository = repository

    def list_document_read_stats(
        self,
        *,
        workspace_id: str | None = None,
        limit: int = 50,
    ) -> list[DocumentReadStatItem]:
        try:
            return self._repository.get_document_read_stats(
                workspace_id=workspace_id,
                limit=limit,
            )
        except DocumentReadStatsRepositoryError as exc:
            raise DocumentReadStatsServiceError(str(exc)) from exc

    def list_document_read_tasks(
        self,
        document_id: str,
        *,
        limit: int = 50,
    ) -> list[DocumentReadTaskItem]:
        if not document_id or not document_id.strip():
            raise DocumentReadStatsServiceError("document_id 不能为空")

        clean_doc_id = document_id.strip()
        if clean_doc_id.endswith("/AGENTS.md") or clean_doc_id == "AGENTS.md":
            return []

        try:
            return self._repository.get_document_read_tasks(
                clean_doc_id,
                limit=limit,
            )
        except DocumentReadStatsRepositoryError as exc:
            raise DocumentReadStatsServiceError(str(exc)) from exc
