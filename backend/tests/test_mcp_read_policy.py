from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.config import settings
from context_router.db.models import Base, Project, TraceEvent
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
    order_docs = documents_root / "order-docs"
    _write_doc(
        order_docs / "AGENTS.md",
        doc_id="orders-entry",
        title="Orders entry",
        body=("[Business](./docs/business.md)\n[Missing](./docs/missing.md)"),
    )
    _write_doc(
        order_docs / "docs" / "business.md",
        doc_id="orders-business",
        title="Orders business",
        body="[Database](./database.md)",
    )
    _write_doc(
        order_docs / "docs" / "database.md",
        doc_id="orders-database",
        title="Orders database",
        body="Schema details",
    )
    _write_doc(
        order_docs / "docs" / "orphan.md",
        doc_id="orders-orphan",
        title="Orders orphan",
        body="Not linked",
    )
    user_docs = documents_root / "user-docs"
    _write_doc(
        user_docs / "AGENTS.md",
        doc_id="users-entry",
        title="Users entry",
        body="User docs",
    )
    (user_docs / "docs").mkdir()
    monkeypatch.setattr(settings, "documents_container_root", str(documents_root))

    with testing_session() as session:
        session.add_all(
            [
                Project(
                    slug="orders",
                    name="Orders",
                    root_path="/srv/projects/orders",
                    docs_path="order-docs",
                ),
                Project(
                    slug="users",
                    name="Users",
                    root_path="/srv/projects/users",
                    docs_path="user-docs",
                ),
            ]
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    assert client.post("/api/projects/orders/documents/sync-local", json={}).status_code == 200
    assert client.post("/api/projects/users/documents/sync-local", json={}).status_code == 200
    return client, testing_session


def _prepare(client: TestClient, *, cwd="/srv/projects/orders") -> str:
    response = client.post(
        "/api/context/prepare",
        json={"task": "Fix current task", "cwd": cwd, "source": "mcp"},
    )
    assert response.status_code == 200
    return response.json()["trace_id"]


def _read(client: TestClient, trace_id: str, document_id: str, parent=None):
    params = {"trace_id": trace_id, "source": "mcp"}
    if parent is not None:
        params["parent_document_id"] = parent
    return client.get(f"/api/documents/{document_id}", params=params)


def test_first_mcp_read_must_be_prepared_agents_without_parent(tmp_path, monkeypatch) -> None:
    client, testing_session = _client(tmp_path, monkeypatch)
    trace_id = _prepare(client)

    deep_first = _read(client, trace_id, "orders-business")
    parent_on_first = _read(
        client,
        trace_id,
        "orders-entry",
        parent="orders-entry",
    )
    entry = _read(client, trace_id, "orders-entry")

    assert deep_first.status_code == 422
    assert "first" in deep_first.json()["detail"].lower()
    assert parent_on_first.status_code == 422
    assert entry.status_code == 200
    assert entry.json()["links"] == [
        {
            "target_document_id": "orders-business",
            "target_path": "docs/business.md",
            "label": "Business",
            "relation_type": "markdown_link",
            "sort_order": 0,
            "is_broken": False,
        }
    ]
    with testing_session() as session:
        events = session.scalars(select(TraceEvent).where(TraceEvent.event_type == "read")).all()
        assert len(events) == 1
        assert events[0].payload["document_id"] == "orders-entry"
        assert events[0].payload["depth"] == 1


def test_followup_requires_read_parent_and_direct_link(tmp_path, monkeypatch) -> None:
    client, testing_session = _client(tmp_path, monkeypatch)
    trace_id = _prepare(client)
    assert _read(client, trace_id, "orders-entry").status_code == 200

    missing_parent = _read(client, trace_id, "orders-business")
    skipped_level = _read(
        client,
        trace_id,
        "orders-database",
        parent="orders-entry",
    )
    child = _read(
        client,
        trace_id,
        "orders-business",
        parent="orders-entry",
    )
    deep = _read(
        client,
        trace_id,
        "orders-database",
        parent="orders-business",
    )

    assert missing_parent.status_code == 422
    assert skipped_level.status_code == 422
    assert "direct" in skipped_level.json()["detail"].lower()
    assert child.status_code == 200
    assert deep.status_code == 200
    with testing_session() as session:
        events = session.scalars(
            select(TraceEvent)
            .where(TraceEvent.event_type == "read")
            .order_by(TraceEvent.created_at)
        ).all()
        assert [event.payload["depth"] for event in events] == [1, 2, 3]
        assert events[2].payload["parent_document_id"] == "orders-business"


def test_mcp_read_rejects_other_trace_project_and_orphan(tmp_path, monkeypatch) -> None:
    client, _testing_session = _client(tmp_path, monkeypatch)
    first_trace = _prepare(client)
    second_trace = _prepare(client)
    assert _read(client, first_trace, "orders-entry").status_code == 200

    unread_parent = _read(
        client,
        second_trace,
        "orders-business",
        parent="orders-entry",
    )
    other_project = _read(client, first_trace, "users-entry")
    orphan = _read(
        client,
        first_trace,
        "orders-orphan",
        parent="orders-entry",
    )

    assert unread_parent.status_code == 422
    assert other_project.status_code == 422
    assert orphan.status_code == 422


def test_web_untracked_preview_can_open_orphan_without_read_event(tmp_path, monkeypatch) -> None:
    client, testing_session = _client(tmp_path, monkeypatch)

    response = client.get(
        "/api/documents/orders-orphan",
        params={"untracked": True},
    )

    assert response.status_code == 200
    with testing_session() as session:
        assert session.scalar(select(TraceEvent).where(TraceEvent.event_type == "read")) is None
