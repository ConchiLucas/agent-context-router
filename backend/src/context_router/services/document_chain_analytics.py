from __future__ import annotations

from context_router.repositories.document_chain_analytics_repository import (
    DocumentChainAnalyticsRepositoryError,
    DocumentChainAnalyticsStore,
)
from context_router.schemas.document_chain_analytics import (
    DocumentChainAnalyticsResponse,
)


class DocumentChainAnalyticsServiceError(RuntimeError):
    pass


class DocumentChainAnalyticsService:
    def __init__(self, repository: DocumentChainAnalyticsStore) -> None:
        self._repository = repository

    def get_chain_analytics(
        self,
        *,
        workspace_id: str | None = None,
        limit: int = 50,
    ) -> DocumentChainAnalyticsResponse:
        try:
            return self._repository.get_chain_analytics(
                workspace_id=workspace_id,
                limit=limit,
            )
        except DocumentChainAnalyticsRepositoryError as exc:
            raise DocumentChainAnalyticsServiceError(str(exc)) from exc
