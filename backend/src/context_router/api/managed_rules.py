from typing import NoReturn

from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.repositories.managed_rule_repository import ManagedRuleRepositoryError
from context_router.schemas.managed_rules import ManagedRule, ManagedRuleList, ManagedRuleWrite
from context_router.services.managed_rules import (
    ManagedRulesError,
    ManagedRulesService,
    http_status_for_rules_error,
)

router = APIRouter(prefix="/managed-rules", tags=["managed-rules"])


def _service(request: Request) -> ManagedRulesService:
    return request.app.state.managed_rules_service


def _raise(exc: ManagedRulesError | ManagedRuleRepositoryError) -> NoReturn:
    raise HTTPException(
        status_code=http_status_for_rules_error(exc),
        detail=str(exc),
    ) from exc


@router.get("", response_model=ManagedRuleList)
def list_managed_rules(request: Request, response: Response) -> ManagedRuleList:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).list_rules()
    except (ManagedRulesError, ManagedRuleRepositoryError) as exc:
        _raise(exc)


@router.post("", response_model=ManagedRule, status_code=status.HTTP_201_CREATED)
def create_managed_rule(
    payload: ManagedRuleWrite,
    request: Request,
    response: Response,
) -> ManagedRule:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).create_rule(payload)
    except (ManagedRulesError, ManagedRuleRepositoryError) as exc:
        _raise(exc)


@router.put("/{rule_id}", response_model=ManagedRule)
def update_managed_rule(
    rule_id: str,
    payload: ManagedRuleWrite,
    request: Request,
    response: Response,
) -> ManagedRule:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _service(request).update_rule(rule_id, payload)
    except (ManagedRulesError, ManagedRuleRepositoryError) as exc:
        _raise(exc)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_managed_rule(rule_id: str, request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    try:
        _service(request).delete_rule(rule_id)
    except (ManagedRulesError, ManagedRuleRepositoryError) as exc:
        _raise(exc)
