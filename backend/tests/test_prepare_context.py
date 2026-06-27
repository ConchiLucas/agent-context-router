from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.db.models import Base, Project, RetrievalHit, Trace
from context_router.db.session import get_session
from context_router.main import create_app
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_store import upsert_document


def test_prepare_context_returns_ranked_docs_and_records_trace() -> None:
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
                id="payments-webhook-timeout-history",
                title="Payments webhook timeout history",
                source_path="docs/payments-timeout.md",
                doc_type="debugging",
                area="payments",
                tags=["webhook", "timeout"],
                content_markdown=(
                    "# Payments\nWebhook timeout happened after retry headers changed."
                ),
            ),
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.post(
        "/api/context/prepare",
        json={
            "project": "my-app",
            "task": "修复 payments webhook timeout",
            "cwd": "/repo/my-app",
            "max_documents": 3,
            "output_format": "markdown",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project"] == "my-app"
    assert body["documents"][0]["document_id"] == "payments-webhook-timeout-history"
    assert "trace_id:" in body["markdown"]

    with TestingSession() as session:
        trace = session.scalar(select(Trace).where(Trace.id == body["trace_id"]))
        hits = session.scalars(
            select(RetrievalHit).where(RetrievalHit.trace_id == body["trace_id"])
        )

        assert trace is not None
        assert trace.task == "修复 payments webhook timeout"
        assert len(list(hits)) == 1
