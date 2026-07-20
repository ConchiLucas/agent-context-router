from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from context_router.schemas.context import ContextDocumentReadRequest
from context_router.services.context_document_read import (
    ContextDocumentReadError,
    ContextDocumentReadService,
)
from context_router.services.context_preparation import (
    ContextPreparationError,
    ContextPreparationService,
)


def create_context_router_mcp(
    preparation_service: ContextPreparationService,
    document_read_service: ContextDocumentReadService,
) -> FastMCP:
    server = FastMCP(
        name="Context Router",
        instructions=(
            "Call prepare_task_context once at the start of a new project task. Preserve the "
            "returned task_id and pass it to every read_context_document call for that task. "
            "Call prepare again for a new conversation when no task_id is available."
        ),
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
    )

    @server.tool(
        name="prepare_task_context",
        description=(
            "Locate the registered project for cwd, create a server-side task number, and "
            "return its complete document tree. Summaries are only returned when explicitly "
            "declared in Markdown Front Matter."
        ),
    )
    def prepare_task_context(
        task: Annotated[str, Field(min_length=1, max_length=4000)],
        cwd: Annotated[str, Field(min_length=1)],
        agent_name: Annotated[str | None, Field(max_length=64)] = None,
    ) -> dict[str, Any]:
        try:
            result = preparation_service.prepare(task=task, cwd=cwd, agent_name=agent_name)
        except ContextPreparationError as exc:
            raise ToolError(str(exc)) from exc
        return result.model_dump(exclude_none=True)

    @server.tool(
        name="read_context_document",
        description=(
            "Read one or more Markdown documents or exact ATX-heading sections from the project "
            "selected by prepare_task_context. task_id must be the value returned for the current "
            "task. Results preserve request order and every call is recorded server-side."
        ),
    )
    def read_context_document(
        task_id: Annotated[int, Field(ge=1)],
        requests: Annotated[
            list[ContextDocumentReadRequest],
            Field(min_length=1, max_length=10),
        ],
    ) -> dict[str, Any]:
        try:
            result = document_read_service.read(task_id=task_id, requests=requests)
        except ContextDocumentReadError as exc:
            raise ToolError(str(exc)) from exc
        return result.model_dump(exclude_none=True)

    return server
