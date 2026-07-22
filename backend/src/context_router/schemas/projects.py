from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_type: str = Field(default="公司项目", min_length=1, max_length=60)
    agents_path: str = Field(min_length=1)


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_type: str = Field(default="公司项目", min_length=1, max_length=60)
    agents_path: str = Field(min_length=1)


class ProjectEnabledUpdate(BaseModel):
    enabled: bool


class ProjectSummary(BaseModel):
    id: str
    name: str
    project_type: str
    agents_path: str
    enabled: bool
    node_count: int
    refreshed_at: datetime | None
    error: str | None


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
