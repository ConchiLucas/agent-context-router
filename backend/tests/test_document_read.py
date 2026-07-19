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


def test_read_document_records_trace_event_when_trace_id_is_provided() -> None:
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
        params={"trace_id": "ctx_test_001", "source": "mcp"},
    )

    assert response.status_code == 200
    assert response.json()["trace_id"] == "ctx_test_001"
    assert response.json()["content_markdown"] == "# Payments\nRun payment tests."

    with TestingSession() as session:
        event = session.scalar(select(TraceEvent).where(TraceEvent.event_type == "read"))

        assert event is not None
        assert event.payload["document_id"] == "payments-runbook"
        assert event.payload["document_title"] == "Payments runbook"
        assert event.payload["parent_document_id"] is None
        assert event.payload["depth"] == 1
        assert event.payload["source"] == "mcp"
        assert event.payload["read_mode"] == "current_trace"
        assert event.payload["duration_ms"] >= 0


def test_mcp_read_requires_trace_id() -> None:
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
                content_markdown="# Payments",
            ),
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.get(
        "/api/documents/payments-runbook",
        params={"source": "mcp"},
    )

    assert response.status_code == 422


def test_read_document_creates_trace_unless_marked_untracked() -> None:
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
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    tracked_response = client.get("/api/documents/payments-runbook")

    assert tracked_response.status_code == 200
    tracked_body = tracked_response.json()
    assert tracked_body["trace_id"].startswith("ctx_")
    assert tracked_body["content_markdown"] == "# Payments\nRun payment tests."

    with TestingSession() as session:
        trace = session.scalar(select(Trace).where(Trace.id == tracked_body["trace_id"]))
        event = session.scalar(select(TraceEvent).where(TraceEvent.event_type == "read"))

        assert trace is not None
        assert trace.task == "读取文档：Payments runbook"
        assert event is not None
        assert event.payload["document_id"] == "payments-runbook"
        assert event.payload["document_title"] == "Payments runbook"
        assert event.payload["project_slug"] == "my-app"
        assert event.payload["read_mode"] == "direct_read"

    untracked_response = client.get(
        "/api/documents/payments-runbook",
        params={"untracked": True},
    )

    assert untracked_response.status_code == 200
    assert untracked_response.json()["trace_id"] is None
    assert untracked_response.json()["content_markdown"] == "# Payments\nRun payment tests."


def test_read_document_prefers_local_file_content_when_project_has_root_path(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    project_root = tmp_path / "target-project"
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    document_path = docs_dir / "payments.md"
    document_path.write_text(
        """---
doc_id: payments-runbook
title: Payments runbook
---

# Payments
Fresh local file content.
""",
        encoding="utf-8",
    )

    with TestingSession() as session:
        project = Project(slug="my-app", name="My App", root_path=str(project_root))
        session.add(project)
        session.flush()
        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="payments-runbook",
                title="Payments runbook",
                source_path=str(document_path),
                doc_type="runbook",
                area="payments",
                tags=["payments"],
                content_markdown="# Payments\nStale cached content.",
            ),
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.get(
        "/api/documents/payments-runbook",
        params={"untracked": True},
    )

    assert response.status_code == 200
    assert response.json()["content_markdown"] == "# Payments\nFresh local file content.\n"


def test_read_document_reports_missing_local_file_when_project_has_root_path(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    project_root = tmp_path / "target-project"
    project_root.mkdir()
    document_path = project_root / "docs" / "missing.md"

    with TestingSession() as session:
        project = Project(slug="my-app", name="My App", root_path=str(project_root))
        session.add(project)
        session.flush()
        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="missing-runbook",
                title="Missing runbook",
                source_path=str(document_path),
                doc_type="runbook",
                area=None,
                tags=[],
                content_markdown="# Cached fallback should not be used.",
            ),
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.get(
        "/api/documents/missing-runbook",
        params={"untracked": True},
    )

    assert response.status_code == 404
    assert "Local document file not found" in response.json()["detail"]


def test_mcp_read_rejects_missing_trace() -> None:
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
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.get(
        "/api/documents/payments-runbook",
        params={"trace_id": "ctx_missing", "source": "mcp"},
    )

    assert response.status_code == 404

    with TestingSession() as session:
        event = session.scalar(select(TraceEvent).where(TraceEvent.event_type == "read"))

        assert event is None


def test_read_document_records_tree_parent_and_depth() -> None:
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
        for document_id, title in [
            ("root-index", "Root index"),
            ("payments-runbook", "Payments runbook"),
        ]:
            upsert_document(
                session,
                project=project,
                document=DocumentCreate(
                    id=document_id,
                    title=title,
                    source_path=f"docs/{document_id}.md",
                    doc_type="runbook",
                    area="payments",
                    tags=["payments"],
                    content_markdown=f"# {title}",
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

    root_response = client.get(
        "/api/documents/root-index",
        params={"trace_id": "ctx_test_001", "source": "mcp"},
    )
    response = client.get(
        "/api/documents/payments-runbook",
        params={
            "trace_id": "ctx_test_001",
            "parent_document_id": "root-index",
            "source": "mcp",
        },
    )

    assert root_response.status_code == 200
    assert response.status_code == 200

    with TestingSession() as session:
        events = session.scalars(
            select(TraceEvent)
            .where(TraceEvent.event_type == "read")
            .order_by(TraceEvent.created_at)
        ).all()

        assert [event.payload["depth"] for event in events] == [1, 2]
        assert events[1].payload["document_id"] == "payments-runbook"
        assert events[1].payload["parent_document_id"] == "root-index"
        assert events[1].payload["read_mode"] == "tree_read"


def test_mcp_read_rejects_parent_not_read_in_same_trace() -> None:
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
        for document_id in ["root-index", "payments-runbook"]:
            upsert_document(
                session,
                project=project,
                document=DocumentCreate(
                    id=document_id,
                    title=document_id,
                    source_path=f"docs/{document_id}.md",
                    doc_type="runbook",
                    area="payments",
                    tags=[],
                    content_markdown=f"# {document_id}",
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
        params={
            "trace_id": "ctx_test_001",
            "parent_document_id": "root-index",
            "source": "mcp",
        },
    )

    assert response.status_code == 422


def test_read_document_marks_prepare_followup_read() -> None:
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
                content_markdown="# Payments",
            ),
        )
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

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.get(
        "/api/documents/payments-runbook",
        params={"trace_id": "ctx_test_001", "source": "mcp"},
    )

    assert response.status_code == 200

    with TestingSession() as session:
        read_event = session.scalar(select(TraceEvent).where(TraceEvent.event_type == "read"))

        assert read_event is not None
        assert read_event.payload["read_mode"] == "prepare_fallback"
