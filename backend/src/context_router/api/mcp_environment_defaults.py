from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.mcp_environment import (
    MCP_ENVIRONMENT_SPECS,
    require_mcp_environment,
)
from context_router.repositories.mcp_environment_default_repository import (
    McpEnvironmentDefaultRepositoryError,
    McpEnvironmentDefaultStore,
)
from context_router.repositories.workspace_repository import (
    WorkspaceRepositoryError,
    WorkspaceStore,
)
from context_router.schemas.mcp_environment_defaults import (
    McpEnvironmentDefaultUpdate,
    McpEnvironmentOption,
    McpEnvironmentToolDefault,
    WorkspaceMcpEnvironmentDefaults,
)

router = APIRouter(prefix="/workspaces", tags=["mcp-environment-defaults"])

_LABELS = {"local": "LOCAL", "test": "TEST", "uat": "UAT"}


def _defaults(request: Request) -> McpEnvironmentDefaultStore:
    return request.app.state.mcp_environment_default_repository


def _workspaces(request: Request) -> WorkspaceStore:
    return request.app.state.workspace_repository


@router.get(
    "/{workspace_id}/mcp-environment-defaults",
    response_model=WorkspaceMcpEnvironmentDefaults,
)
def list_mcp_environment_defaults(
    workspace_id: str,
    request: Request,
    response: Response,
) -> WorkspaceMcpEnvironmentDefaults:
    response.headers["Cache-Control"] = "no-store"
    try:
        _workspaces(request).get_workspace(workspace_id)
        return _build_response(request, workspace_id)
    except (
        WorkspaceRepositoryError,
        McpEnvironmentDefaultRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


@router.put(
    "/{workspace_id}/mcp-environment-defaults/{tool_name}",
    response_model=McpEnvironmentToolDefault,
)
def update_mcp_environment_default(
    workspace_id: str,
    tool_name: str,
    payload: McpEnvironmentDefaultUpdate,
    request: Request,
    response: Response,
) -> McpEnvironmentToolDefault:
    response.headers["Cache-Control"] = "no-store"
    try:
        _workspaces(request).get_workspace(workspace_id)
        require_mcp_environment(tool_name, payload.environment)
        _defaults(request).upsert_default(
            workspace_id=workspace_id,
            tool_name=tool_name,
            environment=payload.environment,
        )
        result = _build_response(request, workspace_id)
        return next(tool for tool in result.tools if tool.tool_name == tool_name)
    except StopIteration as exc:  # pragma: no cover - guarded by registry validation
        raise HTTPException(status_code=404, detail="MCP 环境工具不存在") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except (
        WorkspaceRepositoryError,
        McpEnvironmentDefaultRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


def _build_response(request: Request, workspace_id: str) -> WorkspaceMcpEnvironmentDefaults:
    saved = {record.tool_name: record for record in _defaults(request).list_defaults(workspace_id)}
    tools: list[McpEnvironmentToolDefault] = []
    for spec in MCP_ENVIRONMENT_SPECS:
        configured = saved.get(spec.tool_name)
        if configured is not None:
            environment = configured.environment
            source = "configured"
        else:
            environment = spec.built_in_default
            source = "built_in"
        tools.append(
            McpEnvironmentToolDefault(
                tool_name=spec.tool_name,
                title=spec.title,
                description=spec.description,
                environments=[
                    McpEnvironmentOption(value=value, label=_LABELS[value])
                    for value in spec.environments
                ],
                default_environment=environment,  # type: ignore[arg-type]
                source=source,  # type: ignore[arg-type]
            )
        )
    return WorkspaceMcpEnvironmentDefaults(workspace_id=workspace_id, tools=tools)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkspaceRepositoryError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
