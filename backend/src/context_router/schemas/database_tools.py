from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DatabaseObjectType = Literal["schema", "table", "view", "column", "index"]
DatabaseObjectDetail = Literal["names", "summary", "full"]


class SearchDatabaseObjectsInput(BaseModel):
    task_id: int = Field(ge=1)
    database: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    object_type: DatabaseObjectType
    pattern: str = Field(default="*", min_length=1, max_length=255)
    detail: DatabaseObjectDetail = "names"
    schema: str | None = Field(default=None, max_length=255)
    table: str | None = Field(default=None, max_length=255)
    limit: int = Field(default=100, ge=1, le=500)


class DatabaseObjectResult(BaseModel):
    name: str
    kind: str
    database: str | None = None
    schema: str | None = None
    table: str | None = None
    comment: str | None = None
    column_count: int | None = None
    estimated_rows: int | None = None
    estimated_bytes: int | None = None
    metadata: dict[str, Any] | None = None


class SearchDatabaseObjectsResult(BaseModel):
    task_id: int
    database: str
    engine: str
    object_type: DatabaseObjectType
    detail: DatabaseObjectDetail
    objects: list[DatabaseObjectResult]
    returned_count: int
    truncated: bool
    truncation_reason: str | None = None
    elapsed_ms: int
    result_bytes: int


class ExecuteDatabaseQueryInput(BaseModel):
    task_id: int = Field(ge=1)
    database: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    sql: str = Field(min_length=1, max_length=200_000)


class DatabaseQueryColumn(BaseModel):
    name: str
    type: str


class ExecuteDatabaseQueryResult(BaseModel):
    task_id: int
    database: str
    engine: str
    columns: list[DatabaseQueryColumn]
    rows: list[list[Any]]
    returned_rows: int
    truncated: bool
    truncation_reason: str | None = None
    elapsed_ms: int
    result_bytes: int
