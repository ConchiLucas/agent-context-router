from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProjectKind = Literal["frontend", "backend"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_type: str = Field(default="公司项目", min_length=1, max_length=60)
    project_kind: ProjectKind = "backend"
    agents_path: str = Field(min_length=1)


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_type: str = Field(default="公司项目", min_length=1, max_length=60)
    project_kind: ProjectKind | None = None
    agents_path: str = Field(min_length=1)


class ProjectSummary(BaseModel):
    id: str
    name: str
    project_type: str
    project_kind: ProjectKind = "backend"
    agents_path: str
    node_count: int
    refreshed_at: datetime | None
    error: str | None
    workspace_id: str | None = None
    workspace_name: str | None = None
    workspace_enabled: bool = True
    relative_path: str = "."


class DocumentTreeNode(BaseModel):
    id: str
    description: str
    path: str
    relative_path: str | None
    error: str | None
    children: list["DocumentTreeNode"]


class DocumentDetail(BaseModel):
    id: str
    description: str
    path: str
    relative_path: str | None
    content: str
    error: str | None
