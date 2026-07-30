from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from context_router.schemas.projects import ProjectSummary

RuntimeMode = Literal["fast", "full"]
RuntimeRunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class RuntimeConfigFileDraft(BaseModel):
    relative_path: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=1_000_000)
    executable: bool = False

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or normalized.startswith("/")
            or normalized.endswith("/")
            or "\\" in normalized
            or "\x00" in normalized
        ):
            raise ValueError("文件路径必须是有效的 POSIX 相对路径")
        path = PurePosixPath(normalized)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("文件路径不能包含空目录、点目录或上级目录")
        return path.as_posix()


class RuntimeConfigModeUpdate(BaseModel):
    files: list[RuntimeConfigFileDraft] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_unique_paths(self) -> Self:
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("同一种更新模式下不能保存重复文件路径")
        return self


class RuntimeConfigFile(RuntimeConfigFileDraft):
    id: str
    created_at: datetime
    updated_at: datetime


class RuntimeConfigMode(BaseModel):
    mode: RuntimeMode
    files: list[RuntimeConfigFile]
    updated_at: datetime | None = None


class ProjectRuntimeConfig(BaseModel):
    project: ProjectSummary
    fast: RuntimeConfigMode
    full: RuntimeConfigMode


class RuntimeMaterializationResult(BaseModel):
    snapshot_id: str
    project_id: str
    mode: RuntimeMode
    materialized_path: str
    file_count: int
    total_bytes: int
    manifest_sha256: str
    created_at: datetime


class RuntimeRunSummary(BaseModel):
    id: str
    project_id: str
    mode: RuntimeMode
    trigger: Literal["ui", "mcp"]
    status: RuntimeRunStatus
    snapshot_id: str
    materialized_path: str
    project_root: str
    entry_file: str
    changed_files: list[str]
    decision_reason: str
    exit_code: int | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RuntimeRunLog(BaseModel):
    run_id: str
    status: RuntimeRunStatus
    content: str
    truncated: bool
