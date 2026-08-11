from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

NacosProfileKey = Literal["default", "test", "uat"]
_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_FIELD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class NacosConfigSourceRule(BaseModel):
    data_id: str = Field(min_length=1, max_length=255)
    group: str = Field(default="DEFAULT_GROUP", min_length=1, max_length=255)

    @field_validator("data_id", "group")
    @classmethod
    def normalize_source_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(character in normalized for character in "\r\n\0"):
            raise ValueError("Nacos dataId 和 group 必须是单行非空文本")
        return normalized


class NacosFieldRule(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=16)
    secret: bool = False

    @field_validator("paths")
    @classmethod
    def validate_paths(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            path = value.strip()
            if not path or len(path) > 500 or any(character in path for character in "\r\n\0"):
                raise ValueError("提取路径必须是长度不超过 500 的单行非空文本")
            normalized.append(path)
        if len(set(normalized)) != len(normalized):
            raise ValueError("同一字段的提取路径不能重复")
        return normalized


class NacosComponentRule(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=64)
    sources: list[NacosConfigSourceRule] = Field(min_length=1, max_length=10)
    fields: dict[str, NacosFieldRule] = Field(min_length=1, max_length=64)

    @field_validator("id", "type")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _IDENTIFIER_PATTERN.fullmatch(normalized):
            raise ValueError("组件 ID 和类型必须以小写字母开头且只包含字母、数字、_、-")
        return normalized

    @field_validator("fields")
    @classmethod
    def validate_field_names(
        cls,
        values: dict[str, NacosFieldRule],
    ) -> dict[str, NacosFieldRule]:
        normalized: dict[str, NacosFieldRule] = {}
        for name, rule in values.items():
            field_name = name.strip()
            if not _FIELD_PATTERN.fullmatch(field_name):
                raise ValueError("字段名必须以字母开头且只包含字母、数字、_、-")
            if field_name in normalized:
                raise ValueError("组件字段名不能重复")
            normalized[field_name] = rule
        return normalized

    @model_validator(mode="after")
    def validate_unique_sources(self) -> NacosComponentRule:
        keys = [(source.data_id, source.group) for source in self.sources]
        if len(keys) != len(set(keys)):
            raise ValueError("同一组件不能重复声明相同的 dataId 和 group")
        return self


class NacosProfileUpdate(BaseModel):
    base_url: str = Field(min_length=1, max_length=2000)
    namespace_id: str = Field(min_length=1, max_length=255)
    username: str = Field(default="", max_length=255)
    password: str = Field(default="", max_length=2000)
    request_timeout_ms: int = Field(default=10_000, ge=500, le=30_000)
    components: list[NacosComponentRule] = Field(min_length=1, max_length=64)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Nacos 地址必须是无凭据、无查询参数的 HTTP(S) URL")
        return normalized

    @field_validator("namespace_id", "username")
    @classmethod
    def normalize_single_line(cls, value: str) -> str:
        normalized = value.strip()
        if any(character in normalized for character in "\r\n\0"):
            raise ValueError("Nacos namespace 和用户名必须是单行文本")
        return normalized

    @model_validator(mode="after")
    def validate_component_ids(self) -> NacosProfileUpdate:
        component_ids = [component.id for component in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("同一个 Nacos profile 的组件 ID 不能重复")
        return self


class NacosProfileSummary(BaseModel):
    workspace_id: str
    profile_key: NacosProfileKey
    base_url: str
    namespace_id: str
    username: str
    password_configured: bool
    request_timeout_ms: int
    components: list[NacosComponentRule]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkspaceNacosProfiles(BaseModel):
    workspace_id: str
    profiles: list[NacosProfileSummary] = Field(default_factory=list)


class MiddlewareSourceContext(BaseModel):
    data_id: str
    group: str
    md5: str | None = None
    modified_at: str | None = None


class MiddlewareComponentContext(BaseModel):
    id: str
    type: str
    properties: dict[str, Any]
    missing_fields: list[str] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    sources: list[MiddlewareSourceContext] = Field(default_factory=list)


class ReadMiddlewareContextResult(BaseModel):
    task_id: int
    profile_key: NacosProfileKey
    environment: Literal["test", "uat"] | None = None
    provider: Literal["nacos"] = "nacos"
    fetched_at: datetime
    secrets_revealed: bool
    components: list[MiddlewareComponentContext] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
