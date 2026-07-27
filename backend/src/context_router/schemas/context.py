from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProjectKind = Literal["frontend", "backend"]
TaskScope = Literal["project", "workspace"]


class ContextDocumentNode(BaseModel):
    document_id: str
    path: str
    title: str | None = None
    summary: str | None = None
    error: str | None = None
    children: list[ContextDocumentNode] = Field(default_factory=list)


class PreparedProject(BaseModel):
    project_id: str
    name: str
    node_count: int
    relative_path: str = "."
    document_relative_path: str = "AGENTS.md"
    project_kind: ProjectKind = "backend"


class PreparedWorkspace(BaseModel):
    workspace_id: str
    name: str


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


class PrepareTaskContextResult(BaseModel):
    task_id: int
    workspace: PreparedWorkspace
    documents: ContextDocumentNode
    projects: list[PreparedProject] = Field(default_factory=list)
    active_project: PreparedProject | None = None
    project: PreparedProject | None = None
    databases: list[PreparedDatabase] = Field(default_factory=list)
    warnings: list[str] | None = None


class ContextDocumentReadRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=64)
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
    agent_name: str | None = None
    created_at: datetime
    calls: list[ContextReadHistoryCall]
    database_calls: list[ContextDatabaseCallHistoryItem] = Field(default_factory=list)
