from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.db.models import Base, Project, RetrievalHit, Trace, TraceEvent
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
        project = Project(slug="my-app", name="My App", root_path="/repo/my-app")
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
            "task": "修复 payments webhook timeout",
            "cwd": "/repo/my-app",
            "source": "mcp",
            "agent_name": "codex",
            "max_documents": 3,
            "output_format": "json",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project"] == "my-app"
    assert body["area"] is None
    assert body["documents"][0]["document_id"] == "payments-webhook-timeout-history"
    assert body["trace_id"].startswith("ctx_")
    assert "trace_id:" not in body["markdown"]

    with TestingSession() as session:
        trace = session.scalar(select(Trace).where(Trace.id == body["trace_id"]))
        hits = session.scalars(
            select(RetrievalHit).where(RetrievalHit.trace_id == body["trace_id"])
        )
        event = session.scalar(
            select(TraceEvent).where(
                TraceEvent.trace_id == body["trace_id"],
                TraceEvent.event_type == "prepare",
            )
        )

        assert trace is not None
        assert trace.task == "修复 payments webhook timeout"
        assert trace.area is None
        assert trace.entrypoint_path is None
        assert trace.entrypoint_rule is None
        assert trace.route_hint is None
        assert trace.source == "mcp"
        assert trace.agent_name == "codex"
        assert event is not None
        assert event.payload["project"] == "my-app"
        assert event.payload["max_documents"] == 3
        assert event.payload["duration_ms"] >= 0
        assert len(list(hits)) == 1


def test_prepare_context_requires_real_task_and_cwd() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    with TestingSession() as session:
        session.add(Project(slug="my-app", name="My App", root_path="/repo/my-app"))
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    requests = [
        {"project": "my-app", "task": "", "cwd": ""},
        {"project": "my-app", "task": "   ", "cwd": "/repo/my-app"},
        {"project": "my-app", "task": "fix login", "cwd": "   "},
    ]

    for payload in requests:
        response = client.post("/api/context/prepare", json=payload)
        assert response.status_code == 422

    with TestingSession() as session:
        assert session.scalar(select(Trace)) is None
