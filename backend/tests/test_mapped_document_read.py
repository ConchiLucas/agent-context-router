from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.config import settings
from context_router.db.models import Base, Project
from context_router.db.session import get_session
from context_router.main import create_app
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_store import upsert_document


def _client(monkeypatch, documents_root):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "documents_container_root", str(documents_root))

    def override_session() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    return TestClient(app), testing_session


def _write_agents(path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "docs").mkdir(exist_ok=True)
    path.write_text(
        f"---\ndoc_id: orders-entry\ntitle: Orders entry\n---\n\n# Orders\n\n{body}\n",
        encoding="utf-8",
    )


def _index_entry(testing_session, *, root_path: str | None = None, docs_path="order-docs"):
    with testing_session() as session:
        project = Project(
            slug="orders",
            name="Orders",
            root_path=root_path,
            docs_path=docs_path,
        )
        session.add(project)
        session.flush()
        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="orders-entry",
                title="Orders entry",
                source_path="AGENTS.md",
                doc_type="agent_index",
                content_markdown="# Cached body",
            ),
        )
        session.commit()


def test_untracked_read_returns_latest_mapped_file_body(tmp_path, monkeypatch) -> None:
    documents_root = tmp_path / "documents"
    agents_path = documents_root / "order-docs" / "AGENTS.md"
    _write_agents(agents_path, "First live body")
    client, testing_session = _client(monkeypatch, documents_root)
    _index_entry(testing_session)

    first = client.get("/api/documents/orders-entry", params={"untracked": True})
    _write_agents(agents_path, "Updated live body")
    second = client.get("/api/documents/orders-entry", params={"untracked": True})

    assert first.status_code == 200
    assert first.json()["content_markdown"].endswith("First live body\n")
    assert second.status_code == 200
    assert second.json()["content_markdown"].endswith("Updated live body\n")
    assert "doc_id:" not in second.json()["content_markdown"]


def test_mapped_read_does_not_fall_back_to_cached_body_when_file_is_missing(
    tmp_path, monkeypatch
) -> None:
    documents_root = tmp_path / "documents"
    agents_path = documents_root / "order-docs" / "AGENTS.md"
    _write_agents(agents_path, "Live body")
    client, testing_session = _client(monkeypatch, documents_root)
    _index_entry(testing_session)
    agents_path.unlink()

    response = client.get("/api/documents/orders-entry", params={"untracked": True})

    assert response.status_code == 404
    assert "AGENTS.md" in response.json()["detail"]


def test_read_without_mapping_does_not_use_code_root_or_cached_body(tmp_path, monkeypatch) -> None:
    documents_root = tmp_path / "documents"
    documents_root.mkdir()
    code_root = tmp_path / "code-project"
    _write_agents(code_root / "AGENTS.md", "Code repository body")
    client, testing_session = _client(monkeypatch, documents_root)
    _index_entry(testing_session, root_path=str(code_root), docs_path=None)

    response = client.get("/api/documents/orders-entry", params={"untracked": True})

    assert response.status_code == 400
    assert "mapping" in response.json()["detail"].lower()


def test_mapped_read_rejects_symlink_source_file(tmp_path, monkeypatch) -> None:
    documents_root = tmp_path / "documents"
    project_docs = documents_root / "order-docs"
    actual_path = project_docs / "actual-agents.md"
    _write_agents(actual_path, "Symlink target")
    agents_path = project_docs / "AGENTS.md"
    agents_path.symlink_to(actual_path)
    client, testing_session = _client(monkeypatch, documents_root)
    _index_entry(testing_session)

    response = client.get("/api/documents/orders-entry", params={"untracked": True})

    assert response.status_code == 400
    assert "symlink" in response.json()["detail"].lower()
