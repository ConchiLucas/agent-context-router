from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    slug: str
    name: str
    root_path: str | None = None
    description: str = ""
    parent_slug: str | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    root_path: str | None
    description: str
    parent_slug: str | None


class ProjectSummary(ProjectResponse):
    document_count: int
    active_document_count: int
    trace_count: int
    child_project_count: int


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary]


class ProjectDetailResponse(ProjectSummary):
    children: list[ProjectSummary]
    routing_template: str
