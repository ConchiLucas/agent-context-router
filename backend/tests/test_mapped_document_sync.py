from collections.abc import Generator
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.config import settings
from context_router.db.models import (
    Base,
    Document,
    DocumentLink,
    Project,
    RetrievalHit,
    Trace,
)
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


def _write_document(path, *, doc_id: str | None, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = f"doc_id: {doc_id}\n" if doc_id is not None else ""
    path.write_text(
        f"---\n{metadata}title: {title}\ndoc_type: runbook\n---\n\n# {title}\n\n{body}\n",
        encoding="utf-8",
    )


def test_sync_indexes_only_mapped_tree_and_computes_document_health(tmp_path, monkeypatch) -> None:
    documents_root = tmp_path / "documents"
    project_docs = documents_root / "order-docs"
    _write_document(
        project_docs / "AGENTS.md",
        doc_id="orders-entry",
        title="Orders entry",
        body=(
            "[Business](./docs/business.md#rules)\n"
            "[Missing](./docs/missing.md)\n"
            "[Symlink alias](./docs/alias.md)\n"
            "[Website](https://example.com)"
        ),
    )
    _write_document(
        project_docs / "docs" / "business.md",
        doc_id="orders-business",
        title="Orders business",
        body="[Deep guide](./deep%20guide.md)",
    )
    _write_document(
        project_docs / "docs" / "deep guide.md",
        doc_id="orders-deep",
        title="Orders deep guide",
        body="Details",
    )
    _write_document(
        project_docs / "docs" / "orphan.md",
        doc_id="orders-orphan",
        title="Orders orphan",
        body="Not linked",
    )
    (project_docs / "docs" / "alias.md").symlink_to(project_docs / "docs" / "business.md")
    _write_document(
        project_docs / "README.md",
        doc_id="orders-readme",
        title="Ignored readme",
        body="Must not be indexed",
    )
    _write_document(
        project_docs / "other" / "ignored.md",
        doc_id="orders-ignored",
        title="Ignored nested doc",
        body="Must not be indexed",
    )
    client, testing_session = _client(monkeypatch, documents_root)
    with testing_session() as session:
        session.add(
            Project(
                slug="orders",
                name="Orders",
                root_path="/srv/projects/orders",
                docs_path="order-docs",
            )
        )
        session.commit()

    response = client.post(
        "/api/projects/orders/documents/sync-local",
        json={"docs_dir": "/tmp/must-be-ignored", "prune": False},
    )

    assert response.status_code == 200
    assert response.json() == {
        "project_slug": "orders",
        "docs_path": "order-docs",
        "indexed_count": 4,
        "reachable_count": 3,
        "orphan_count": 1,
        "broken_link_count": 2,
        "link_count": 4,
        "pruned_count": 0,
        "indexed_document_ids": [
            "orders-entry",
            "orders-business",
            "orders-deep",
            "orders-orphan",
        ],
        "pruned_document_ids": [],
    }
    with testing_session() as session:
        documents = {document.id: document for document in session.scalars(select(Document)).all()}
        assert set(documents) == {
            "orders-entry",
            "orders-business",
            "orders-deep",
            "orders-orphan",
        }
        assert documents["orders-entry"].source_path == "AGENTS.md"
        assert documents["orders-entry"].doc_type == "agent_index"
        assert documents["orders-entry"].graph_depth == 1
        assert documents["orders-business"].graph_depth == 2
        assert documents["orders-deep"].graph_depth == 3
        assert documents["orders-orphan"].is_reachable is False
        assert documents["orders-orphan"].graph_depth is None
        broken_links = session.scalars(
            select(DocumentLink).where(DocumentLink.target_document_id.is_(None))
        ).all()
        assert {link.target_path for link in broken_links} == {
            "docs/alias.md",
            "docs/missing.md",
        }
        assert all(link.source_document_id == "orders-entry" for link in broken_links)
        project = session.scalar(select(Project).where(Project.slug == "orders"))
        assert project is not None
        assert project.last_sync_status == "success"
        assert project.last_sync_summary["broken_links"] == 2


def test_sync_failure_rolls_back_index_and_preserves_last_success(tmp_path, monkeypatch) -> None:
    documents_root = tmp_path / "documents"
    project_docs = documents_root / "order-docs"
    _write_document(
        project_docs / "AGENTS.md",
        doc_id="orders-entry",
        title="Orders entry",
        body="[Broken metadata](./docs/broken.md)",
    )
    _write_document(
        project_docs / "docs" / "broken.md",
        doc_id=None,
        title="Broken metadata",
        body="Missing id",
    )
    client, testing_session = _client(monkeypatch, documents_root)
    last_success = datetime.now(UTC)
    with testing_session() as session:
        project = Project(
            slug="orders",
            name="Orders",
            root_path="/srv/projects/orders",
            docs_path="order-docs",
            last_synced_at=last_success,
            last_sync_status="success",
            last_sync_summary={"indexed": 1},
        )
        session.add(project)
        session.flush()
        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="previous-entry",
                title="Previous entry",
                source_path="AGENTS.md",
                doc_type="agent_index",
                content_markdown="# Previous",
            ),
        )
        session.commit()

    response = client.post("/api/projects/orders/documents/sync-local", json={})

    assert response.status_code == 400
    assert "doc_id" in response.json()["detail"]
    assert "docs/broken.md" in response.json()["detail"]
    with testing_session() as session:
        documents = session.scalars(select(Document)).all()
        assert [document.id for document in documents] == ["previous-entry"]
        project = session.scalar(select(Project).where(Project.slug == "orders"))
        assert project is not None
        assert project.last_sync_status == "failed"
        assert project.last_synced_at is not None
        assert project.last_synced_at.replace(tzinfo=None) == last_success.replace(tzinfo=None)
        assert project.last_sync_summary == {"indexed": 1}


def test_sync_reports_duplicate_doc_ids_with_conflicting_sources(tmp_path, monkeypatch) -> None:
    documents_root = tmp_path / "documents"
    project_docs = documents_root / "order-docs"
    _write_document(
        project_docs / "AGENTS.md",
        doc_id="duplicate-id",
        title="Orders entry",
        body="Entry",
    )
    _write_document(
        project_docs / "docs" / "duplicate.md",
        doc_id="duplicate-id",
        title="Duplicate",
        body="Duplicate id",
    )
    client, testing_session = _client(monkeypatch, documents_root)
    with testing_session() as session:
        session.add(
            Project(
                slug="orders",
                name="Orders",
                root_path="/srv/projects/orders",
                docs_path="order-docs",
            )
        )
        session.commit()

    response = client.post("/api/projects/orders/documents/sync-local", json={})

    assert response.status_code == 400
    assert "duplicate-id" in response.json()["detail"]
    assert "AGENTS.md" in response.json()["detail"]
    assert "docs/duplicate.md" in response.json()["detail"]


def test_sync_rejects_doc_id_owned_by_another_project(tmp_path, monkeypatch) -> None:
    documents_root = tmp_path / "documents"
    project_docs = documents_root / "order-docs"
    _write_document(
        project_docs / "AGENTS.md",
        doc_id="shared-entry",
        title="Orders entry",
        body="Entry",
    )
    (project_docs / "docs").mkdir()
    client, testing_session = _client(monkeypatch, documents_root)
    with testing_session() as session:
        owner = Project(slug="owner", name="Owner", root_path="/srv/projects/owner")
        orders = Project(
            slug="orders",
            name="Orders",
            root_path="/srv/projects/orders",
            docs_path="order-docs",
        )
        session.add_all([owner, orders])
        session.flush()
        upsert_document(
            session,
            project=owner,
            document=DocumentCreate(
                id="shared-entry",
                title="Owned entry",
                source_path="AGENTS.md",
                doc_type="agent_index",
                content_markdown="# Owned",
            ),
        )
        session.commit()

    response = client.post("/api/projects/orders/documents/sync-local", json={})

    assert response.status_code == 400
    assert "shared-entry" in response.json()["detail"]
    assert "owner" in response.json()["detail"]


def test_prune_keeps_retrieval_hit_document_as_tombstone(tmp_path, monkeypatch) -> None:
    documents_root = tmp_path / "documents"
    project_docs = documents_root / "order-docs"
    _write_document(
        project_docs / "AGENTS.md",
        doc_id="orders-entry",
        title="Orders entry",
        body="[Business](./docs/business.md)",
    )
    _write_document(
        project_docs / "docs" / "business.md",
        doc_id="orders-business",
        title="Orders business",
        body="Details",
    )
    client, testing_session = _client(monkeypatch, documents_root)
    with testing_session() as session:
        session.add(
            Project(
                slug="orders",
                name="Orders",
                root_path="/srv/projects/orders",
                docs_path="order-docs",
            )
        )
        session.commit()
    assert client.post("/api/projects/orders/documents/sync-local", json={}).status_code == 200

    with testing_session() as session:
        project = session.scalar(select(Project).where(Project.slug == "orders"))
        assert project is not None
        trace = Trace(id="ctx_history", project_id=project.id, task="Historical task")
        session.add(trace)
        session.flush()
        session.add(
            RetrievalHit(
                trace_id=trace.id,
                document_id="orders-business",
                rank=1,
                score=1,
                reason="Historical candidate",
                was_returned=True,
            )
        )
        session.commit()

    _write_document(
        project_docs / "AGENTS.md",
        doc_id="orders-entry",
        title="Orders entry",
        body="Business was removed",
    )
    (project_docs / "docs" / "business.md").unlink()

    response = client.post("/api/projects/orders/documents/sync-local", json={})

    assert response.status_code == 200
    assert response.json()["pruned_count"] == 1
    assert response.json()["pruned_document_ids"] == ["orders-business"]
    with testing_session() as session:
        tombstone = session.scalar(select(Document).where(Document.id == "orders-business"))
        assert tombstone is not None
        assert tombstone.status == "removed"
        assert tombstone.is_reachable is False
        assert tombstone.graph_depth is None
        hit = session.scalar(
            select(RetrievalHit).where(RetrievalHit.document_id == "orders-business")
        )
        assert hit is not None
