from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    "not_captured",
    "expired",
    "capture_failed",
]


TraceAttributeValue = str | int | float | bool | None


class McpCallTraceContext(BaseModel):
    """Optional caller correlation metadata shared by all traced MCP workflows."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    run_id: str = Field(
        min_length=1,
        max_length=128,
        description="Stable caller-defined identifier shared by one external workflow run.",
    )
    item_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Optional caller-defined work item identifier within the run.",
    )
    step_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Optional caller-defined step identifier within the item.",
    )
    attempt: int = Field(
        default=1,
        ge=1,
        le=1000,
        description="One-based attempt number for the same logical step.",
    )
    attributes: dict[str, TraceAttributeValue] = Field(
        default_factory=dict,
        max_length=16,
        description="Bounded scalar correlation metadata. Never include secrets or payloads.",
    )

    @field_validator("run_id", "item_id", "step_id")
    @classmethod
    def strip_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("trace_context identifier must not be blank")
        return normalized

    @field_validator("attributes")
    @classmethod
    def validate_attributes(
        cls, value: dict[str, TraceAttributeValue]
    ) -> dict[str, TraceAttributeValue]:
        normalized: dict[str, TraceAttributeValue] = {}
        for key, item in value.items():
            normalized_key = key.strip()
            if not normalized_key or len(normalized_key) > 64:
                raise ValueError("trace_context attribute key must be 1 to 64 characters")
            if normalized_key in normalized:
                raise ValueError("trace_context attribute keys must remain unique after trimming")
            if isinstance(item, str) and len(item) > 256:
                raise ValueError("trace_context string attribute must not exceed 256 characters")
            normalized[normalized_key] = item
        return normalized


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
    trace_context: McpCallTraceContext | None = None
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
