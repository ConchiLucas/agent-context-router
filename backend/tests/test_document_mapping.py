from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.config import settings
from context_router.db.models import Base, Project
from context_router.db.session import get_session
from context_router.main import create_app


def _mapped_docs_root(tmp_path):
    root = tmp_path / "documents"
    valid = root / "order-docs"
    nested = valid / "docs" / "database"
    nested.mkdir(parents=True)
    (valid / "AGENTS.md").write_text("# Order entry", encoding="utf-8")
    (valid / "docs" / "business.md").write_text("# Business", encoding="utf-8")
    (nested / "schema.md").write_text("# Schema", encoding="utf-8")
    (valid / "README.md").write_text("# Not indexed", encoding="utf-8")
    return root, valid


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


def test_candidates_only_include_valid_direct_document_projects(tmp_path, monkeypatch) -> None:
    root, _valid = _mapped_docs_root(tmp_path)
    used = root / "used-docs"
    (used / "docs").mkdir(parents=True)
    (used / "AGENTS.md").write_text("# Used", encoding="utf-8")
    (root / "missing-agents" / "docs").mkdir(parents=True)
    nested = root / "team" / "nested-docs"
    (nested / "docs").mkdir(parents=True)
    (nested / "AGENTS.md").write_text("# Nested", encoding="utf-8")
    client, testing_session = _client(monkeypatch, root)

    with testing_session() as session:
        session.add(
            Project(
                slug="used-project",
                name="Used project",
                root_path="/srv/projects/used",
                docs_path="used-docs",
            )
        )
        session.commit()

    response = client.get("/api/document-mappings/candidates")

    assert response.status_code == 200
    assert response.json() == {
        "candidates": [
            {
                "docs_path": "order-docs",
                "markdown_count": 3,
                "mapped_project_slug": None,
            },
            {
                "docs_path": "used-docs",
                "markdown_count": 1,
                "mapped_project_slug": "used-project",
            },
        ]
    }


def test_mapping_api_saves_relative_path_and_invalidates_previous_sync(
    tmp_path, monkeypatch
) -> None:
    root, _valid = _mapped_docs_root(tmp_path)
    client, testing_session = _client(monkeypatch, root)

    with testing_session() as session:
        session.add(
            Project(
                slug="orders",
                name="Orders",
                root_path="/srv/projects/orders",
                last_synced_at=datetime.now(UTC),
                last_sync_status="success",
                last_sync_summary={"indexed": 9},
            )
        )
        session.commit()

    response = client.put(
        "/api/projects/orders/document-mapping",
        json={"docs_path": "order-docs"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "project_slug": "orders",
        "docs_path": "order-docs",
        "last_synced_at": None,
        "last_sync_status": "never",
        "last_sync_summary": {},
    }
    with testing_session() as session:
        project = session.scalar(select(Project).where(Project.slug == "orders"))
        assert project is not None
        assert project.docs_path == "order-docs"
        assert project.last_synced_at is None
        assert project.last_sync_summary == {}


@pytest.mark.parametrize("docs_path", ["/absolute/order-docs", "../order-docs"])
def test_mapping_api_rejects_absolute_and_parent_paths(docs_path, tmp_path, monkeypatch) -> None:
    root, _valid = _mapped_docs_root(tmp_path)
    client, testing_session = _client(monkeypatch, root)
    with testing_session() as session:
        session.add(Project(slug="orders", name="Orders", root_path="/srv/projects/orders"))
        session.commit()

    response = client.put(
        "/api/projects/orders/document-mapping",
        json={"docs_path": docs_path},
    )

    assert response.status_code == 400
    assert "relative" in response.json()["detail"].lower()


def test_mapping_api_rejects_symlink_and_occupied_directory(tmp_path, monkeypatch) -> None:
    root, valid = _mapped_docs_root(tmp_path)
    (root / "alias-docs").symlink_to(valid, target_is_directory=True)
    client, testing_session = _client(monkeypatch, root)
    with testing_session() as session:
        session.add_all(
            [
                Project(
                    slug="orders",
                    name="Orders",
                    root_path="/srv/projects/orders",
                ),
                Project(
                    slug="owner",
                    name="Owner",
                    root_path="/srv/projects/owner",
                    docs_path="order-docs",
                ),
            ]
        )
        session.commit()

    symlink_response = client.put(
        "/api/projects/orders/document-mapping",
        json={"docs_path": "alias-docs"},
    )
    occupied_response = client.put(
        "/api/projects/orders/document-mapping",
        json={"docs_path": "order-docs"},
    )

    assert symlink_response.status_code == 400
    assert "symlink" in symlink_response.json()["detail"].lower()
    assert occupied_response.status_code == 409
    assert "owner" in occupied_response.json()["detail"]
