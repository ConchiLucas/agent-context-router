from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class McpServiceInfo(BaseModel):
    name: str
    transport: str
    url: str


class McpToolInfo(BaseModel):
    name: str
    description: str


class McpClientConfig(BaseModel):
    client: Literal["codex", "antigravity"]
    title: str
    config_path: str
    project_config_path: str | None = None
    config: str


class McpIntegrationReadiness(BaseModel):
    database_configured: bool
    project_count: int
    ready_for_full_test: bool


class McpIntegrationInfo(BaseModel):
    service: McpServiceInfo
    tools: list[McpToolInfo]
    clients: list[McpClientConfig]
    readiness: McpIntegrationReadiness


class McpIntegrationTestRequest(BaseModel):
    project_id: str = Field(min_length=1)


class McpIntegrationTestStage(BaseModel):
    key: str
    label: str
    status: Literal["passed", "failed", "skipped"]
    detail: str
    duration_ms: int


class McpIntegrationTestResult(BaseModel):
    status: Literal["passed", "failed"]
    project_id: str
    project_name: str | None = None
    task_id: int | None = None
    read_call_id: int | None = None
    started_at: datetime
    finished_at: datetime
    stages: list[McpIntegrationTestStage]
