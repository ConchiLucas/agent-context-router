from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from context_router.database.errors import DatabaseAccessError
from context_router.schemas.context import ContextDocumentReadRequest
from context_router.services.context_document_read import (
    ContextDocumentReadError,
    ContextDocumentReadService,
)
from context_router.services.context_preparation import (
    ContextPreparationError,
    ContextPreparationService,
)
from context_router.services.database_catalog import DatabaseCatalogService
from context_router.services.database_query import DatabaseQueryService

MCP_SERVER_NAME = "Context Router"
MCP_SERVER_INSTRUCTIONS = (
    "Call prepare_task_context once at the start of a new project task. Preserve the "
    "returned task_id and pass it to every document or database call for that task. "
    "Use only database aliases returned by prepare. Search database objects before querying "
    "when the schema is uncertain. Database queries are always bounded and read-only. Call "
    "prepare again for a new conversation when no task_id is available."
)
PREPARE_TOOL_NAME = "prepare_task_context"
PREPARE_TOOL_DESCRIPTION = (
    "Locate the registered project for cwd, create a server-side task number, and "
    "return its complete document tree. Summaries are only returned when explicitly "
    "declared in Markdown Front Matter."
)
READ_TOOL_NAME = "read_context_document"
READ_TOOL_DESCRIPTION = (
    "Read one or more Markdown documents or exact ATX-heading sections from the project "
    "selected by prepare_task_context. task_id must be the value returned for the current "
    "task. Results preserve request order and every call is recorded server-side."
)
SEARCH_DATABASE_TOOL_NAME = "search_database_objects"
SEARCH_DATABASE_TOOL_DESCRIPTION = (
    "Search schemas, tables, views, columns, or indexes in a database authorized for the "
    "current task. Use names first and request summary/full details only when needed."
)
EXECUTE_DATABASE_TOOL_NAME = "execute_database_query"
EXECUTE_DATABASE_TOOL_DESCRIPTION = (
    "Execute exactly one bounded read-only SQL statement against a database alias returned "
    "by prepare_task_context. Connection details and query limits are enforced server-side."
)
PREPARE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
READ_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
DATABASE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_context_router_mcp(
    preparation_service: ContextPreparationService,
    document_read_service: ContextDocumentReadService,
    database_catalog_service: DatabaseCatalogService | None = None,
    database_query_service: DatabaseQueryService | None = None,
) -> FastMCP:
    server = FastMCP(
        name=MCP_SERVER_NAME,
        instructions=MCP_SERVER_INSTRUCTIONS,
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
    )

    @server.tool(
        name=PREPARE_TOOL_NAME,
        description=PREPARE_TOOL_DESCRIPTION,
        annotations=PREPARE_TOOL_ANNOTATIONS,
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
        name=READ_TOOL_NAME,
        description=READ_TOOL_DESCRIPTION,
        annotations=READ_TOOL_ANNOTATIONS,
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

    @server.tool(
        name=SEARCH_DATABASE_TOOL_NAME,
        description=SEARCH_DATABASE_TOOL_DESCRIPTION,
        annotations=DATABASE_TOOL_ANNOTATIONS,
    )
    def search_database_objects(
        task_id: Annotated[int, Field(ge=1)],
        database: Annotated[
            str,
            Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"),
        ],
        object_type: Literal["schema", "table", "view", "column", "index"],
        pattern: Annotated[str, Field(min_length=1, max_length=255)] = "*",
        detail: Literal["names", "summary", "full"] = "names",
        schema: Annotated[str | None, Field(max_length=255)] = None,
        table: Annotated[str | None, Field(max_length=255)] = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> dict[str, object]:
        if database_catalog_service is None:
            raise ToolError("database_tools_disabled: 数据库工具当前不可用")
        try:
            return database_catalog_service.search(
                task_id=task_id,
                database=database,
                object_type=object_type,
                pattern=pattern,
                detail=detail,
                schema=schema,
                table=table,
                limit=limit,
            )
        except DatabaseAccessError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @server.tool(
        name=EXECUTE_DATABASE_TOOL_NAME,
        description=EXECUTE_DATABASE_TOOL_DESCRIPTION,
        annotations=DATABASE_TOOL_ANNOTATIONS,
    )
    def execute_database_query(
        task_id: Annotated[int, Field(ge=1)],
        database: Annotated[
            str,
            Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"),
        ],
        sql: Annotated[str, Field(min_length=1, max_length=200_000)],
    ) -> dict[str, object]:
        if database_query_service is None:
            raise ToolError("database_tools_disabled: 数据库工具当前不可用")
        try:
            return database_query_service.execute(task_id=task_id, database=database, sql=sql)
        except DatabaseAccessError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    return server
