from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from context_router.schemas.context import TaskIntentSource, TaskIntentType

AiTaskResultStatus = Literal["investigating", "resolved", "failed"]
AiTaskDisplayStatus = Literal["investigating", "resolved", "failed", "unclosed"]
AiTaskChainStatus = Literal["healthy", "running", "attention", "failed", "unused"]


class AiTaskCodeLocation(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    line: int | None = Field(default=None, ge=1)
    description: str = Field(default="", max_length=1000)


class AiTaskVerificationItem(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    result: str = Field(min_length=1, max_length=2000)
    tool_call_id: int | None = Field(default=None, ge=1)


class AiTaskResultWrite(BaseModel):
    status: AiTaskResultStatus
    summary: str = Field(min_length=1, max_length=4000)
    root_cause: str | None = Field(default=None, max_length=4000)
    code_locations: list[AiTaskCodeLocation] = Field(default_factory=list, max_length=50)
    suggested_actions: list[str] = Field(default_factory=list, max_length=50)
    verification: list[AiTaskVerificationItem] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_terminal_evidence(self) -> AiTaskResultWrite:
        if self.status == "resolved" and not self.verification:
            raise ValueError("resolved 任务必须至少包含一项验证结果")
        if self.status == "failed" and not (self.root_cause or "").strip():
            raise ValueError("failed 任务必须写明无法完成的根因")
        return self


class AiTaskResult(BaseModel):
    task_id: int
    status: AiTaskResultStatus
    summary: str
    root_cause: str | None = None
    code_locations: list[AiTaskCodeLocation] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    verification: list[AiTaskVerificationItem] = Field(default_factory=list)
    source: str
    revision: int
    created_at: datetime
    updated_at: datetime
    finalized_at: datetime | None = None


class AiTaskVisualizationListItem(BaseModel):
    task_id: int
    description: str
    workspace_id: str
    workspace_name: str
    environment: str
    agent_name: str
    intent_type: TaskIntentType
    intent_error_signal: bool = False
    intent_summary: str | None = None
    intent_source: TaskIntentSource
    status: AiTaskDisplayStatus
    created_at: datetime
    last_activity_at: datetime
    tool_call_count: int
    tool_error_count: int
    running_call_count: int
    data_query_count: int
    interface_success_count: int
    interface_failed_count: int
    error_event_count: int


class AiTaskVisualizationList(BaseModel):
    items: list[AiTaskVisualizationListItem]
    limit: int
    has_more: bool
    next_cursor: str | None = None


class AiTaskRelatedArtifacts(BaseModel):
    mcp_trace: bool
    data_visualization: bool
    interface_visualization: bool
    log_visualization: bool


class AiTaskChainHealthItem(BaseModel):
    key: Literal["mcp", "data", "interface", "log", "conclusion"]
    label: str
    status: AiTaskChainStatus
    summary: str


class AiTaskVisualizationDetail(AiTaskVisualizationListItem):
    cwd: str
    active_project_name: str | None = None
    result: AiTaskResult | None = None
    related: AiTaskRelatedArtifacts
    chain_health: list[AiTaskChainHealthItem]


class AiTaskTimelineEvent(BaseModel):
    event_id: str
    event_type: Literal[
        "mcp_call",
        "data_query",
        "interface_request",
        "log_investigation",
        "task_result",
    ]
    title: str
    status: str
    occurred_at: datetime
    summary: str
    artifact_type: Literal["mcp", "data", "interface", "log", "result"]
    artifact_id: str


class AiTaskTimeline(BaseModel):
    task_id: int
    items: list[AiTaskTimelineEvent]
    limit: int
    has_more: bool
    next_cursor: str | None = None
