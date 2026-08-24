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
    source_keys: dict[str, str | int | float | bool | None] | None = None
    page: int = Field(default=1, ge=1, le=100_000)
    ai_query_record_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("keyword")
    @classmethod
    def strip_keyword(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("关键词不能为空")
        return normalized

    @field_validator("source_keys")
    @classmethod
    def validate_source_keys(
        cls,
        value: dict[str, str | int | float | bool | None] | None,
    ) -> dict[str, str | int | float | bool | None] | None:
        if value is None:
            return None
        if len(value) > 64:
            raise ValueError("起点记录关联键过多")
        if any(not key or len(key) > 255 for key in value):
            raise ValueError("起点记录关联键名称无效")
        if any(isinstance(item, str) and len(item) > 1000 for item in value.values()):
            raise ValueError("起点记录关联键值过长")
        return value


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
    kind: Literal["source", "related"] = "related"
    edge_id: str
    relation_id: str
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "unknown"]
    source_column: str
    target: RelationRecordTable
    target_column: str
    matched_columns: list[str] = Field(default_factory=list)
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
    source_keys: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    cards: list[RelationRecordCard] = Field(default_factory=list)
