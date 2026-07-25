from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from context_router.schemas.context import ContextReadHistoryItem

McpTraceSource = Literal["server", "legacy"]
McpTraceStatus = Literal["running", "ok", "error", "cancelled"]
McpTraceCompleteness = Literal["complete", "running", "partial"]
McpDatabasePayloadStatus = Literal[
    "pending",
    "ok",
    "error",
    "cancelled",
    "interrupted",
    "capture_failed",
    "expired",
]
McpDatabasePayloadUnavailableReason = Literal[
    "capture_disabled",
    "not_captured",
    "expired",
    "capture_failed",
]


class McpTraceSummary(BaseModel):
    task_id: int
    task: str
    project_id: str | None = None
    project_name: str
    cwd: str
    agent_name: str | None = None
    created_at: datetime
    call_count: int
    error_count: int
    server_names: list[str] = Field(default_factory=list)
    last_activity_at: datetime
    trace_status: McpTraceCompleteness = "complete"
    warnings: list[str] = Field(default_factory=list)


class McpTraceDocumentReadArtifact(BaseModel):
    kind: Literal["document_read"] = "document_read"
    read_call_id: int
    documents: list[ContextReadHistoryItem]


class McpTraceDatabaseCallArtifact(BaseModel):
    kind: Literal["database_call"] = "database_call"
    database_call_id: int
    operation: str
    database: str
    engine: str
    status: str
    object_type: str | None = None
    statement_type: str | None = None
    duration_ms: int | None = None
    returned_count: int | None = None
    result_bytes: int | None = None
    truncated: bool | None = None
    error_code: str | None = None


McpTraceArtifact = McpTraceDocumentReadArtifact | McpTraceDatabaseCallArtifact


class McpTraceCall(BaseModel):
    tool_call_id: int
    sequence: int
    parent_tool_call_id: int | None = None
    server_name: str
    tool_name: str
    source: McpTraceSource
    status: McpTraceStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    request_summary: dict[str, object] | None = None
    result_summary: dict[str, object] | None = None
    error_code: str | None = None
    artifacts: list[McpTraceArtifact] = Field(default_factory=list)
    database_payload_available: bool = False
    database_payload_status: McpDatabasePayloadStatus | None = None
    database_payload_reason: McpDatabasePayloadUnavailableReason | None = None


class McpTraceDetail(McpTraceSummary):
    calls: list[McpTraceCall] = Field(default_factory=list)


class McpDatabaseToolPayloadDetail(BaseModel):
    task_id: int
    tool_call_id: int
    tool_name: Literal["search_database_objects", "execute_database_query"]
    available: bool
    reason: McpDatabasePayloadUnavailableReason | None = None
    status: McpDatabasePayloadStatus | None = None
    request_payload: dict[str, object] | None = None
    response_payload: dict[str, object] | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    request_truncated: bool = False
    response_truncated: bool = False
    capture_error_code: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
