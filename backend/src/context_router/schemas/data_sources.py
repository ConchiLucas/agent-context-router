from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DatabaseEngine = Literal[
    "mysql",
    "mariadb",
    "postgresql",
    "sqlserver",
    "sqlite",
    "oracle",
    "clickhouse",
]


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="本机电脑", min_length=1, max_length=60)
    engine: DatabaseEngine
    description: str = Field(default="", max_length=500)
    connection_config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class DataSourceUpdate(DataSourceCreate):
    pass


class DataSourceSummary(BaseModel):
    id: str
    name: str
    category: str
    engine: DatabaseEngine
    description: str
    connection_config: dict[str, Any]
    enabled: bool
    config_version: int
    database_count: int
    project_count: int
    created_at: datetime
    updated_at: datetime


class DataSourcePasswordReveal(BaseModel):
    password: str


class DataSourceEngineCapability(BaseModel):
    engine: DatabaseEngine
    configurable: bool
    discoverable: bool
    searchable: bool
    queryable: bool


class DataSourceConnectionTestResult(BaseModel):
    engine: DatabaseEngine
    status: Literal["passed", "failed"]
    duration_ms: int
    error_code: str | None = None
    message: str


class DataSourceDatabaseCreate(BaseModel):
    remote_name: str = Field(min_length=1, max_length=255)
    display_name: str = Field(default="", max_length=255)
    namespace_type: Literal["database", "schema", "file"] = "database"
    available: bool = True
    system_database: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataSourceDatabaseUpdate(DataSourceDatabaseCreate):
    pass


class DataSourceDatabaseSummary(BaseModel):
    id: str
    data_source_id: str
    remote_name: str
    display_name: str
    namespace_type: Literal["database", "schema", "file"]
    available: bool
    system_database: bool
    metadata: dict[str, Any]
    project_count: int
    created_at: datetime
    updated_at: datetime


class DataSourceDatabaseSyncResult(BaseModel):
    discovered_count: int
    created_count: int
    unavailable_count: int
    databases: list[DataSourceDatabaseSummary]


class ProjectDatabaseLinkCreate(BaseModel):
    project_id: str = Field(min_length=1, max_length=32)
    alias: str = Field(default="", max_length=120)
    mcp_alias: str | None = Field(default=None, min_length=1, max_length=64)
    purpose: str = Field(default="", max_length=500)
    enabled: bool = True
    readonly: bool = True
    allowed_schemas: list[str] = Field(default_factory=list)
    max_rows: int = Field(default=1000, ge=1, le=100_000)
    max_result_bytes: int = Field(default=2_000_000, ge=1_024, le=100_000_000)
    query_timeout_ms: int = Field(default=15_000, ge=100, le=300_000)

    @field_validator("mcp_alias")
    @classmethod
    def validate_mcp_alias(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("MCP 别名不能为空")
        if not normalized[0].isalpha() or not normalized[0].isascii():
            raise ValueError("MCP 别名必须以小写英文字母开头")
        if normalized.lower() != normalized or any(
            not (character.isascii() and (character.isalnum() or character in "_-"))
            for character in normalized
        ):
            raise ValueError("MCP 别名只能包含小写英文字母、数字、下划线和连字符")
        return normalized


class ProjectDatabaseLinkUpdate(ProjectDatabaseLinkCreate):
    pass


class ProjectDatabaseAliasUpdate(BaseModel):
    mcp_alias: str = Field(min_length=1, max_length=64)

    @field_validator("mcp_alias")
    @classmethod
    def validate_mcp_alias(cls, value: str) -> str:
        return ProjectDatabaseLinkCreate.validate_mcp_alias(value)  # type: ignore[return-value]


class ProjectDatabaseLinkSummary(BaseModel):
    id: str
    project_id: str
    project_name: str
    database_id: str
    database_name: str
    data_source_id: str
    data_source_name: str
    engine: DatabaseEngine
    alias: str
    mcp_alias: str | None
    purpose: str
    enabled: bool
    readonly: bool
    allowed_schemas: list[str]
    max_rows: int
    max_result_bytes: int
    query_timeout_ms: int
    created_at: datetime
    updated_at: datetime


class ProjectDatabaseSelectionUpdate(BaseModel):
    database_ids: list[str] = Field(default_factory=list, max_length=5000)
    mcp_aliases: dict[str, str] = Field(default_factory=dict, max_length=5000)

    @field_validator("mcp_aliases")
    @classmethod
    def validate_mcp_aliases(cls, values: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        used: set[str] = set()
        for database_id, value in values.items():
            alias = ProjectDatabaseAliasUpdate(mcp_alias=value).mcp_alias
            key = alias.casefold()
            if key in used:
                raise ValueError("同一项目内的 MCP 数据库别名不能重复")
            normalized[database_id] = alias
            used.add(key)
        return normalized


class ProjectDatabaseOption(BaseModel):
    id: str
    remote_name: str
    display_name: str
    namespace_type: Literal["database", "schema", "file"]
    available: bool
    selected: bool
    link_id: str | None = None
    mcp_alias: str | None = None


class ProjectDataSourceOption(BaseModel):
    id: str
    name: str
    category: str
    engine: DatabaseEngine
    enabled: bool
    databases: list[ProjectDatabaseOption]


class ProjectDataSourceOptions(BaseModel):
    project_id: str
    project_name: str
    selected_source_count: int
    selected_database_count: int
    sources: list[ProjectDataSourceOption]
