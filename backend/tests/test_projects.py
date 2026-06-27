from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.db.models import Base, Project
from context_router.db.session import get_session
from context_router.main import create_app
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_store import upsert_document


def test_create_project_api_persists_and_returns_project() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.post(
        "/api/projects",
        json={
            "slug": "my-app",
            "name": "My App",
            "root_path": "/repo/my-app",
            "description": "Main app",
        },
    )

    assert response.status_code == 200
    assert response.json()["slug"] == "my-app"


def test_list_and_get_project_include_document_counts_and_routing_template() -> None:
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
                id="payments-runbook",
                title="Payments runbook",
                source_path="docs/payments.md",
                doc_type="runbook",
                area="payments",
                tags=["payments"],
                content_markdown="# Payments\nRun tests.",
            ),
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    list_response = client.get("/api/projects")
    assert list_response.status_code == 200
    assert list_response.json()["projects"][0]["slug"] == "my-app"
    assert list_response.json()["projects"][0]["document_count"] == 1

    detail_response = client.get("/api/projects/my-app")
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["slug"] == "my-app"
    assert body["document_count"] == 1
    assert "ctx prepare --project my-app" in body["routing_template"]
