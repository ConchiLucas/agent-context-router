from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UsageCardCreate(BaseModel):
    slug: str | None = None
    title: str
    description: str = ""
    content_markdown: str
    sort_order: int | None = None


class UsageCardUpdate(BaseModel):
    title: str
    description: str = ""
    content_markdown: str
    sort_order: int | None = None


class UsageCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    title: str
    description: str
    content_markdown: str
    sort_order: int
    is_builtin: bool
    created_at: datetime
    updated_at: datetime


class UsageCardListResponse(BaseModel):
    cards: list[UsageCardResponse]


class UsageCardDeleteResponse(BaseModel):
    deleted: bool
