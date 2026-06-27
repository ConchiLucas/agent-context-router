from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    slug: str
    name: str
    root_path: str | None = None
    description: str = ""


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    root_path: str | None
    description: str


class ProjectSummary(ProjectResponse):
    document_count: int
    active_document_count: int


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary]


class ProjectDetailResponse(ProjectSummary):
    routing_template: str
