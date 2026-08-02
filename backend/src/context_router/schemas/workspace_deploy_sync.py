from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True, slots=True)
class DeployConfigFile:
    relative_path: str
    content: str
    executable: bool


@dataclass(frozen=True, slots=True)
class RuntimeProfileBundle:
    files: tuple[DeployConfigFile, ...]


@dataclass(frozen=True, slots=True)
class ProjectDeployBundle:
    project_id: str
    relative_path: str
    fast: RuntimeProfileBundle
    full: RuntimeProfileBundle


@dataclass(frozen=True, slots=True)
class WorkspaceDeployBundle:
    digest: str
    workspace_paths: tuple[str, ...]
    project_order: tuple[str, ...]
    start: RuntimeProfileBundle
    projects: tuple[ProjectDeployBundle, ...]


@dataclass(frozen=True, slots=True)
class DeployChangeSummary:
    additions: int = 0
    updates: int = 0
    deletions: int = 0


@dataclass(frozen=True, slots=True)
class DeployProfilePreview:
    owner: str
    mode: str
    file_count: int
    changes: DeployChangeSummary


@dataclass(frozen=True, slots=True)
class WorkspaceDeploySyncPreview:
    valid: bool
    source_root: str
    digest: str
    profiles: tuple[DeployProfilePreview, ...]
    total: DeployChangeSummary
    synchronized: bool = False


class WorkspaceDeploySyncCommitRequest(BaseModel):
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
