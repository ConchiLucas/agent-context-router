from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from context_router.schemas.context import ContextReadHistoryItem

McpTraceSource = Literal["server", "gateway", "reported", "legacy"]
McpTraceStatus = Literal["running", "ok", "error", "cancelled"]


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


class McpTraceDetail(McpTraceSummary):
    calls: list[McpTraceCall] = Field(default_factory=list)
