from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from context_router.schemas.value_mapping import (
    ValueMappingPreviewRequest,
    ValueMappingWrite,
)
from context_router.services.value_mapping import ValueMappingError, ValueMappingService

router = APIRouter(prefix="/value-mappings", tags=["value-mappings"])


def _service(request: Request) -> ValueMappingService:
    return request.app.state.value_mapping_service


def _error(exc: ValueMappingError) -> HTTPException:
    if exc.code in {"mapping_not_found", "workspace_not_found", "interface_not_found"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {"duplicate_key", "duplicate_alias", "duplicate_binding"}:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=f"{exc.code}: {exc}")


@router.get("/overview")
def overview(
    request: Request,
    workspace_id: str = Query(min_length=1, max_length=36),
    keyword: str = Query(default="", max_length=240),
):
    try:
        return _service(request).overview(workspace_id, keyword)
    except ValueMappingError as exc:
        raise _error(exc) from exc


@router.get("/interfaces")
def search_interfaces(
    request: Request,
    workspace_id: str = Query(min_length=1, max_length=36),
    keyword: str = Query(default="", max_length=240),
    limit: int = Query(default=30, ge=1, le=100),
):
    try:
        return _service(request).search_interfaces(
            workspace_id=workspace_id,
            keyword=keyword,
            limit=limit,
        )
    except ValueMappingError as exc:
        raise _error(exc) from exc


@router.get("/{mapping_id}")
def detail(mapping_id: str, request: Request):
    try:
        return _service(request).get(mapping_id)
    except ValueMappingError as exc:
        raise _error(exc) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
def create(payload: ValueMappingWrite, request: Request):
    try:
        return _service(request).create(payload)
    except ValueMappingError as exc:
        raise _error(exc) from exc


@router.put("/{mapping_id}")
def update(mapping_id: str, payload: ValueMappingWrite, request: Request):
    try:
        return _service(request).update(mapping_id, payload)
    except ValueMappingError as exc:
        raise _error(exc) from exc


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(mapping_id: str, request: Request):
    try:
        _service(request).delete(mapping_id)
    except ValueMappingError as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{mapping_id}/preview")
def preview(
    mapping_id: str,
    payload: ValueMappingPreviewRequest,
    request: Request,
):
    try:
        return _service(request).preview(
            mapping_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
            keyword=payload.keyword,
            limit=payload.limit,
        )
    except ValueMappingError as exc:
        raise _error(exc) from exc
