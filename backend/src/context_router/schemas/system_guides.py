from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SystemGuideWrite(BaseModel):
    guide_key: str = Field(min_length=1, max_length=64)
    document: dict[str, Any]
    include_in_prepare: bool = False
    sort_order: int = Field(default=0, ge=0, le=100_000)


class SystemGuideContentWrite(BaseModel):
    document: dict[str, Any]


class SystemGuideSummary(BaseModel):
    id: str
    document_id: str
    guide_key: str
    title: str
    summary: str
    include_in_prepare: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class SystemGuideDetail(SystemGuideSummary):
    document: dict[str, Any]
