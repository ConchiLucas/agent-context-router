from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from context_router.db.models import Project, RetrievalHit, Trace
from context_router.db.session import get_session
from context_router.schemas.traces import (
    RetrievalHitResponse,
    TraceDetailResponse,
    TraceEventResponse,
    TraceListResponse,
    TraceProject,
    TraceSummary,
)

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("", response_model=TraceListResponse)
def list_traces(
    session: Annotated[Session, Depends(get_session)],
    project: str | None = Query(default=None),
    area: str | None = Query(default=None),
    source: str | None = Query(default=None),
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
        query = query.where(Project.slug.in_(_project_slug_scope(session, project)))
    if area is not None:
        query = query.where(Trace.area == area)
    if source is not None:
        query = query.where(Trace.source == source)

    traces = session.scalars(query).all()
    return TraceListResponse(traces=[_trace_summary(trace) for trace in traces])


def _project_slug_scope(session: Session, project_slug: str) -> list[str]:
    project = session.scalar(select(Project).where(Project.slug == project_slug))
    if project is None:
        return [project_slug]

    slugs = [project.slug]
    pending_ids = [project.id]
    while pending_ids:
        children = session.scalars(
            select(Project).where(Project.parent_project_id.in_(pending_ids))
        ).all()
        slugs.extend(child.slug for child in children)
        pending_ids = [child.id for child in children]
    return slugs


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


def _trace_summary(trace: Trace) -> TraceSummary:
    return TraceSummary(
        id=trace.id,
        project_slug=trace.project.slug,
        project_name=trace.project.name,
        task=trace.task,
        cwd=trace.cwd,
        area=trace.area,
        source=trace.source,
        agent_name=trace.agent_name,
        created_at=trace.created_at,
        returned_document_count=sum(1 for hit in trace.retrieval_hits if hit.was_returned),
        read_event_count=sum(1 for event in trace.events if event.event_type == "read"),
        mcp_duration_ms=_mcp_duration_ms(trace),
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
        area=trace.area,
        entrypoint_path=trace.entrypoint_path,
        entrypoint_rule=trace.entrypoint_rule,
        route_hint=trace.route_hint,
        source=trace.source,
        agent_name=trace.agent_name,
        created_at=trace.created_at,
        retrieval_hits=[
            RetrievalHitResponse(
                id=hit.id,
                document_id=hit.document_id,
                document_title=hit.document.title,
                rank=hit.rank,
                score=hit.score,
                reason=hit.reason,
                was_returned=hit.was_returned,
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


def _mcp_duration_ms(trace: Trace) -> float:
    total = 0.0
    for event in trace.events:
        duration = event.payload.get("duration_ms")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            total += float(duration)
    return round(total, 3)
