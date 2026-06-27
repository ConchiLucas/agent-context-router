from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.db.models import Base, Project, Trace, TraceEvent
from context_router.db.session import get_session
from context_router.main import create_app
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_store import upsert_document


def test_read_document_records_trace_event_when_trace_id_and_reason_are_provided() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    with TestingSession() as session:
        project = Project(slug="my-app", name="My App")
        session.add(project)
        session.flush()
        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="payments-runbook",
                title="Payments runbook",
                source_path="docs/payments.md",
                doc_type="runbook",
                area="payments",
                tags=["payments"],
                content_markdown="# Payments\nRun payment tests.",
            ),
        )
        session.add(Trace(id="ctx_test_001", project_id=project.id, task="Fix payments"))
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.get(
        "/api/documents/payments-runbook",
        params={"trace_id": "ctx_test_001", "reason": "Need full runbook"},
    )

    assert response.status_code == 200
    assert response.json()["content_markdown"] == "# Payments\nRun payment tests."

    with TestingSession() as session:
        event = session.scalar(select(TraceEvent).where(TraceEvent.event_type == "read"))

        assert event is not None
        assert event.payload["document_id"] == "payments-runbook"
        assert event.payload["reason"] == "Need full runbook"
