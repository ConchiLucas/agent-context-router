from __future__ import annotations

from datetime import datetime

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


class AiDataQueryLatest(BaseModel):
    record: AiDataQueryRecord | None = None


class AiDataQueryHistory(BaseModel):
    items: list[AiDataQueryRecord]
