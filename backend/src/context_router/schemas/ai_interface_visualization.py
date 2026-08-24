from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AiInterfaceRequestListItem(BaseModel):
    id: str
    workspace_id: str
    workspace_name: str
    source: str
    description: str
    interface_id: str
    interface_name: str
    service_name: str
    method: str
    path: str
    environment: str
    address_name: str | None = None
    login_account: str | None = None
    role_name: str | None = None
    request_preview: str
    status_code: int | None = None
    success: bool
    duration_ms: int
    response_bytes: int
    response_truncated: bool
    created_at: datetime


class AiInterfaceRequestList(BaseModel):
    items: list[AiInterfaceRequestListItem]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    has_more: bool
    next_cursor: str | None = None


class AiInterfaceRequestDetail(AiInterfaceRequestListItem):
    task_id: int | None = None
    tool_call_id: int | None = None
    plan_id: str | None = None
    request_sha256: str | None = None
    request: Any
    response: Any
    parameter_evidence: dict[str, Any]
