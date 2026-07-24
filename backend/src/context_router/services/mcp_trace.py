from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime

from context_router.repositories.database_call_repository import (
    DatabaseCallRepositoryError,
    DatabaseCallStore,
)
from context_router.repositories.document_read_repository import (
    DocumentReadRepositoryError,
    DocumentReadStore,
)
from context_router.repositories.mcp_tool_call_repository import (
    McpToolCallRepositoryError,
    McpToolCallSource,
    McpToolCallStatus,
    McpToolCallStore,
    McpToolCallWrite,
)
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
from context_router.schemas.context import ContextReadHistoryItem
from context_router.schemas.mcp_traces import (
    McpTraceArtifact,
    McpTraceCall,
    McpTraceDatabaseCallArtifact,
    McpTraceDetail,
    McpTraceDocumentReadArtifact,
    McpTraceSummary,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

logger = logging.getLogger(__name__)
_CURRENT_TOOL_CALL_ID: ContextVar[int | None] = ContextVar(
    "context_router_current_tool_call_id",
    default=None,
)


class McpTraceServiceError(RuntimeError):
    pass


def current_tool_call_id() -> int | None:
    return _CURRENT_TOOL_CALL_ID.get()


class McpTraceService:
    def __init__(
        self,
        *,
        tool_call_repository: McpToolCallStore,
        task_repository: TaskReader,
        document_read_repository: DocumentReadStore,
        database_call_repository: DatabaseCallStore,
        registry: ProjectRegistry,
    ) -> None:
        self._tool_calls = tool_call_repository
        self._tasks = task_repository
        self._document_reads = document_read_repository
        self._database_calls = database_call_repository
        self._registry = registry

    def start_call(
        self,
        *,
        task_id: int,
        server_name: str,
        tool_name: str,
        source: McpToolCallSource = "server",
        started_at: datetime | None = None,
        request_summary: dict[str, object] | None = None,
        parent_tool_call_id: int | None = None,
    ) -> int | None:
        try:
            return self._tool_calls.create_call(
                McpToolCallWrite(
                    task_id=task_id,
                    parent_tool_call_id=parent_tool_call_id,
                    server_name=server_name,
                    tool_name=tool_name,
                    source=source,
                    status="running",
                    started_at=started_at or datetime.now(UTC),
                    request_summary=request_summary,
                )
            )
        except McpToolCallRepositoryError:
            logger.warning("Unable to persist MCP tool-call start metadata", exc_info=True)
            return None

    def record_completed_call(
        self,
        *,
        task_id: int,
        server_name: str,
        tool_name: str,
        source: McpToolCallSource = "server",
        started_at: datetime,
        finished_at: datetime,
        duration_ms: int,
        request_summary: dict[str, object] | None = None,
        result_summary: dict[str, object] | None = None,
    ) -> int | None:
        try:
            return self._tool_calls.create_call(
                McpToolCallWrite(
                    task_id=task_id,
                    server_name=server_name,
                    tool_name=tool_name,
                    source=source,
                    status="ok",
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    request_summary=request_summary,
                    result_summary=result_summary,
                )
            )
        except McpToolCallRepositoryError:
            logger.warning("Unable to persist completed MCP tool-call metadata", exc_info=True)
            return None

    def finish_call(
        self,
        tool_call_id: int | None,
        *,
        status: McpToolCallStatus,
        finished_at: datetime,
        duration_ms: int,
        result_summary: dict[str, object] | None = None,
        error_code: str | None = None,
    ) -> None:
        if tool_call_id is None:
            return
        try:
            self._tool_calls.complete_call(
                tool_call_id,
                status=status,
                finished_at=finished_at,
                duration_ms=duration_ms,
                result_summary=result_summary,
                error_code=error_code,
            )
        except McpToolCallRepositoryError:
            logger.warning("Unable to persist MCP tool-call completion metadata", exc_info=True)

    @staticmethod
    def bind_call(tool_call_id: int | None) -> Token[int | None]:
        return _CURRENT_TOOL_CALL_ID.set(tool_call_id)

    @staticmethod
    def reset_call(token: Token[int | None]) -> None:
        _CURRENT_TOOL_CALL_ID.reset(token)

    def list_traces(
        self,
        *,
        project_id: str | None = None,
        agent_name: str | None = None,
        server_name: str | None = None,
        tool_name: str | None = None,
        status: McpToolCallStatus | None = None,
        keyword: str | None = None,
        limit: int = 30,
    ) -> list[McpTraceSummary]:
        project_key = None
        if project_id is not None:
            try:
                project_key = self._registry.get_project_key(project_id)
            except ProjectRegistryError as exc:
                raise McpTraceServiceError(str(exc)) from exc
        try:
            records = self._tool_calls.list_traces(
                project_key=project_key,
                agent_name=agent_name,
                server_name=server_name,
                tool_name=tool_name,
                status=status,
                keyword=keyword,
                limit=limit,
            )
        except McpToolCallRepositoryError as exc:
            raise McpTraceServiceError(str(exc)) from exc
        return [
            McpTraceSummary(
                task_id=record.task_id,
                task=record.task,
                project_id=self._registry.find_project_id_by_key(record.project_key),
                project_name=record.project_name,
                cwd=record.cwd,
                agent_name=record.agent_name,
                created_at=record.created_at,
                call_count=record.call_count,
                error_count=record.error_count,
                server_names=sorted(record.server_names),
                last_activity_at=record.last_activity_at,
            )
            for record in records
        ]

    def get_trace(self, task_id: int) -> McpTraceDetail:
        try:
            task = self._tasks.get_task(task_id)
            calls = self._tool_calls.list_calls(task_id)
            document_reads = self._document_reads.list_read_calls(task_id)
            database_calls = self._database_calls.list_calls(task_id)
        except (
            TaskRepositoryError,
            McpToolCallRepositoryError,
            DocumentReadRepositoryError,
            DatabaseCallRepositoryError,
        ) as exc:
            raise McpTraceServiceError(str(exc)) from exc

        artifacts_by_call: dict[int, list[McpTraceArtifact]] = {}
        for read_call in document_reads:
            if read_call.tool_call_id is None:
                continue
            artifacts_by_call.setdefault(read_call.tool_call_id, []).append(
                McpTraceDocumentReadArtifact(
                    read_call_id=read_call.id,
                    documents=[
                        ContextReadHistoryItem(
                            position=item.position,
                            document_id=item.document_id,
                            path=item.document_path,
                            section=item.requested_section,
                            status=item.status,
                            error_code=item.error_code,
                        )
                        for item in read_call.items
                    ],
                )
            )
        for database_call in database_calls:
            if database_call.tool_call_id is None:
                continue
            artifacts_by_call.setdefault(database_call.tool_call_id, []).append(
                McpTraceDatabaseCallArtifact(
                    database_call_id=database_call.id,
                    operation=database_call.operation,
                    database=database_call.database_alias,
                    engine=database_call.engine,
                    status=database_call.status,
                    object_type=database_call.object_type,
                    statement_type=database_call.statement_type,
                    duration_ms=database_call.duration_ms,
                    returned_count=database_call.returned_count,
                    result_bytes=database_call.result_bytes,
                    truncated=database_call.truncated,
                    error_code=database_call.error_code,
                )
            )

        trace_calls = [
            McpTraceCall(
                tool_call_id=call.id,
                sequence=sequence,
                parent_tool_call_id=call.parent_tool_call_id,
                server_name=call.server_name,
                tool_name=call.tool_name,
                source=call.source,
                status=call.status,
                started_at=call.started_at,
                finished_at=call.finished_at,
                duration_ms=call.duration_ms,
                request_summary=call.request_summary,
                result_summary=call.result_summary,
                error_code=call.error_code,
                artifacts=artifacts_by_call.get(call.id, []),
            )
            for sequence, call in enumerate(calls, start=1)
        ]
        error_count = sum(1 for call in calls if call.status == "error")
        last_activity_at = max(
            (call.finished_at or call.started_at for call in calls),
            default=task.created_at,
        )
        return McpTraceDetail(
            task_id=task.id,
            task=task.task,
            project_id=self._registry.find_project_id_by_key(task.project_key),
            project_name=task.project_name,
            cwd=task.cwd,
            agent_name=task.agent_name,
            created_at=task.created_at,
            call_count=len(calls),
            error_count=error_count,
            server_names=sorted({call.server_name for call in calls}),
            last_activity_at=last_activity_at,
            calls=trace_calls,
        )
