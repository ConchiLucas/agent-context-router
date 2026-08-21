from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RelationRecordTable(BaseModel):
    database_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    schema_name: str = Field(min_length=1, max_length=255)
    table_name: str = Field(min_length=1, max_length=255)


class RelationRecordSearchInput(BaseModel):
    environment: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    table: RelationRecordTable
    keyword: str = Field(min_length=1, max_length=200)
    edge_id: str | None = Field(default=None, min_length=1, max_length=32)
    page: int = Field(default=1, ge=1, le=100_000)

    @field_validator("keyword")
    @classmethod
    def strip_keyword(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("关键词不能为空")
        return normalized


class RelationRecordColumn(BaseModel):
    name: str
    type: str = ""
    comment: str = ""
    relation_key: bool = False


class RelationRecordPage(BaseModel):
    page: int = 1
    page_size: int = 3
    total_rows: int = 0
    total_pages: int = 0


class RelationRecordCard(BaseModel):
    edge_id: str
    relation_id: str
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "unknown"]
    source_column: str
    target: RelationRecordTable
    target_column: str
    columns: list[RelationRecordColumn] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    page: RelationRecordPage
    matched_key_count: int = 0
    matched_keys_truncated: bool = False
    warning: str | None = None


class RelationRecordSearchResult(BaseModel):
    workspace_id: str
    environment: str
    table: RelationRecordTable
    keyword: str
    scanned_columns: list[str] = Field(default_factory=list)
    cards: list[RelationRecordCard] = Field(default_factory=list)
