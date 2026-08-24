from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.repositories.shared_ai_default_repository import (
    SharedAiDefaultRepositoryError,
)
from context_router.schemas.shared_config import (
    SharedAiCatalog,
    SharedAiDefaultUpdate,
    SharedConfigurationCatalog,
)
from context_router.services.shared_ai_config import SharedAiConfigService
from context_router.services.shared_config_client import SharedConfigCenterError

router = APIRouter(prefix="/shared-config/ai", tags=["shared-config"])


def _service(request: Request) -> SharedAiConfigService:
    return request.app.state.shared_ai_config_service


@router.get("", response_model=SharedAiCatalog)
def get_shared_ai_config(request: Request, response: Response) -> SharedAiCatalog:
    response.headers["Cache-Control"] = "no-store"
    return _catalog(request, refresh=True)


@router.get("/catalog", response_model=SharedConfigurationCatalog)
def get_shared_configuration_catalog(
    request: Request, response: Response
) -> SharedConfigurationCatalog:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).full_catalog()
    except SharedAiDefaultRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except SharedConfigCenterError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/refresh", response_model=SharedAiCatalog)
def refresh_shared_ai_config(request: Request, response: Response) -> SharedAiCatalog:
    response.headers["Cache-Control"] = "no-store"
    return _catalog(request, refresh=True)


@router.put("/default", response_model=SharedAiCatalog)
def save_shared_ai_default(
    payload: SharedAiDefaultUpdate,
    request: Request,
    response: Response,
) -> SharedAiCatalog:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).save_default(payload.provider_id, payload.revision)
    except SharedAiDefaultRepositoryError as exc:
        status_code = (
            status.HTTP_409_CONFLICT
            if "其他操作更新" in str(exc)
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except (SharedConfigCenterError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def _catalog(request: Request, *, refresh: bool) -> SharedAiCatalog:
    try:
        return _service(request).catalog(refresh=refresh)
    except SharedAiDefaultRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except SharedConfigCenterError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
