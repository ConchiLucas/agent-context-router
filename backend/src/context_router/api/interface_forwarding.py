from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from context_router.schemas.interface_forwarding import (
    InterfaceForwardingEnvironmentWrite,
    InterfaceForwardingExecute,
    InterfaceForwardingIdentityWrite,
    InterfaceForwardingImport,
    InterfaceForwardingLogWrite,
    InterfaceForwardingNamedWrite,
    InterfaceForwardingOverview,
    InterfaceForwardingRewriteResult,
    InterfaceForwardingResult,
)
from context_router.services.interface_forwarding import (
    InterfaceForwardingError,
    InterfaceForwardingService,
)

router = APIRouter(prefix="/interface-forwarding", tags=["interface-forwarding"])


def _service(request: Request) -> InterfaceForwardingService:
    return request.app.state.interface_forwarding_service


def _error(exc: InterfaceForwardingError) -> HTTPException:
    message = str(exc)
    code = (
        status.HTTP_404_NOT_FOUND
        if message.endswith(("不存在", "记录不存在"))
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=message)


@router.get("/overview", response_model=InterfaceForwardingOverview)
def overview(request: Request, workspace_id: str, keyword: str = ""):
    try:
        return _service(request).overview(workspace_id, keyword)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.post("/import", status_code=status.HTTP_201_CREATED)
def import_spec(payload: InterfaceForwardingImport, request: Request):
    try:
        return _service(request).import_spec(payload)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.put("/services/{service_id}")
def rename_service(service_id: str, payload: InterfaceForwardingNamedWrite, request: Request):
    try:
        return _service(request).rename_service(service_id, payload.name)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: str, request: Request):
    try:
        _service(request).delete_service(service_id)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/interfaces/{interface_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interface(interface_id: str, request: Request):
    try:
        _service(request).delete_interface(interface_id)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/interfaces/{interface_id}/state")
def interface_state(interface_id: str, request: Request):
    try:
        return _service(request).interface_state(interface_id)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.get("/interfaces/{interface_id}/logs")
def logs(interface_id: str, request: Request, limit: int = Query(default=50, ge=1, le=200)):
    try:
        return _service(request).logs(interface_id, limit)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.post("/interfaces/{interface_id}/logs", status_code=status.HTTP_201_CREATED)
def record_external_log(
    interface_id: str, payload: InterfaceForwardingLogWrite, request: Request
):
    try:
        return _service(request).record_external_log(interface_id, payload)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/rewrite-names",
    response_model=InterfaceForwardingRewriteResult,
)
def rewrite_names(
    workspace_id: str,
    request: Request,
    service_id: str | None = Query(default=None),
    path_prefix: str | None = Query(default=None),
):
    try:
        return _service(request).rewrite_names(
            workspace_id,
            service_id=service_id,
            path_prefix=path_prefix,
        )
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.post("/interfaces/{interface_id}/execute", response_model=InterfaceForwardingResult)
def execute(interface_id: str, payload: InterfaceForwardingExecute, request: Request):
    try:
        return _service(request).execute(interface_id, payload)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.get("/environments")
def environments(workspace_id: str, request: Request):
    try:
        return _service(request).list_environments(workspace_id)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.post("/environments", status_code=status.HTTP_201_CREATED)
def create_environment(payload: InterfaceForwardingEnvironmentWrite, request: Request):
    try:
        return _service(request).create_environment(payload)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.put("/environments/{environment_id}")
def update_environment(
    environment_id: str, payload: InterfaceForwardingEnvironmentWrite, request: Request
):
    try:
        return _service(request).update_environment(environment_id, payload)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.delete("/environments/{environment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_environment(environment_id: str, request: Request):
    try:
        _service(request).delete_environment(environment_id)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/identities")
def identities(workspace_id: str, request: Request, environment_id: str | None = None):
    try:
        return _service(request).list_identities(workspace_id, environment_id)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.post("/identities", status_code=status.HTTP_201_CREATED)
def create_identity(payload: InterfaceForwardingIdentityWrite, request: Request):
    try:
        return _service(request).create_identity(payload)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.put("/identities/{identity_id}")
def update_identity(identity_id: str, payload: InterfaceForwardingIdentityWrite, request: Request):
    try:
        return _service(request).update_identity(identity_id, payload)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc


@router.delete("/identities/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_identity(identity_id: str, request: Request):
    try:
        _service(request).delete_identity(identity_id)
    except InterfaceForwardingError as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
