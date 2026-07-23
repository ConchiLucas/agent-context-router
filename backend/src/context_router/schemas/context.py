from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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


class PreparedDatabase(BaseModel):
    database: str
    engine: str
    name: str
    purpose: str
    readonly: bool = True
    capabilities: list[str] = Field(default_factory=list)


class PrepareTaskContextResult(BaseModel):
    task_id: int
    project: PreparedProject
    documents: ContextDocumentNode
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


class ContextTaskSummary(BaseModel):
    task_id: int
    task: str
    cwd: str
    agent_name: str | None = None
    created_at: datetime
    read_call_count: int


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
    project_name: str
    agent_name: str | None = None
    created_at: datetime
    calls: list[ContextReadHistoryCall]
    database_calls: list[ContextDatabaseCallHistoryItem] = Field(default_factory=list)
