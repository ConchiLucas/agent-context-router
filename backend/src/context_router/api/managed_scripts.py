from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.repositories.managed_script_repository import (
    ManagedScriptRepositoryError,
)
from context_router.schemas.managed_scripts import (
    ManagedScript,
    ManagedScriptAutostartUpdate,
    ManagedScriptList,
    ManagedScriptRunRequest,
    ManagedScriptRunResult,
)
from context_router.services.managed_scripts import ManagedScriptsError, ManagedScriptsService

router = APIRouter(prefix="/managed-scripts", tags=["managed-scripts"])


def _service(request: Request) -> ManagedScriptsService:
    return request.app.state.managed_scripts_service


@router.get("", response_model=ManagedScriptList)
def list_managed_scripts(request: Request, response: Response) -> ManagedScriptList:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).list_scripts()
    except (ManagedScriptsError, ManagedScriptRepositoryError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{script_id}/autostart", response_model=ManagedScript)
def set_managed_script_autostart(
    script_id: str,
    payload: ManagedScriptAutostartUpdate,
    request: Request,
    response: Response,
) -> ManagedScript:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).set_autostart(script_id, payload.enabled)
    except (ManagedScriptsError, ManagedScriptRepositoryError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{script_id}/run", response_model=ManagedScriptRunResult)
def run_managed_script(
    script_id: str,
    payload: ManagedScriptRunRequest,
    request: Request,
    response: Response,
) -> ManagedScriptRunResult:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).run(script_id, payload.workspace_id)
    except (ManagedScriptsError, ManagedScriptRepositoryError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
