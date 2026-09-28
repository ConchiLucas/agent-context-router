from pydantic import BaseModel, Field


class ManagedRule(BaseModel):
    id: str
    slug: str
    title: str
    body: str
    sort_order: int


class ManagedRuleList(BaseModel):
    rules: list[ManagedRule]


class ManagedRuleWrite(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=8000)
