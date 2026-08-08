from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.schemas.system_guides import (
    SystemGuideContentWrite,
    SystemGuideDetail,
    SystemGuideWrite,
)
from context_router.services.system_guides import SystemGuideError, SystemGuideService

router = APIRouter(prefix="/system-guides", tags=["system-guides"])


def _service(request: Request) -> SystemGuideService:
    return request.app.state.system_guide_service


def _http_error(exc: SystemGuideError) -> HTTPException:
    message = str(exc)
    code = status.HTTP_404_NOT_FOUND if message == "系统文档不存在" else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=message)


@router.get("", response_model=list[SystemGuideDetail])
def list_system_guides(request: Request) -> list[SystemGuideDetail]:
    return _service(request).list_guides()


@router.get("/{guide_id}", response_model=SystemGuideDetail)
def get_system_guide(guide_id: str, request: Request) -> SystemGuideDetail:
    try:
        return _service(request).get_guide(guide_id)
    except SystemGuideError as exc:
        raise _http_error(exc) from exc


@router.post("", response_model=SystemGuideDetail, status_code=status.HTTP_201_CREATED)
def create_system_guide(payload: SystemGuideWrite, request: Request) -> SystemGuideDetail:
    try:
        return _service(request).create_guide(payload)
    except SystemGuideError as exc:
        raise _http_error(exc) from exc


@router.put("/{guide_id}", response_model=SystemGuideDetail)
def update_system_guide(
    guide_id: str,
    payload: SystemGuideWrite,
    request: Request,
) -> SystemGuideDetail:
    try:
        return _service(request).update_guide(guide_id, payload)
    except SystemGuideError as exc:
        raise _http_error(exc) from exc


@router.put("/{guide_id}/content", response_model=SystemGuideDetail)
def update_system_guide_content(
    guide_id: str,
    payload: SystemGuideContentWrite,
    request: Request,
) -> SystemGuideDetail:
    try:
        return _service(request).update_content(guide_id, payload)
    except SystemGuideError as exc:
        raise _http_error(exc) from exc


@router.delete("/{guide_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_system_guide(guide_id: str, request: Request) -> Response:
    try:
        _service(request).delete_guide(guide_id)
    except SystemGuideError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
