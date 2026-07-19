from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from context_router.db.models import RetrievalHit, Trace, TraceEvent
from context_router.db.session import get_session
from context_router.schemas.context import PrepareContextRequest, PrepareContextResponse
from context_router.services.project_resolution import ProjectResolutionError, resolve_project
from context_router.services.rendering import render_context_markdown
from context_router.services.retrieval import retrieve_documents
from context_router.services.tracing import new_trace_id

router = APIRouter(prefix="/api/context", tags=["context"])


@router.post("/prepare", response_model=PrepareContextResponse)
def prepare_context(
    request: PrepareContextRequest,
    session: Annotated[Session, Depends(get_session)],
) -> PrepareContextResponse:
    try:
        project = resolve_project(
            session,
            cwd=request.cwd,
            project_slug=request.project,
        )
    except ProjectResolutionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    task_text = request.task.strip()
    started_at = perf_counter()

    results = retrieve_documents(
        session,
        project=project,
        task=task_text,
        area=request.area,
        max_documents=request.max_documents,
    )
    duration_ms = round((perf_counter() - started_at) * 1000, 3)
    trace_id = new_trace_id()
    trace = Trace(
        id=trace_id,
        project_id=project.id,
        task=task_text,
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
                "project": project.slug,
                "task": task_text,
                "area": request.area,
                "entrypoint_path": request.entrypoint_path,
                "entrypoint_rule": request.entrypoint_rule,
                "route_hint": request.route_hint,
                "source": request.source,
                "agent_name": request.agent_name,
                "max_documents": request.max_documents,
                "output_format": request.output_format,
                "duration_ms": duration_ms,
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
        project=project.slug,
        area=request.area,
        entrypoint_path=request.entrypoint_path,
        entrypoint_rule=request.entrypoint_rule,
        route_hint=request.route_hint,
        results=results,
    )
    session.commit()

    return PrepareContextResponse(
        trace_id=trace_id,
        project=project.slug,
        task=task_text,
        area=request.area,
        entrypoint_path=request.entrypoint_path,
        entrypoint_rule=request.entrypoint_rule,
        route_hint=request.route_hint,
        documents=results,
        markdown=markdown,
    )
