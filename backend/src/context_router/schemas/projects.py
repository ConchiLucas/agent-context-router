from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ProjectCreate(BaseModel):
    slug: NonBlankString
    name: NonBlankString
    root_path: NonBlankString
    description: str = ""
    parent_slug: str | None = None


class DocumentMappingRequest(BaseModel):
    docs_path: NonBlankString


class DocumentMappingResponse(BaseModel):
    project_slug: str
    docs_path: str
    last_synced_at: datetime | None
    last_sync_status: str
    last_sync_summary: dict[str, Any]


class DocumentMappingCandidateResponse(BaseModel):
    docs_path: str
    markdown_count: int
    mapped_project_slug: str | None


class DocumentMappingCandidateListResponse(BaseModel):
    candidates: list[DocumentMappingCandidateResponse]


class SyncSummary(BaseModel):
    indexed: int = 0
    reachable: int = 0
    orphan: int = 0
    broken_links: int = 0
    pruned: int = 0


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    root_path: str | None
    docs_path: str | None
    description: str
    parent_slug: str | None
    mapping_status: str
    last_synced_at: datetime | None
    last_sync_status: str
    sync_summary: SyncSummary


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
