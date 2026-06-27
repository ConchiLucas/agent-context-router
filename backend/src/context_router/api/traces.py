from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from context_router.db.models import Project, RetrievalHit, Trace, TraceEvent
from context_router.db.session import get_session
from context_router.schemas.traces import (
    RetrievalHitResponse,
    TraceDetailResponse,
    TraceEventResponse,
    TraceFeedbackRequest,
    TraceFeedbackResponse,
    TraceListResponse,
    TraceProject,
    TraceSummary,
)

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("", response_model=TraceListResponse)
def list_traces(
    session: Annotated[Session, Depends(get_session)],
    project: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> TraceListResponse:
    query = (
        select(Trace)
        .join(Trace.project)
        .options(
            selectinload(Trace.project),
            selectinload(Trace.events),
            selectinload(Trace.retrieval_hits),
        )
        .order_by(Trace.created_at.desc())
        .limit(limit)
    )
    if project is not None:
        query = query.where(Project.slug == project)

    traces = session.scalars(query).all()
    return TraceListResponse(traces=[_trace_summary(trace) for trace in traces])


@router.get("/{trace_id}", response_model=TraceDetailResponse)
def get_trace(
    trace_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> TraceDetailResponse:
    trace = session.scalar(
        select(Trace)
        .where(Trace.id == trace_id)
        .options(
            selectinload(Trace.project),
            selectinload(Trace.events),
            selectinload(Trace.retrieval_hits).selectinload(RetrievalHit.document),
        )
    )
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    return _trace_detail(trace)


@router.post("/{trace_id}/feedback", response_model=TraceFeedbackResponse)
def record_feedback(
    trace_id: str,
    request: TraceFeedbackRequest,
    session: Annotated[Session, Depends(get_session)],
) -> TraceFeedbackResponse:
    trace = session.scalar(select(Trace).where(Trace.id == trace_id))
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    hits = session.scalars(
        select(RetrievalHit).where(
            RetrievalHit.trace_id == trace_id,
            RetrievalHit.document_id == request.document_id,
        )
    ).all()
    if not hits:
        raise HTTPException(
            status_code=404,
            detail="Retrieval hit not found for this trace and document",
        )

    for hit in hits:
        hit.feedback = request.feedback

    session.add(
        TraceEvent(
            trace_id=trace_id,
            event_type="feedback",
            payload={
                "document_id": request.document_id,
                "feedback": request.feedback,
                "note": request.note,
            },
        )
    )
    session.commit()

    return TraceFeedbackResponse(
        trace_id=trace_id,
        document_id=request.document_id,
        feedback=request.feedback,
        updated_hit_count=len(hits),
    )


def _trace_summary(trace: Trace) -> TraceSummary:
    return TraceSummary(
        id=trace.id,
        project_slug=trace.project.slug,
        project_name=trace.project.name,
        task=trace.task,
        cwd=trace.cwd,
        created_at=trace.created_at,
        returned_document_count=sum(1 for hit in trace.retrieval_hits if hit.was_returned),
        read_event_count=sum(1 for event in trace.events if event.event_type == "read"),
        feedback_count=sum(1 for event in trace.events if event.event_type == "feedback"),
    )


def _trace_detail(trace: Trace) -> TraceDetailResponse:
    return TraceDetailResponse(
        id=trace.id,
        project=TraceProject(
            id=trace.project.id,
            slug=trace.project.slug,
            name=trace.project.name,
        ),
        task=trace.task,
        cwd=trace.cwd,
        agent_name=trace.agent_name,
        created_at=trace.created_at,
        retrieval_hits=[
            RetrievalHitResponse(
                id=hit.id,
                document_id=hit.document_id,
                document_title=hit.document.title,
                chunk_id=hit.chunk_id,
                rank=hit.rank,
                score=hit.score,
                reason=hit.reason,
                was_returned=hit.was_returned,
                feedback=hit.feedback,
            )
            for hit in trace.retrieval_hits
        ],
        events=[
            TraceEventResponse(
                id=event.id,
                event_type=event.event_type,
                payload=event.payload,
                created_at=event.created_at,
            )
            for event in trace.events
        ],
    )
