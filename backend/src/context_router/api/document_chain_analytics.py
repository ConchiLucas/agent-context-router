from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.schemas.document_chain_analytics import (
    DocumentChainAnalyticsResponse,
)
from context_router.services.document_chain_analytics import (
    DocumentChainAnalyticsService,
    DocumentChainAnalyticsServiceError,
)

router = APIRouter(tags=["document-chain-analytics"])


def _analytics_service(request: Request) -> DocumentChainAnalyticsService:
    return request.app.state.document_chain_analytics_service


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


@router.get(
    "/document-chain-analytics",
    response_model=DocumentChainAnalyticsResponse,
)
def get_document_chain_analytics(
    request: Request,
    workspace_id: str | None = Query(None, description="工作空间 ID 过滤"),
    limit: int = Query(50, ge=1, le=200, description="健康度矩阵文档显示上限"),
) -> DocumentChainAnalyticsResponse:
    service = _analytics_service(request)
    try:
        return service.get_chain_analytics(
            workspace_id=workspace_id,
            limit=limit,
        )
    except DocumentChainAnalyticsServiceError as exc:
        raise _bad_request(str(exc)) from exc
