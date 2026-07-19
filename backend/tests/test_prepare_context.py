from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.config import settings
from context_router.db.models import Base, Project, RetrievalHit, Trace, TraceEvent
from context_router.db.session import get_session
from context_router.main import create_app


def _write_doc(path, *, doc_id: str, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ndoc_id: {doc_id}\ntitle: {title}\n---\n\n# {title}\n\n{body}\n",
        encoding="utf-8",
    )


def _client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    documents_root = tmp_path / "documents"
    project_docs = documents_root / "order-docs"
    _write_doc(
        project_docs / "AGENTS.md",
        doc_id="orders-entry",
        title="Orders entry",
        body="[Business](./docs/business.md)",
    )
    _write_doc(
        project_docs / "docs" / "business.md",
        doc_id="orders-business",
        title="Orders business",
        body="Payment and timeout rules",
    )
    _write_doc(
        project_docs / "docs" / "orphan.md",
        doc_id="orders-orphan",
        title="Orders orphan",
        body="Not linked from the entry",
    )
    monkeypatch.setattr(settings, "documents_container_root", str(documents_root))

    def override_session() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    return TestClient(app), testing_session, project_docs


def _add_project(testing_session, *, docs_path: str | None) -> None:
    with testing_session() as session:
        session.add(
            Project(
                slug="orders",
                name="Orders",
                root_path="/srv/projects/orders",
                docs_path=docs_path,
            )
        )
        session.commit()


def test_prepare_returns_only_mapped_agents_and_records_one_entry_hit(
    tmp_path, monkeypatch
) -> None:
    client, testing_session, _project_docs = _client(tmp_path, monkeypatch)
    _add_project(testing_session, docs_path="order-docs")
    assert client.post("/api/projects/orders/documents/sync-local", json={}).status_code == 200

    response = client.post(
        "/api/context/prepare",
        json={
            "task": "修复 payment timeout",
            "cwd": "/srv/projects/orders/backend",
            "source": "mcp",
            "agent_name": "codex",
            "max_documents": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project"] == "orders"
    assert body["trace_id"].startswith("ctx_")
    assert [document["document_id"] for document in body["documents"]] == ["orders-entry"]
    assert body["documents"][0]["rank"] == 1
    assert "Orders entry" in body["documents"][0]["excerpt"]
    with testing_session() as session:
        trace = session.scalar(select(Trace).where(Trace.id == body["trace_id"]))
        hits = session.scalars(
            select(RetrievalHit).where(RetrievalHit.trace_id == body["trace_id"])
        ).all()
        event = session.scalar(
            select(TraceEvent).where(
                TraceEvent.trace_id == body["trace_id"],
                TraceEvent.event_type == "prepare",
            )
        )
        assert trace is not None
        assert trace.task == "修复 payment timeout"
        assert trace.agent_name == "codex"
        assert [hit.document_id for hit in hits] == ["orders-entry"]
        assert event is not None
        assert event.payload["max_documents"] == 1
        assert event.payload["entry_document_id"] == "orders-entry"


def test_prepare_rejects_unmapped_and_unsynced_projects_without_trace(
    tmp_path, monkeypatch
) -> None:
    client, testing_session, _project_docs = _client(tmp_path, monkeypatch)
    _add_project(testing_session, docs_path=None)

    unmapped = client.post(
        "/api/context/prepare",
        json={"task": "Fix orders", "cwd": "/srv/projects/orders"},
    )
    assert unmapped.status_code == 409
    assert "synced document mapping" in unmapped.json()["detail"]

    with testing_session() as session:
        project = session.scalar(select(Project).where(Project.slug == "orders"))
        assert project is not None
        project.docs_path = "order-docs"
        session.commit()

    unsynced = client.post(
        "/api/context/prepare",
        json={"task": "Fix orders", "cwd": "/srv/projects/orders"},
    )
    assert unsynced.status_code == 409
    with testing_session() as session:
        assert session.scalar(select(Trace)) is None


def test_prepare_rejects_missing_live_agents_without_creating_trace(tmp_path, monkeypatch) -> None:
    client, testing_session, project_docs = _client(tmp_path, monkeypatch)
    _add_project(testing_session, docs_path="order-docs")
    assert client.post("/api/projects/orders/documents/sync-local", json={}).status_code == 200
    (project_docs / "AGENTS.md").unlink()

    response = client.post(
        "/api/context/prepare",
        json={"task": "Fix orders", "cwd": "/srv/projects/orders"},
    )

    assert response.status_code == 409
    assert "AGENTS.md" in response.json()["detail"]
    with testing_session() as session:
        assert session.scalar(select(Trace)) is None


def test_prepare_uses_last_complete_index_after_failed_resync(tmp_path, monkeypatch) -> None:
    client, testing_session, _project_docs = _client(tmp_path, monkeypatch)
    _add_project(testing_session, docs_path="order-docs")
    assert client.post("/api/projects/orders/documents/sync-local", json={}).status_code == 200
    with testing_session() as session:
        project = session.scalar(select(Project).where(Project.slug == "orders"))
        assert project is not None
        project.last_sync_status = "failed"
        session.commit()

    response = client.post(
        "/api/context/prepare",
        json={"task": "Fix orders", "cwd": "/srv/projects/orders"},
    )

    assert response.status_code == 200
    assert response.json()["documents"][0]["document_id"] == "orders-entry"


def test_prepare_context_requires_real_task_and_cwd(tmp_path, monkeypatch) -> None:
    client, testing_session, _project_docs = _client(tmp_path, monkeypatch)
    _add_project(testing_session, docs_path="order-docs")

    requests = [
        {"project": "orders", "task": "", "cwd": ""},
        {"project": "orders", "task": "   ", "cwd": "/srv/projects/orders"},
        {"project": "orders", "task": "fix login", "cwd": "   "},
    ]
    for payload in requests:
        assert client.post("/api/context/prepare", json=payload).status_code == 422
    with testing_session() as session:
        assert session.scalar(select(Trace)) is None
