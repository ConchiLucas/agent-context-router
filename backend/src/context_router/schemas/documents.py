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


class DocumentLinkSummary(BaseModel):
    target_document_id: str | None
    target_path: str
    label: str
    relation_type: str
    sort_order: int
    is_broken: bool


class DocumentSyncResponse(BaseModel):
    project_slug: str
    docs_path: str
    indexed_count: int
    reachable_count: int
    orphan_count: int
    broken_link_count: int
    link_count: int
    pruned_count: int
    indexed_document_ids: list[str]
    pruned_document_ids: list[str]


class DocumentReadResponse(BaseModel):
    id: str
    trace_id: str | None = None
    title: str
    source_path: str
    doc_type: str
    area: str | None
    tags: list[str]
    status: str
    is_reachable: bool
    graph_depth: int | None
    broken_link_count: int
    content_markdown: str
    links: list[DocumentLinkSummary] = Field(default_factory=list)


class DocumentSummary(BaseModel):
    id: str
    project_slug: str
    title: str
    source_path: str
    doc_type: str
    area: str | None
    tags: list[str]
    status: str
    is_reachable: bool
    graph_depth: int | None
    broken_link_count: int
    links: list[DocumentLinkSummary] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]
