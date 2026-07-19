from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.config import settings
from context_router.db.models import Base, Document, Project
from context_router.db.session import get_session
from context_router.main import create_app
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_store import upsert_document


def test_upsert_document_replaces_document_content_when_content_changes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(slug="my-app", name="My App")
        session.add(project)
        session.flush()

        first = upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="payments-runbook",
                title="Payments runbook",
                source_path="docs/payments.md",
                doc_type="runbook",
                area="payments",
                tags=["payments"],
                content_markdown="# Payments\nFirst version.",
            ),
        )
        second = upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="payments-runbook",
                title="Payments runbook",
                source_path="docs/payments.md",
                doc_type="runbook",
                area="payments",
                tags=["payments", "updated"],
                content_markdown="# Payments\nSecond version.\n\n## Tests\nRun payment tests.",
            ),
        )
        saved = session.scalar(select(Document).where(Document.id == "payments-runbook"))

        assert first.status == "active"
        assert second.status == "active"
        assert saved is not None
        assert saved.tags == ["payments", "updated"]
        assert (
            saved.content_markdown == "# Payments\nSecond version.\n\n## Tests\nRun payment tests."
        )


def test_create_document_api_stores_document_and_returns_status() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    with TestingSession() as session:
        session.add(Project(slug="my-app", name="My App"))
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.post(
        "/api/projects/my-app/documents",
        json={
            "id": "build-runbook",
            "title": "Build runbook",
            "source_path": "docs/build.md",
            "doc_type": "test_command",
            "area": "build",
            "tags": ["build", "test"],
            "content_markdown": "# Build\nRun make test.\n\n## Lint\nRun make lint.",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": "build-runbook",
        "status": "active",
    }


def test_list_documents_returns_metadata() -> None:
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
                id="build-runbook",
                title="Build runbook",
                source_path="docs/build.md",
                doc_type="test_command",
                area="build",
                tags=["build", "test"],
                content_markdown="# Build\nRun make test.\n\n## Lint\nRun make lint.",
            ),
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.get("/api/documents", params={"project": "my-app"})

    assert response.status_code == 200
    assert response.json()["documents"] == [
        {
            "id": "build-runbook",
            "project_slug": "my-app",
            "title": "Build runbook",
            "source_path": "docs/build.md",
            "doc_type": "test_command",
            "area": "build",
            "tags": ["build", "test"],
            "status": "active",
            "links": [],
        }
    ]


def test_sync_local_documents_indexes_frontmatter_and_markdown_links(tmp_path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    documents_root = tmp_path / "documents"
    project_root = documents_root / "my-app-docs"
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (project_root / "AGENTS.md").write_text(
        """---
doc_id: root-index
title: Root Index
doc_type: agent_index
area: agent
tags: [agent, index]
---

# Root Index

- [Payments](./docs/payments.md)
""",
        encoding="utf-8",
    )
    (docs_dir / "payments.md").write_text(
        """---
doc_id: payments-runbook
title: Payments Runbook
doc_type: runbook
area: payments
tags: [payments]
---

# Payments Runbook

Run payment checks.
""",
        encoding="utf-8",
    )

    with TestingSession() as session:
        session.add(Project(slug="my-app", name="My App", docs_path="my-app-docs"))
        session.commit()

    monkeypatch.setattr(settings, "documents_container_root", str(documents_root))

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    sync_response = client.post(
        "/api/projects/my-app/documents/sync-local",
        json={"docs_dir": str(docs_dir), "prune": True},
    )

    assert sync_response.status_code == 200
    assert sync_response.json()["indexed_document_ids"] == [
        "root-index",
        "payments-runbook",
    ]
    assert sync_response.json()["link_count"] == 1

    documents_response = client.get("/api/documents", params={"project": "my-app"})

    assert documents_response.status_code == 200
    documents = {document["id"]: document for document in documents_response.json()["documents"]}
    assert documents["root-index"]["links"] == [
        {
            "target_document_id": "payments-runbook",
            "target_path": "docs/payments.md",
            "label": "Payments",
            "relation_type": "markdown_link",
            "sort_order": 0,
        }
    ]

    read_response = client.get("/api/documents/root-index", params={"untracked": True})

    assert read_response.status_code == 200
    assert read_response.json()["content_markdown"].startswith("# Root Index")
    assert "doc_id:" not in read_response.json()["content_markdown"]


def test_sync_local_documents_ignores_requested_path_and_uses_mapping(
    tmp_path, monkeypatch
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    documents_root = tmp_path / "documents"
    project_root = documents_root / "target-project"
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (project_root / "AGENTS.md").write_text(
        """---
doc_id: root-index
title: Root Index
doc_type: agent_index
area: agent
tags: [agent]
---

# Root Index
""",
        encoding="utf-8",
    )

    with TestingSession() as session:
        session.add(
            Project(
                slug="my-app",
                name="My App",
                root_path="/srv/projects/my-app",
                docs_path="target-project",
            )
        )
        session.commit()

    monkeypatch.setattr(settings, "documents_container_root", str(documents_root))

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    sync_response = client.post(
        "/api/projects/my-app/documents/sync-local",
        json={"docs_dir": "docs", "prune": True},
    )

    assert sync_response.status_code == 200
    assert sync_response.json()["docs_path"] == "target-project"

    documents_response = client.get("/api/documents", params={"project": "my-app"})

    assert documents_response.status_code == 200
    assert documents_response.json()["documents"][0]["source_path"] == "AGENTS.md"


def test_sync_project_root_only_reads_root_agent_and_docs_tree(tmp_path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    documents_root = tmp_path / "documents"
    project_root = documents_root / "target-project"
    docs_dir = project_root / "docs"
    submodule_dir = project_root / "submodule"
    docs_dir.mkdir(parents=True)
    submodule_dir.mkdir()
    (project_root / "AGENTS.md").write_text(
        """---
doc_id: root-agent
title: Root Agent
doc_type: agent_index
---

# Root Agent

[Second](./docs/second.md)
""",
        encoding="utf-8",
    )
    (docs_dir / "second.md").write_text(
        """---
doc_id: second-doc
title: Second Doc
doc_type: runbook
---

# Second Doc
""",
        encoding="utf-8",
    )
    (submodule_dir / "AGENTS.md").write_text(
        """---
doc_id: should-not-sync
title: Should Not Sync
doc_type: agent_index
---

# Should Not Sync
""",
        encoding="utf-8",
    )

    with TestingSession() as session:
        session.add(
            Project(
                slug="my-app",
                name="My App",
                root_path="/srv/projects/my-app",
                docs_path="target-project",
            )
        )
        session.commit()

    monkeypatch.setattr(settings, "documents_container_root", str(documents_root))

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    sync_response = client.post(
        "/api/projects/my-app/documents/sync-local",
        json={"docs_dir": ".", "prune": True},
    )

    assert sync_response.status_code == 200
    assert sync_response.json()["indexed_document_ids"] == ["root-agent", "second-doc"]


def test_list_documents_project_filter_includes_child_projects() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    with TestingSession() as session:
        parent = Project(slug="workspace", name="Workspace")
        other = Project(slug="other", name="Other")
        session.add_all([parent, other])
        session.flush()
        child = Project(slug="workspace-api", name="Workspace API", parent_project_id=parent.id)
        session.add(child)
        session.flush()
        upsert_document(
            session,
            project=parent,
            document=DocumentCreate(
                id="workspace-index",
                title="Workspace index",
                source_path="docs/index.md",
                doc_type="readme",
                area="agent",
                tags=["workspace"],
                content_markdown="# Workspace\nTop-level notes.",
            ),
        )
        upsert_document(
            session,
            project=child,
            document=DocumentCreate(
                id="api-runbook",
                title="API runbook",
                source_path="api/docs/runbook.md",
                doc_type="runbook",
                area="backend",
                tags=["api"],
                content_markdown="# API\nChild project notes.",
            ),
        )
        upsert_document(
            session,
            project=other,
            document=DocumentCreate(
                id="other-runbook",
                title="Other runbook",
                source_path="docs/other.md",
                doc_type="runbook",
                area="other",
                tags=["other"],
                content_markdown="# Other\nUnrelated notes.",
            ),
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.get("/api/documents", params={"project": "workspace"})

    assert response.status_code == 200
    assert [document["id"] for document in response.json()["documents"]] == [
        "api-runbook",
        "workspace-index",
    ]


def test_list_documents_filters_by_project_area_type_tag_and_status() -> None:
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
                tags=["payments", "webhook"],
                content_markdown="# Payments\nRun payment checks.",
            ),
        )
        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="frontend-notes",
                title="Frontend notes",
                source_path="docs/frontend.md",
                doc_type="architecture",
                area="frontend",
                tags=["react"],
                content_markdown="# Frontend\nReact notes.",
            ),
        )
        stale_document = upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id="old-payments-notes",
                title="Old payments notes",
                source_path="docs/old-payments.md",
                doc_type="runbook",
                area="payments",
                tags=["payments", "legacy"],
                content_markdown="# Old Payments\nLegacy notes.",
            ),
        )
        saved_stale = session.get(Document, stale_document.id)
        assert saved_stale is not None
        saved_stale.status = "stale"
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.get(
        "/api/documents",
        params={
            "project": "my-app",
            "area": "payments",
            "doc_type": "runbook",
            "tag": "webhook",
            "status": "active",
        },
    )

    assert response.status_code == 200
    documents = response.json()["documents"]
    assert [document["id"] for document in documents] == ["payments-runbook"]
