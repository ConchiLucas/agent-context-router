from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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
        }
    ]


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
