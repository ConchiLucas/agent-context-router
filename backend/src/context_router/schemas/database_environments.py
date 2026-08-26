from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DatabaseEnvironment = str
DatabaseEnvironmentMappingStatus = Literal["complete", "incomplete", "invalid", "suggested"]


class WorkspaceEnvironmentOption(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    is_default: bool
    sort_order: int


class WorkspaceEnvironmentList(BaseModel):
    workspace_id: str
    default_environment: str = "local"
    environments: list[WorkspaceEnvironmentOption] = Field(default_factory=list)


class WorkspaceEnvironmentUpsert(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    aliases: list[str] | None = Field(default=None, max_length=20)
    sort_order: int = Field(default=100, ge=-10000, le=10000)

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            alias = value.strip()
            if not alias:
                continue
            if len(alias) > 80:
                raise ValueError("环境别名不能超过 80 个字符")
            folded = alias.casefold()
            if folded not in seen:
                seen.add(folded)
                normalized.append(alias)
        return normalized


class WorkspaceEnvironmentDatabaseTargetUpdate(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=32)
    project_id: str = Field(min_length=1, max_length=32)
    logical_name: str = Field(min_length=1, max_length=120)
    mcp_alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    link_id: str = Field(min_length=1, max_length=32)

    @field_validator("logical_name", "mcp_alias")
    @classmethod
    def strip_target_text(cls, value: str) -> str:
        return value.strip()


class WorkspaceEnvironmentDatabaseTargetsUpdate(BaseModel):
    targets: list[WorkspaceEnvironmentDatabaseTargetUpdate] = Field(
        default_factory=list,
        max_length=5000,
    )


class DatabaseEnvironmentTargetSummary(BaseModel):
    link_id: str
    database_id: str
    database_name: str
    database_display_name: str
    data_source_id: str
    data_source_name: str
    engine: str
    namespace_type: str
    mcp_alias: str | None = None
    available: bool
    readonly: bool
    system_database: bool


class DatabaseEnvironmentTargetPair(BaseModel):
    test: DatabaseEnvironmentTargetSummary | None = None
    uat: DatabaseEnvironmentTargetSummary | None = None


class DatabaseEnvironmentMappingSummary(BaseModel):
    id: str | None = None
    logical_name: str
    mcp_alias: str
    status: DatabaseEnvironmentMappingStatus
    targets: DatabaseEnvironmentTargetPair
    suggested_targets: DatabaseEnvironmentTargetPair
    issues: list[str] = Field(default_factory=list)


class DatabaseEnvironmentCandidates(BaseModel):
    test: list[DatabaseEnvironmentTargetSummary] = Field(default_factory=list)
    uat: list[DatabaseEnvironmentTargetSummary] = Field(default_factory=list)


class ProjectDatabaseEnvironmentMappings(BaseModel):
    project_id: str
    project_name: str
    project_kind: Literal["backend"]
    mappings: list[DatabaseEnvironmentMappingSummary] = Field(default_factory=list)
    candidates: DatabaseEnvironmentCandidates


class DatabaseEnvironmentMappingCounts(BaseModel):
    mapping_count: int
    complete_count: int
    issue_count: int


class WorkspaceDatabaseEnvironmentMappings(BaseModel):
    workspace_id: str
    configured: bool
    active_environment: DatabaseEnvironment | None = None
    revision: int = Field(ge=0)
    summary: DatabaseEnvironmentMappingCounts
    projects: list[ProjectDatabaseEnvironmentMappings] = Field(default_factory=list)


class DatabaseEnvironmentTargetUpdate(BaseModel):
    test: str | None = Field(default=None, min_length=1, max_length=32)
    uat: str | None = Field(default=None, min_length=1, max_length=32)


class DatabaseEnvironmentMappingUpdate(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=32)
    project_id: str = Field(min_length=1, max_length=32)
    logical_name: str = Field(min_length=1, max_length=120)
    mcp_alias: str = Field(min_length=1, max_length=64)
    targets: DatabaseEnvironmentTargetUpdate

    @field_validator("logical_name", "mcp_alias")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("mcp_alias")
    @classmethod
    def validate_mcp_alias(cls, value: str) -> str:
        if not value:
            raise ValueError("MCP 别名不能为空")
        if not value[0].isascii() or not value[0].isalpha() or value.lower() != value:
            raise ValueError("MCP 别名必须以小写英文字母开头")
        if any(
            not (character.isascii() and (character.isalnum() or character in "_-"))
            for character in value
        ):
            raise ValueError("MCP 别名只能包含小写英文字母、数字、下划线和连字符")
        return value


class DatabaseEnvironmentMappingsUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    mappings: list[DatabaseEnvironmentMappingUpdate] = Field(
        default_factory=list,
        max_length=5000,
    )

    @field_validator("mappings")
    @classmethod
    def validate_unique_mappings(
        cls,
        mappings: list[DatabaseEnvironmentMappingUpdate],
    ) -> list[DatabaseEnvironmentMappingUpdate]:
        ids: set[str] = set()
        aliases: set[str] = set()
        for mapping in mappings:
            if mapping.id is not None:
                if mapping.id in ids:
                    raise ValueError("环境映射 ID 不能重复")
                ids.add(mapping.id)
            alias = mapping.mcp_alias.casefold()
            if alias in aliases:
                raise ValueError("工作空间内环境映射 MCP 别名不能重复")
            aliases.add(alias)
        return mappings


class DatabaseEnvironmentSwitchUpdate(BaseModel):
    environment: DatabaseEnvironment
    expected_revision: int = Field(ge=1)


class EnvironmentJsonPair(BaseModel):
    test: dict[str, Any]
    uat: dict[str, Any]


class WorkspaceEnvironmentConfig(BaseModel):
    workspace_id: str
    configured: bool
    active_environment: DatabaseEnvironment | None = None
    revision: int = Field(ge=0)
    environments: EnvironmentJsonPair
    active_config: dict[str, Any] | None = None


class WorkspaceEnvironmentConfigUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    environments: EnvironmentJsonPair
