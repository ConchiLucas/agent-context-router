from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

RuntimeOperationStatus = Literal[
    "queued", "leased", "running", "succeeded", "failed", "cancelled", "interrupted"
]
RuntimeStepStatus = Literal["queued", "running", "succeeded", "failed", "skipped", "cancelled"]


class WorkspaceRuntimeFileDraft(BaseModel):
    relative_path: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=1_000_000)
    executable: bool = False

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        normalized = value.strip()
        path = PurePosixPath(normalized)
        if (
            not normalized
            or normalized.startswith("/")
            or normalized.endswith("/")
            or "\\" in normalized
            or "\x00" in normalized
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("文件路径必须是安全的 POSIX 相对路径")
        if path.as_posix() == ".env.local":
            raise ValueError("本机 .env.local 不得进入 Context Router")
        return path.as_posix()


class WorkspaceRuntimeConfigUpdate(BaseModel):
    files: list[WorkspaceRuntimeFileDraft] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_files(self) -> Self:
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("运行配置不能包含重复文件路径")
        entry = next((item for item in self.files if item.relative_path == "deploy.sh"), None)
        if entry is None or not entry.executable:
            raise ValueError("start 配置必须包含可执行的 deploy.sh")
        return self


class WorkspaceRuntimePolicyUpdate(BaseModel):
    project_order: list[str] = Field(default_factory=list, max_length=500)
    workspace_paths: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if len(self.project_order) != len(set(self.project_order)):
            raise ValueError("项目更新顺序不能重复")
        normalized: list[str] = []
        for value in self.workspace_paths:
            path = WorkspaceRuntimeFileDraft.validate_relative_path(value)
            normalized.append(path)
        if len(normalized) != len(set(normalized)):
            raise ValueError("工作空间运行路径不能重复")
        self.workspace_paths = normalized
        return self


class RuntimeOperationStepView(BaseModel):
    id: str
    sequence: int
    owner_type: Literal["workspace", "project"]
    owner_id: str
    mode: Literal["start", "fast", "full"]
    status: RuntimeStepStatus
    changed_files: list[str]
    decision_reason: str
    exit_code: int | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    log: str = ""
    log_truncated: bool = False


class RuntimeOperationView(BaseModel):
    id: str
    task_id: int
    workspace_id: str
    kind: Literal["apply_changes", "start_workspace"]
    trigger: Literal["mcp", "api"]
    status: RuntimeOperationStatus
    changed_files: list[str]
    current_step: int
    runner_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: list[RuntimeOperationStepView]


class RunnerRegistration(BaseModel):
    runner_id: str = Field(min_length=1, max_length=64)
    hostname: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=50)


class RunnerLeaseRequest(BaseModel):
    runner_id: str = Field(min_length=1, max_length=64)


class RunnerOperationRequest(BaseModel):
    lease_token: str = Field(min_length=32, max_length=256)


class RunnerStepResultRequest(RunnerOperationRequest):
    exit_code: int
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)
