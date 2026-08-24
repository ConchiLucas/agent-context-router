from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AiLogInvestigationListItem(BaseModel):
    id: str
    workspace_id: str
    workspace_name: str
    source: str
    description: str
    environment: str
    container_id: str
    container_name: str
    image: str
    project_id: str | None = None
    project_name: str | None = None
    project_kind: str | None = None
    severity: str
    error_title: str
    occurred_at: datetime | None = None
    occurrence_count: int
    truncated: bool
    created_at: datetime
    updated_at: datetime


class AiLogInvestigationList(BaseModel):
    items: list[AiLogInvestigationListItem]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    has_more: bool


class AiLogInvestigationDetail(AiLogInvestigationListItem):
    task_id: int | None = None
    error_excerpt: str
    log_line_count: int
    fingerprint: str
