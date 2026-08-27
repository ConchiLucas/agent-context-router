from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ProjectKind = Literal["frontend", "backend"]
TaskScope = Literal["project", "workspace"]
DatabaseEnvironment = str
DatabaseEnvironmentSelection = Literal["workspace_default", "task_explicit", "task_description"]
TaskIntentType = Literal[
    "interface_execute",
    "data_query",
    "task_execute",
    "bug_investigate",
    "bug_fix",
]
TaskIntentSource = Literal["agent_declared", "compatibility_default", "system_default"]
TaskMutationPolicy = Literal["allowed", "forbidden"]


class ContextDocumentNode(BaseModel):
    document_id: str
    summary: str
    children: list[ContextDocumentNode] = Field(default_factory=list)


class PreparedDatabaseEnvironment(BaseModel):
    key: DatabaseEnvironment
    name: str
    revision: int = Field(ge=1)
    selection: DatabaseEnvironmentSelection


class PreparedDatabase(BaseModel):
    database: str
    engine: str
    name: str
    purpose: str
    readonly: bool = True
    capabilities: list[str] = Field(default_factory=list)
    project_id: str | None = None
    project_name: str | None = None
    project_kind: ProjectKind | None = None
    environment: DatabaseEnvironment | None = None


class TaskExecutionContract(BaseModel):
    intent_type: TaskIntentType
    error_signal: bool = False
    intent_summary: str | None = None
    intent_source: TaskIntentSource
    mutation_policy: TaskMutationPolicy
    required_steps: list[str] = Field(default_factory=list)
    visualization_targets: list[Literal["task", "data", "interface", "log"]] = Field(
        default_factory=lambda: ["task"]
    )
    instructions: list[str] = Field(default_factory=list)


class PrepareTaskContextResult(BaseModel):
    task_id: int
    environment: PreparedDatabaseEnvironment | None = None
    documents: ContextDocumentNode
    execution_contract: TaskExecutionContract
    access: list[Literal["documents", "database", "environment", "middleware", "runtime"]] = Field(
        default_factory=lambda: [
            "documents",
            "database",
            "environment",
            "middleware",
            "runtime",
        ]
    )
    warnings: list[str] | None = None


class TaskEnvironmentContext(BaseModel):
    configured: bool
    selected: PreparedDatabaseEnvironment | None = None
    config: dict[str, Any] | None = None


class ReadTaskContextResult(BaseModel):
    task_id: int
    databases: list[PreparedDatabase] | None = None
    environment: TaskEnvironmentContext | None = None


class ContextDocumentReadRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=96)
    section: str | None = Field(default=None, max_length=500)


class ContextDocumentReadItemError(BaseModel):
    code: str
    message: str


class ContextDocumentReadItem(BaseModel):
    position: int
    document_id: str
    path: str | None = None
    title: str | None = None
    section: str | None = None
    content: str | None = None
    error: ContextDocumentReadItemError | None = None


class ReadContextDocumentResult(BaseModel):
    task_id: int
    read_call_id: int
    documents: list[ContextDocumentReadItem]


class ContextDocumentSearchSection(BaseModel):
    section: str | None = None
    section_path: list[str] = Field(default_factory=list)
    can_read_section: bool = False


class ContextDocumentSearchResultItem(BaseModel):
    document_id: str
    path: str
    title: str | None = None
    summary: str | None = None
    relevance: float = Field(ge=0, le=1)
    matched_sections: list[ContextDocumentSearchSection] = Field(default_factory=list)
    match_reasons: list[str] = Field(default_factory=list)


class SearchContextDocumentsResult(BaseModel):
    task_id: int
    query: str
    returned_count: int
    truncated: bool
    results: list[ContextDocumentSearchResultItem] = Field(default_factory=list)


class ContextTaskSummary(BaseModel):
    task_id: int
    task: str
    cwd: str
    agent_name: str | None = None
    created_at: datetime
    read_call_count: int
    scope: TaskScope = "project"
    workspace_id: str | None = None
    workspace_name: str | None = None
    active_project_id: str | None = None
    active_project_name: str | None = None
    active_project_kind: ProjectKind | None = None
    database_environment: str | None = None
    database_environment_revision: int | None = None
    database_environment_selection: DatabaseEnvironmentSelection | None = None
    intent_type: TaskIntentType = "task_execute"
    intent_error_signal: bool = False
    intent_summary: str | None = None
    intent_source: TaskIntentSource = "compatibility_default"


class ContextReadHistoryItem(BaseModel):
    position: int
    document_id: str
    path: str | None = None
    section: str | None = None
    status: str
    error_code: str | None = None


class ContextReadHistoryCall(BaseModel):
    read_call_id: int
    created_at: datetime
    documents: list[ContextReadHistoryItem]


class ContextDatabaseCallHistoryItem(BaseModel):
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
    created_at: datetime


class ContextTaskReadHistory(BaseModel):
    task_id: int
    task: str
    project_name: str | None = None
    workspace_id: str | None = None
    workspace_name: str | None = None
    active_project_id: str | None = None
    active_project_name: str | None = None
    active_project_kind: ProjectKind | None = None
    scope: TaskScope = "project"
    database_environment: str | None = None
    database_environment_revision: int | None = None
    database_environment_selection: DatabaseEnvironmentSelection | None = None
    intent_type: TaskIntentType = "task_execute"
    intent_error_signal: bool = False
    intent_summary: str | None = None
    intent_source: TaskIntentSource = "compatibility_default"
    agent_name: str | None = None
    created_at: datetime
    calls: list[ContextReadHistoryCall]
    database_calls: list[ContextDatabaseCallHistoryItem] = Field(default_factory=list)
