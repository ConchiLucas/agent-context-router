from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ProjectKind = Literal["frontend", "backend"]


def _normalize_relative_path(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("项目相对路径不能为空")
    if "\\" in normalized:
        raise ValueError("项目相对路径必须使用 / 分隔")
    if normalized.startswith("~"):
        raise ValueError("项目相对路径不能使用 ~")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        raise ValueError("项目相对路径不能是绝对路径")
    if ".." in path.parts:
        raise ValueError("项目相对路径不能包含 ..")
    rendered = path.as_posix()
    return "." if rendered in {"", "."} else rendered.removeprefix("./")


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    workspace_type: str = Field(default="公司项目", min_length=1, max_length=60)
    root_path: str = Field(min_length=1)
    enabled: bool = True


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    workspace_type: str = Field(default="公司项目", min_length=1, max_length=60)
    root_path: str = Field(min_length=1)


class WorkspaceEnabledUpdate(BaseModel):
    enabled: bool


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    workspace_type: str
    root_path: str
    enabled: bool
    project_count: int = 0
    frontend_project_count: int = 0
    backend_project_count: int = 0
    error_project_count: int = 0
    data_source_count: int = 0
    database_count: int = 0
    database_authorization_count: int = 0
    created_at: datetime
    updated_at: datetime


class WorkspaceProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_kind: ProjectKind = "backend"
    relative_path: str = Field(default=".", min_length=1)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _normalize_relative_path(value)


class WorkspaceProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_kind: ProjectKind | None = None
    relative_path: str = Field(min_length=1)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _normalize_relative_path(value)


class WorkspaceProjectSummary(BaseModel):
    id: str
    name: str
    workspace_id: str
    workspace_name: str
    workspace_enabled: bool
    project_type: str
    project_kind: ProjectKind = "backend"
    relative_path: str
    agents_path: str
    node_count: int = 0
    data_source_count: int = 0
    database_count: int = 0
    refreshed_at: datetime | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
