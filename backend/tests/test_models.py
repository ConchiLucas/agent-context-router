from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from context_router.db.models import (
    Base,
    Document,
    DocumentChunk,
    Project,
    RetrievalHit,
    Trace,
    TraceEvent,
)


def test_project_document_trace_lifecycle_can_be_persisted() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(
            slug="my-app",
            name="My App",
            root_path="/repo/my-app",
            description="Main application",
        )
        session.add(project)
        session.flush()

        document = Document(
            id="payments-webhook-timeout-history",
            project_id=project.id,
            title="Payments webhook timeout history",
            source_path="docs/debugging/payments-webhook-timeout.md",
            doc_type="debugging",
            area="payments",
            tags=["webhook", "timeout"],
            content_markdown="# Timeout history\nPast webhook timeout notes.",
        )
        session.add(document)

        chunk = DocumentChunk(
            document_id=document.id,
            heading_path=["Timeout history"],
            chunk_index=0,
            content="Past webhook timeout notes.",
            token_estimate=5,
            embedding=[0.1, 0.2, 0.3],
            chunk_metadata={"source": "unit-test"},
        )
        session.add(chunk)

        trace = Trace(
            id="ctx_test_001",
            project_id=project.id,
            task="修复支付 webhook timeout",
            cwd="/repo/my-app",
            agent_name="codex",
        )
        session.add(trace)

        event = TraceEvent(
            trace_id=trace.id,
            event_type="prepare",
            payload={"max_documents": 5},
        )
        session.add(event)

        hit = RetrievalHit(
            trace_id=trace.id,
            document_id=document.id,
            chunk_id=chunk.id,
            rank=1,
            score=0.91,
            reason="Task mentions payments, webhook, and timeout.",
            was_returned=True,
        )
        session.add(hit)
        session.commit()

    with Session(engine) as session:
        saved_project = session.scalar(select(Project).where(Project.slug == "my-app"))

        assert saved_project is not None
        assert saved_project.documents[0].id == "payments-webhook-timeout-history"
        assert saved_project.traces[0].retrieval_hits[0].reason.startswith("Task mentions")
        assert saved_project.traces[0].events[0].payload == {"max_documents": 5}
