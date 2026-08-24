from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ValueMappingBindingWrite(BaseModel):
    interface_id: str = Field(min_length=1, max_length=36)
    location: Literal["path", "query", "body"]
    parameter_path: str = Field(min_length=1, max_length=240)
    required: bool = False

    @field_validator("parameter_path")
    @classmethod
    def normalize_parameter_path(cls, value: str) -> str:
        normalized = value.strip().strip(".")
        if not normalized or any(part in {"", ".."} for part in normalized.split(".")):
            raise ValueError("参数路径格式无效")
        return normalized


class ValueMappingWrite(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=36)
    value_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2_000)
    status: Literal["draft", "published"] = "draft"
    database_alias: str = Field(min_length=1, max_length=64)
    schema_name: str | None = Field(default=None, max_length=128)
    table_name: str = Field(min_length=1, max_length=128)
    value_column: str = Field(min_length=1, max_length=128)
    search_columns: list[str] = Field(default_factory=list, max_length=12)
    display_columns: list[str] = Field(default_factory=list, max_length=8)
    filters: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    bindings: list[ValueMappingBindingWrite] = Field(default_factory=list, max_length=200)

    @field_validator(
        "name",
        "database_alias",
        "table_name",
        "value_column",
        mode="before",
    )
    @classmethod
    def strip_required_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def strip_description(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("schema_name", mode="before")
    @classmethod
    def normalize_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("search_columns", "display_columns", "aliases", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = str(item).strip()
            key = normalized.casefold()
            if normalized and key not in seen:
                seen.add(key)
                result.append(normalized)
        return result


class ValueMappingPreviewRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=36)
    environment: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_-]{0,31}$",
    )
    keyword: str = Field(default="", max_length=240)
    limit: int = Field(default=10, ge=1, le=20, strict=True)


class ValueMappingInterfaceSearch(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=36)
    keyword: str = Field(default="", max_length=240)
    limit: int = Field(default=30, ge=1, le=100, strict=True)
