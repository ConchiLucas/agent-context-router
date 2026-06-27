from pydantic import BaseModel, Field


class PrepareContextRequest(BaseModel):
    project: str
    task: str
    cwd: str | None = None
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
    documents: list[ContextDocument]
    markdown: str
