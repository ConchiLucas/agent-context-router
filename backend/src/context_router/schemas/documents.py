from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    id: str
    title: str
    source_path: str
    doc_type: str
    area: str | None = None
    tags: list[str] = Field(default_factory=list)
    content_markdown: str


class DocumentUpsertResponse(BaseModel):
    id: str
    status: str


class DocumentReadResponse(BaseModel):
    id: str
    title: str
    source_path: str
    doc_type: str
    area: str | None
    tags: list[str]
    status: str
    content_markdown: str


class DocumentSummary(BaseModel):
    id: str
    project_slug: str
    title: str
    source_path: str
    doc_type: str
    area: str | None
    tags: list[str]
    status: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]
