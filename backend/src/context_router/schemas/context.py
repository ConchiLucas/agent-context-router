from pydantic import BaseModel, Field


class PrepareContextRequest(BaseModel):
    project: str
    task: str
    area: str | None = None
    cwd: str | None = None
    entrypoint_path: str | None = None
    entrypoint_rule: str | None = None
    route_hint: str | None = None
    source: str | None = None
    agent_name: str | None = None
    max_documents: int = Field(default=5, ge=1, le=20)
    output_format: str = "markdown"


class ContextDocument(BaseModel):
    document_id: str
    title: str
    reason: str
    score: float
    excerpt: str
    rank: int


class PrepareContextResponse(BaseModel):
    trace_id: str
    project: str
    task: str
    area: str | None
    entrypoint_path: str | None
    entrypoint_rule: str | None
    route_hint: str | None
    documents: list[ContextDocument]
    markdown: str
