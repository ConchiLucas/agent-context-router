from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.config import settings
from context_router.db.models import Base, Project, Trace, TraceEvent
from context_router.db.session import get_session
from context_router.main import create_app
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_store import upsert_document


def _client_with_documents(tmp_path, monkeypatch, documents):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    documents_root = tmp_path / "documents"
    project_root = documents_root / "my-app-docs"
    (project_root / "docs").mkdir(parents=True)
    monkeypatch.setattr(settings, "documents_container_root", str(documents_root))

    with testing_session() as session:
        project = Project(
            slug="my-app",
            name="My App",
            root_path="/srv/projects/my-app",
            docs_path="my-app-docs",
        )
        session.add(project)
        session.flush()
        for document_id, title, source_path in documents:
            path = project_root / source_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {title}\nLive {document_id} body.", encoding="utf-8")
            upsert_document(
                session,
                project=project,
                document=DocumentCreate(
                    id=document_id,
                    title=title,
                    source_path=source_path,
                    doc_type="agent_index" if source_path == "AGENTS.md" else "runbook",
                    area="payments",
                    tags=["payments"],
                    content_markdown=f"# Cached {title}",
                ),
            )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    return TestClient(app), testing_session


def test_read_document_records_trace_event_when_trace_id_is_provided(tmp_path, monkeypatch) -> None:
    client, testing_session = _client_with_documents(
        tmp_path,
        monkeypatch,
        [("payments-runbook", "Payments runbook", "docs/payments.md")],
    )
    with testing_session() as session:
        project = session.scalar(select(Project).where(Project.slug == "my-app"))
        assert project is not None
        session.add(Trace(id="ctx_test_001", project_id=project.id, task="Fix payments"))
        session.commit()

    response = client.get(
        "/api/documents/payments-runbook",
        params={"trace_id": "ctx_test_001"},
    )

    assert response.status_code == 200
    assert response.json()["trace_id"] == "ctx_test_001"
    assert "Live payments-runbook body" in response.json()["content_markdown"]
    with testing_session() as session:
        event = session.scalar(select(TraceEvent).where(TraceEvent.event_type == "read"))
        assert event is not None
        assert event.payload["document_id"] == "payments-runbook"
        assert event.payload["parent_document_id"] is None
        assert event.payload["depth"] == 1
        assert event.payload["source"] is None
        assert event.payload["duration_ms"] >= 0


def test_mcp_read_requires_trace_id(tmp_path, monkeypatch) -> None:
    client, _testing_session = _client_with_documents(
        tmp_path,
        monkeypatch,
        [("payments-runbook", "Payments runbook", "docs/payments.md")],
    )

    response = client.get(
        "/api/documents/payments-runbook",
        params={"source": "mcp"},
    )

    assert response.status_code == 422


def test_read_document_creates_trace_unless_marked_untracked(tmp_path, monkeypatch) -> None:
    client, testing_session = _client_with_documents(
        tmp_path,
        monkeypatch,
        [("payments-runbook", "Payments runbook", "docs/payments.md")],
    )

    tracked_response = client.get("/api/documents/payments-runbook")
    assert tracked_response.status_code == 200
    assert tracked_response.json()["trace_id"].startswith("ctx_")

    with testing_session() as session:
        trace_count = len(session.scalars(select(Trace)).all())

    untracked_response = client.get(
        "/api/documents/payments-runbook",
        params={"untracked": True},
    )
    assert untracked_response.status_code == 200
    assert untracked_response.json()["trace_id"] is None
    with testing_session() as session:
        assert len(session.scalars(select(Trace)).all()) == trace_count


def test_mcp_read_rejects_missing_trace(tmp_path, monkeypatch) -> None:
    client, testing_session = _client_with_documents(
        tmp_path,
        monkeypatch,
        [("payments-runbook", "Payments runbook", "docs/payments.md")],
    )

    response = client.get(
        "/api/documents/payments-runbook",
        params={"trace_id": "ctx_missing", "source": "mcp"},
    )

    assert response.status_code == 404
    with testing_session() as session:
        assert session.scalar(select(TraceEvent).where(TraceEvent.event_type == "read")) is None


def test_read_document_records_tree_parent_and_depth(tmp_path, monkeypatch) -> None:
    client, testing_session = _client_with_documents(
        tmp_path,
        monkeypatch,
        [
            ("root-index", "Root index", "AGENTS.md"),
            ("payments-runbook", "Payments runbook", "docs/payments.md"),
        ],
    )
    with testing_session() as session:
        project = session.scalar(select(Project).where(Project.slug == "my-app"))
        assert project is not None
        session.add(Trace(id="ctx_test_001", project_id=project.id, task="Fix payments"))
        session.commit()

    root_response = client.get(
        "/api/documents/root-index",
        params={"trace_id": "ctx_test_001"},
    )
    child_response = client.get(
        "/api/documents/payments-runbook",
        params={
            "trace_id": "ctx_test_001",
            "parent_document_id": "root-index",
        },
    )

    assert root_response.status_code == 200
    assert child_response.status_code == 200
    with testing_session() as session:
        events = session.scalars(
            select(TraceEvent)
            .where(TraceEvent.event_type == "read")
            .order_by(TraceEvent.created_at)
        ).all()
        assert [event.payload["depth"] for event in events] == [1, 2]
        assert events[1].payload["parent_document_id"] == "root-index"
        assert events[1].payload["read_mode"] == "tree_read"


def test_mcp_read_rejects_parent_not_read_in_same_trace(tmp_path, monkeypatch) -> None:
    client, testing_session = _client_with_documents(
        tmp_path,
        monkeypatch,
        [
            ("root-index", "Root index", "AGENTS.md"),
            ("payments-runbook", "Payments runbook", "docs/payments.md"),
        ],
    )
    with testing_session() as session:
        project = session.scalar(select(Project).where(Project.slug == "my-app"))
        assert project is not None
        session.add(Trace(id="ctx_test_001", project_id=project.id, task="Fix payments"))
        session.commit()

    response = client.get(
        "/api/documents/payments-runbook",
        params={
            "trace_id": "ctx_test_001",
            "parent_document_id": "root-index",
            "source": "mcp",
        },
    )

    assert response.status_code == 422


def test_read_document_marks_prepare_followup_read(tmp_path, monkeypatch) -> None:
    client, testing_session = _client_with_documents(
        tmp_path,
        monkeypatch,
        [("root-index", "Root index", "AGENTS.md")],
    )
    with testing_session() as session:
        project = session.scalar(select(Project).where(Project.slug == "my-app"))
        assert project is not None
        trace = Trace(id="ctx_test_001", project_id=project.id, task="Fix payments")
        session.add(trace)
        session.flush()
        session.add(
            TraceEvent(
                trace_id=trace.id,
                event_type="prepare",
                payload={"project": "my-app"},
            )
        )
        session.commit()

    response = client.get(
        "/api/documents/root-index",
        params={"trace_id": "ctx_test_001"},
    )

    assert response.status_code == 200
    with testing_session() as session:
        read_event = session.scalar(select(TraceEvent).where(TraceEvent.event_type == "read"))
        assert read_event is not None
        assert read_event.payload["read_mode"] == "prepare_fallback"
