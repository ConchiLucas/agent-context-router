from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TraceFeedbackValue = Literal["useful", "unnecessary", "missing", "stale"]


class TraceProject(BaseModel):
    id: str
    slug: str
    name: str


class TraceEventResponse(BaseModel):
    id: str
    event_type: str
    payload: dict
    created_at: datetime


class RetrievalHitResponse(BaseModel):
    id: str
    document_id: str
    document_title: str
    rank: int
    score: float
    reason: str
    was_returned: bool
    feedback: str | None


class TraceDetailResponse(BaseModel):
    id: str
    project: TraceProject
    task: str
    cwd: str | None
    area: str | None
    entrypoint_path: str | None
    entrypoint_rule: str | None
    route_hint: str | None
    source: str | None
    agent_name: str | None
    created_at: datetime
    retrieval_hits: list[RetrievalHitResponse]
    events: list[TraceEventResponse]


class TraceSummary(BaseModel):
    id: str
    project_slug: str
    project_name: str
    task: str
    cwd: str | None
    area: str | None
    source: str | None
    created_at: datetime
    returned_document_count: int
    read_event_count: int
    feedback_count: int


class TraceListResponse(BaseModel):
    traces: list[TraceSummary]


class TraceFeedbackRequest(BaseModel):
    document_id: str
    feedback: TraceFeedbackValue
    note: str = Field(default="")


class TraceFeedbackResponse(BaseModel):
    trace_id: str
    document_id: str
    feedback: TraceFeedbackValue
    updated_hit_count: int
