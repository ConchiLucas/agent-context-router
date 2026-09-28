from typing import Literal, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from context_router.repositories.interface_prompt_match_repository import (
    InterfacePromptMatchRepositoryError,
)
from context_router.schemas.interface_prompt_matches import (
    InterfacePromptClientResultImport,
    InterfacePromptClientResultImportResponse,
    InterfacePromptClientResultReset,
    InterfacePromptClientStoredResultReset,
    InterfacePromptMatch,
    InterfacePromptMatchCreate,
    InterfacePromptMatchList,
    PromptClientName,
)
from context_router.services.interface_prompt_matches import (
    InterfacePromptMatchError,
    InterfacePromptMatchService,
    http_status_for_prompt_match_error,
)

router = APIRouter(prefix="/interface-prompt-matches", tags=["interface-prompt-matches"])


def _service(request: Request) -> InterfacePromptMatchService:
    return request.app.state.interface_prompt_match_service


def _raise(exc: InterfacePromptMatchError | InterfacePromptMatchRepositoryError) -> NoReturn:
    raise HTTPException(
        status_code=http_status_for_prompt_match_error(exc),
        detail=str(exc),
    ) from exc


@router.post(
    "/client-results/import",
    response_model=InterfacePromptClientResultImportResponse,
)
def import_interface_prompt_client_results(
    payload: InterfacePromptClientResultImport,
    request: Request,
    response: Response,
) -> InterfacePromptClientResultImportResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).import_client_results(payload)
    except (InterfacePromptMatchError, InterfacePromptMatchRepositoryError) as exc:
        _raise(exc)


@router.delete(
    "/client-results/imported",
    response_model=InterfacePromptClientStoredResultReset,
)
def delete_imported_interface_prompt_client_results(
    request: Request,
    response: Response,
    workspace_id: str = Query(min_length=1, max_length=120),
    client: PromptClientName = Query(),  # noqa: B008
    expected_count: int = Query(ge=0),
) -> InterfacePromptClientStoredResultReset:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).delete_stored_client_results(
            workspace_id,
            client=client,
            expected_count=expected_count,
        )
    except (InterfacePromptMatchError, InterfacePromptMatchRepositoryError) as exc:
        _raise(exc)


@router.get("", response_model=InterfacePromptMatchList)
def list_interface_prompt_matches(
    request: Request,
    response: Response,
    workspace_id: str = Query(min_length=1, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    client: PromptClientName | None = Query(default=None),  # noqa: B008
) -> InterfacePromptMatchList:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).list_matches(
            workspace_id,
            page=page,
            page_size=page_size,
            prioritize_returned_for=client,
        )
    except (InterfacePromptMatchError, InterfacePromptMatchRepositoryError) as exc:
        _raise(exc)


@router.post("", response_model=InterfacePromptMatch, status_code=status.HTTP_201_CREATED)
def create_interface_prompt_match(
    payload: InterfacePromptMatchCreate,
    request: Request,
    response: Response,
) -> InterfacePromptMatch:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).create_match(payload)
    except (InterfacePromptMatchError, InterfacePromptMatchRepositoryError) as exc:
        _raise(exc)


@router.get("/client-results/reset-preview", response_model=InterfacePromptClientResultReset)
def preview_interface_prompt_client_result_reset(
    request: Request,
    response: Response,
    workspace_id: str = Query(min_length=1, max_length=120),
    client: Literal["antigravity"] = Query(default="antigravity"),
) -> InterfacePromptClientResultReset:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).preview_client_result_reset(workspace_id, client=client)
    except (InterfacePromptMatchError, InterfacePromptMatchRepositoryError) as exc:
        _raise(exc)


@router.delete("/client-results", response_model=InterfacePromptClientResultReset)
def reset_interface_prompt_client_results(
    request: Request,
    response: Response,
    workspace_id: str = Query(min_length=1, max_length=120),
    client: Literal["antigravity"] = Query(default="antigravity"),
    expected_task_count: int = Query(ge=0),
    expected_tool_call_count: int = Query(ge=0),
) -> InterfacePromptClientResultReset:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).reset_client_results(
            workspace_id,
            client=client,
            expected_task_count=expected_task_count,
            expected_tool_call_count=expected_tool_call_count,
        )
    except (InterfacePromptMatchError, InterfacePromptMatchRepositoryError) as exc:
        _raise(exc)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_interface_prompt_matches(
    request: Request,
    response: Response,
    workspace_id: str = Query(min_length=1, max_length=120),
) -> None:
    response.headers["Cache-Control"] = "no-store"
    try:
        _service(request).delete_matches(workspace_id)
    except (InterfacePromptMatchError, InterfacePromptMatchRepositoryError) as exc:
        _raise(exc)
