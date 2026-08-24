from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AiDataQueryWrite(BaseModel):
    source: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    description: str = Field(default="", max_length=2000)
    workspace_id: str = Field(min_length=1, max_length=36)
    environment: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    database_key: str = Field(min_length=1, max_length=64)
    schema_name: str = Field(default="", max_length=255)
    table_name: str = Field(min_length=1, max_length=255)
    keyword: str = Field(min_length=1, max_length=500)
    task_id: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class AiDataQueryRecord(BaseModel):
    id: str
    source: str
    description: str
    workspace_id: str
    workspace_name: str
    environment: str
    database_key: str
    schema_name: str
    table_name: str
    keyword: str
    created_at: datetime
    task_id: int | None = None
    execution_status: Literal["pending", "succeeded", "failed"] = "pending"
    executed_at: datetime | None = None
    result_card_count: int | None = None
    result_row_count: int | None = None
    duration_ms: int | None = None
    error_summary: str | None = None


class AiDataQueryLatest(BaseModel):
    record: AiDataQueryRecord | None = None


class AiDataQueryHistory(BaseModel):
    items: list[AiDataQueryRecord]
