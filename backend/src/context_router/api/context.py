from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from context_router.db.models import Project, RetrievalHit, Trace, TraceEvent
from context_router.db.session import get_session
from context_router.schemas.context import PrepareContextRequest, PrepareContextResponse
from context_router.services.rendering import render_context_markdown
from context_router.services.retrieval import retrieve_documents
from context_router.services.tracing import new_trace_id

router = APIRouter(prefix="/api/context", tags=["context"])


@router.post("/prepare", response_model=PrepareContextResponse)
def prepare_context(
    request: PrepareContextRequest,
    session: Annotated[Session, Depends(get_session)],
) -> PrepareContextResponse:
    project = session.scalar(select(Project).where(Project.slug == request.project))
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project}")

    results = retrieve_documents(
        session,
        project=project,
        task=request.task,
        area=request.area,
        max_documents=request.max_documents,
    )
    trace_id = new_trace_id()
    trace = Trace(
        id=trace_id,
        project_id=project.id,
        task=request.task,
        cwd=request.cwd,
        area=request.area,
        entrypoint_path=request.entrypoint_path,
        entrypoint_rule=request.entrypoint_rule,
        route_hint=request.route_hint,
        source=request.source,
        agent_name=request.agent_name,
    )
    session.add(trace)
    session.add(
        TraceEvent(
            trace_id=trace_id,
            event_type="prepare",
            payload={
                "project": request.project,
                "task": request.task,
                "area": request.area,
                "entrypoint_path": request.entrypoint_path,
                "entrypoint_rule": request.entrypoint_rule,
                "route_hint": request.route_hint,
                "source": request.source,
                "agent_name": request.agent_name,
                "max_documents": request.max_documents,
                "output_format": request.output_format,
            },
        )
    )

    for result in results:
        session.add(
            RetrievalHit(
                trace_id=trace_id,
                document_id=result.document_id,
                rank=result.rank,
                score=result.score,
                reason=result.reason,
                was_returned=True,
            )
        )

    markdown = render_context_markdown(
        trace_id=trace_id,
        project=request.project,
        area=request.area,
        entrypoint_path=request.entrypoint_path,
        entrypoint_rule=request.entrypoint_rule,
        route_hint=request.route_hint,
        results=results,
    )
    session.commit()

    return PrepareContextResponse(
        trace_id=trace_id,
        project=request.project,
        task=request.task,
        area=request.area,
        entrypoint_path=request.entrypoint_path,
        entrypoint_rule=request.entrypoint_rule,
        route_hint=request.route_hint,
        documents=results,
        markdown=markdown,
    )
