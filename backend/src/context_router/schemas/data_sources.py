from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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
    purpose: str = Field(default="", max_length=500)
    enabled: bool = True
    readonly: bool = True
    allowed_schemas: list[str] = Field(default_factory=list)
    max_rows: int = Field(default=1000, ge=1, le=100_000)
    max_result_bytes: int = Field(default=2_000_000, ge=1_024, le=100_000_000)
    query_timeout_ms: int = Field(default=15_000, ge=100, le=300_000)


class ProjectDatabaseLinkUpdate(ProjectDatabaseLinkCreate):
    pass


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


class ProjectDatabaseOption(BaseModel):
    id: str
    remote_name: str
    display_name: str
    namespace_type: Literal["database", "schema", "file"]
    available: bool
    selected: bool
    link_id: str | None = None


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
