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
    McpDatabaseToolPayloadDetail,
    McpTraceArtifact,
    McpTraceCall,
    McpTraceDatabaseCallArtifact,
    McpTraceDetail,
    McpTraceDocumentReadArtifact,
    McpTraceSummary,
)
from context_router.services.database_tool_payload import (
    DATABASE_PAYLOAD_TOOL_NAMES,
    DatabaseToolPayloadService,
    DatabaseToolPayloadServiceError,
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
        database_payload_service: DatabaseToolPayloadService | None = None,
    ) -> None:
        self._tool_calls = tool_call_repository
        self._tasks = task_repository
        self._document_reads = document_read_repository
        self._database_calls = database_call_repository
        self._registry = registry
        self._database_payloads = database_payload_service

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
        except Exception:
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
        except Exception:
            logger.warning("Unable to persist completed MCP tool-call metadata", exc_info=True)
            return None

    def record_failed_call(
        self,
        *,
        task_id: int,
        server_name: str,
        tool_name: str,
        started_at: datetime,
        finished_at: datetime,
        duration_ms: int,
        request_summary: dict[str, object] | None = None,
        error_code: str,
    ) -> int | None:
        try:
            return self._tool_calls.create_call(
                McpToolCallWrite(
                    task_id=task_id,
                    server_name=server_name,
                    tool_name=tool_name,
                    source="server",
                    status="error",
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    request_summary=request_summary,
                    error_code=error_code,
                )
            )
        except Exception:
            logger.warning("Unable to persist failed MCP tool-call metadata", exc_info=True)
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
        except Exception:
            logger.warning("Unable to persist MCP tool-call completion metadata", exc_info=True)

    @staticmethod
    def bind_call(tool_call_id: int | None) -> Token[int | None]:
        return _CURRENT_TOOL_CALL_ID.set(tool_call_id)

    @staticmethod
    def reset_call(token: Token[int | None]) -> None:
        _CURRENT_TOOL_CALL_ID.reset(token)

    def reconcile_interrupted_calls(self) -> int:
        try:
            recovered = self._tool_calls.fail_running_calls(finished_at=datetime.now(UTC))
        except Exception:
            logger.warning("Unable to reconcile interrupted MCP tool calls", exc_info=True)
            return 0
        if recovered:
            logger.warning(
                "Marked %s interrupted MCP tool call(s) as server_restarted",
                recovered,
            )
        return recovered

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
                project_id=project_id,
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
        summaries: list[McpTraceSummary] = []
        for record in records:
            trace_status, warnings = _trace_completeness(
                call_count=record.call_count,
                prepare_call_count=record.prepare_call_count,
                running_call_count=record.running_call_count,
                legacy_call_count=record.legacy_call_count,
                interrupted_call_count=record.interrupted_call_count,
                unlinked_document_read_count=record.unlinked_document_read_count,
                unlinked_database_call_count=record.unlinked_database_call_count,
            )
            summaries.append(
                McpTraceSummary(
                    task_id=record.task_id,
                    task=record.task,
                    project_id=record.project_id
                    or self._registry.find_project_id_by_key(record.project_key),
                    project_name=record.project_name,
                    cwd=record.cwd,
                    agent_name=record.agent_name,
                    created_at=record.created_at,
                    call_count=record.call_count,
                    error_count=record.error_count,
                    server_names=sorted(record.server_names),
                    last_activity_at=record.last_activity_at,
                    trace_status=trace_status,
                    warnings=warnings,
                )
            )
        return summaries

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

        database_payload_metadata = (
            self._database_payloads.metadata_for_calls(
                [call.id for call in calls if call.tool_name in DATABASE_PAYLOAD_TOOL_NAMES]
            )
            if self._database_payloads is not None
            else {}
        )

        artifacts_by_call: dict[int, list[McpTraceArtifact]] = {}
        document_call_ids = {call.id for call in calls if call.tool_name == "read_context_document"}
        unlinked_document_read_count = 0
        for read_call in document_reads:
            if read_call.tool_call_id not in document_call_ids:
                unlinked_document_read_count += 1
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
        database_call_tools = {call.id: call.tool_name for call in calls}
        unlinked_database_call_count = 0
        for database_call in database_calls:
            expected_tool = (
                "search_database_objects"
                if database_call.operation == "search_objects"
                else "execute_database_query"
            )
            if database_call_tools.get(database_call.tool_call_id) != expected_tool:
                unlinked_database_call_count += 1
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

        trace_calls: list[McpTraceCall] = []
        for sequence, call in enumerate(calls, start=1):
            payload_metadata = database_payload_metadata.get(call.id)
            trace_calls.append(
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
                    database_payload_available=(
                        payload_metadata is not None
                        and payload_metadata.response_status != "expired"
                    ),
                    database_payload_status=(
                        payload_metadata.response_status if payload_metadata is not None else None
                    ),
                    database_payload_reason=None,
                )
            )
        error_count = sum(1 for call in calls if call.status == "error")
        trace_status, warnings = _trace_completeness(
            call_count=len(calls),
            prepare_call_count=sum(1 for call in calls if call.tool_name == "prepare_task_context"),
            running_call_count=sum(1 for call in calls if call.status == "running"),
            legacy_call_count=sum(1 for call in calls if call.source == "legacy"),
            interrupted_call_count=sum(
                1 for call in calls if call.error_code == "server_restarted"
            ),
            unlinked_document_read_count=unlinked_document_read_count,
            unlinked_database_call_count=unlinked_database_call_count,
        )
        last_activity_at = max(
            (call.finished_at or call.started_at for call in calls),
            default=task.created_at,
        )
        return McpTraceDetail(
            task_id=task.id,
            task=task.task,
            project_id=task.project_id or self._registry.find_project_id_by_key(task.project_key),
            project_name=task.project_name,
            cwd=task.cwd,
            agent_name=task.agent_name,
            created_at=task.created_at,
            call_count=len(calls),
            error_count=error_count,
            server_names=sorted({call.server_name for call in calls}),
            last_activity_at=last_activity_at,
            trace_status=trace_status,
            warnings=warnings,
            calls=trace_calls,
        )

    def get_database_payload(
        self,
        *,
        task_id: int,
        tool_call_id: int,
    ) -> McpDatabaseToolPayloadDetail:
        try:
            self._tasks.get_task(task_id)
            calls = self._tool_calls.list_calls(task_id)
        except (TaskRepositoryError, McpToolCallRepositoryError) as exc:
            raise McpTraceServiceError(str(exc)) from exc
        call = next((item for item in calls if item.id == tool_call_id), None)
        if call is None:
            raise McpTraceServiceError("这个 MCP 工具调用不属于指定任务")
        if call.tool_name not in DATABASE_PAYLOAD_TOOL_NAMES:
            raise McpTraceServiceError("只有数据库 MCP 工具调用支持出入参详情")

        record = None
        if self._database_payloads is not None:
            try:
                record = self._database_payloads.get_payload(tool_call_id)
            except DatabaseToolPayloadServiceError as exc:
                raise McpTraceServiceError(str(exc)) from exc
        if record is None:
            return McpDatabaseToolPayloadDetail(
                task_id=task_id,
                tool_call_id=tool_call_id,
                tool_name=call.tool_name,
                available=False,
                reason="not_captured",
            )

        available = record.response_status != "expired" and (
            record.request_payload is not None or record.response_payload is not None
        )
        reason = None
        if record.response_status == "expired":
            reason = "expired"
        elif record.response_status == "capture_failed":
            reason = "capture_failed"
        elif not available:
            reason = "not_captured"
        return McpDatabaseToolPayloadDetail(
            task_id=task_id,
            tool_call_id=tool_call_id,
            tool_name=call.tool_name,
            available=available,
            reason=reason,
            status=record.response_status,
            request_payload=record.request_payload,
            response_payload=record.response_payload,
            request_bytes=record.request_bytes,
            response_bytes=record.response_bytes,
            request_truncated=record.request_truncated,
            response_truncated=record.response_truncated,
            capture_error_code=record.capture_error_code,
            expires_at=record.expires_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


def _trace_completeness(
    *,
    call_count: int,
    prepare_call_count: int,
    running_call_count: int,
    legacy_call_count: int,
    interrupted_call_count: int,
    unlinked_document_read_count: int,
    unlinked_database_call_count: int,
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if call_count == 0:
        warnings.append("no_trace_calls")
    if prepare_call_count == 0:
        warnings.append("missing_prepare_call")
    if running_call_count:
        warnings.append("running_calls")
    if legacy_call_count:
        warnings.append("legacy_calls")
    if interrupted_call_count:
        warnings.append("interrupted_calls")
    if unlinked_document_read_count:
        warnings.append("unlinked_document_reads")
    if unlinked_database_call_count:
        warnings.append("unlinked_database_calls")

    if running_call_count:
        return "running", warnings
    if warnings:
        return "partial", warnings
    return "complete", warnings
