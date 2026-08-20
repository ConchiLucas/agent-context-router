from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.repositories.database_environment_repository import (
    DatabaseEnvironmentRepositoryError,
    DatabaseEnvironmentStore,
)
from context_router.repositories.nacos_profile_repository import (
    NacosProfileRecord,
    NacosProfileRepositoryError,
    NacosProfileStore,
    NacosProfileWrite,
)
from context_router.repositories.workspace_repository import (
    WorkspaceRepositoryError,
    WorkspaceStore,
)
from context_router.schemas.nacos_profiles import (
    NacosComponentRule,
    NacosProfileKey,
    NacosProfileSummary,
    NacosProfileUpdate,
    WorkspaceNacosProfiles,
)

router = APIRouter(prefix="/workspaces", tags=["nacos-profiles"])


def _profiles(request: Request) -> NacosProfileStore:
    return request.app.state.nacos_profile_repository


def _workspaces(request: Request) -> WorkspaceStore:
    return request.app.state.workspace_repository


def _environments(request: Request) -> DatabaseEnvironmentStore | None:
    return getattr(request.app.state, "database_environment_repository", None)


@router.get(
    "/{workspace_id}/nacos-profiles",
    response_model=WorkspaceNacosProfiles,
)
def list_nacos_profiles(
    workspace_id: str,
    request: Request,
    response: Response,
) -> WorkspaceNacosProfiles:
    response.headers["Cache-Control"] = "no-store"
    try:
        _workspaces(request).get_workspace(workspace_id)
        records = _profiles(request).list_profiles(workspace_id)
    except (WorkspaceRepositoryError, NacosProfileRepositoryError) as exc:
        raise _http_error(exc) from exc
    return WorkspaceNacosProfiles(
        workspace_id=workspace_id,
        profiles=[_summary(record) for record in records],
    )


@router.put(
    "/{workspace_id}/nacos-profiles/{profile_key}",
    response_model=NacosProfileSummary,
)
def upsert_nacos_profile(
    workspace_id: str,
    profile_key: NacosProfileKey,
    payload: NacosProfileUpdate,
    request: Request,
    response: Response,
) -> NacosProfileSummary:
    response.headers["Cache-Control"] = "no-store"
    try:
        _workspaces(request).get_workspace(workspace_id)
        environments = _environments(request)
        if environments is not None and not environments.has_environment(
            workspace_id, profile_key
        ):
            raise DatabaseEnvironmentRepositoryError("工作空间没有配置所选环境")
        record = _profiles(request).upsert_profile(
            NacosProfileWrite(
                workspace_id=workspace_id,
                profile_key=profile_key,
                base_url=payload.base_url,
                namespace_id=payload.namespace_id,
                username=payload.username,
                password=payload.password,
                request_timeout_ms=payload.request_timeout_ms,
                components=[component.model_dump(mode="json") for component in payload.components],
            )
        )
    except (
        WorkspaceRepositoryError,
        NacosProfileRepositoryError,
        DatabaseEnvironmentRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc
    return _summary(record)


@router.delete(
    "/{workspace_id}/nacos-profiles/{profile_key}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_nacos_profile(
    workspace_id: str,
    profile_key: NacosProfileKey,
    request: Request,
) -> Response:
    try:
        _workspaces(request).get_workspace(workspace_id)
        _profiles(request).delete_profile(workspace_id, profile_key)
    except (WorkspaceRepositoryError, NacosProfileRepositoryError) as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _summary(record: NacosProfileRecord) -> NacosProfileSummary:
    return NacosProfileSummary(
        workspace_id=record.workspace_id,
        profile_key=record.profile_key,
        base_url=record.base_url,
        namespace_id=record.namespace_id,
        username=record.username,
        password_configured=bool(record.password),
        request_timeout_ms=record.request_timeout_ms,
        components=[NacosComponentRule.model_validate(item) for item in record.components],
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _http_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", None)
    if code == "nacos_not_configured" or isinstance(exc, WorkspaceRepositoryError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
