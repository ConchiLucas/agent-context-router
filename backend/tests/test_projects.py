from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.db.models import Base, Project, Trace
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


def test_create_project_requires_non_blank_root_path() -> None:
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

    missing_response = client.post(
        "/api/projects",
        json={"slug": "missing-root", "name": "Missing root"},
    )
    blank_response = client.post(
        "/api/projects",
        json={"slug": "blank-root", "name": "Blank root", "root_path": "   "},
    )

    assert missing_response.status_code == 422
    assert blank_response.status_code == 422


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
    assert list_response.json()["projects"][0]["trace_count"] == 0
    assert list_response.json()["projects"][0]["child_project_count"] == 0

    detail_response = client.get("/api/projects/my-app")
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["slug"] == "my-app"
    assert body["document_count"] == 1
    assert body["trace_count"] == 0
    assert body["children"] == []
    assert "prepare_task_context" in body["routing_template"]
    assert "read_context_document" in body["routing_template"]
    assert "ctx " not in body["routing_template"]


def test_project_list_defaults_to_roots_and_detail_includes_children() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    with TestingSession() as session:
        parent = Project(slug="my-workspace", name="My Workspace", root_path="/repo")
        session.add(parent)
        session.flush()

        child = Project(
            slug="my-workspace-api",
            name="My Workspace API",
            root_path="/repo/api",
            parent_project_id=parent.id,
        )
        session.add(child)
        session.flush()

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
                content_markdown="# API\nRun backend tests.",
            ),
        )
        session.add(
            Trace(
                id="ctx_child_001",
                project_id=child.id,
                task="Fix child API",
                source="mcp",
            )
        )
        session.add(
            Trace(
                id="ctx_child_historical",
                project_id=child.id,
                task="Historical CLI task",
                source="cli",
            )
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    root_response = client.get("/api/projects")
    assert root_response.status_code == 200
    root_projects = root_response.json()["projects"]
    assert [project["slug"] for project in root_projects] == ["my-workspace"]
    assert root_projects[0]["document_count"] == 1
    assert root_projects[0]["active_document_count"] == 1
    assert root_projects[0]["trace_count"] == 1
    assert root_projects[0]["child_project_count"] == 1

    all_response = client.get("/api/projects?include_children=true")
    assert all_response.status_code == 200
    assert {project["slug"] for project in all_response.json()["projects"]} == {
        "my-workspace",
        "my-workspace-api",
    }

    detail_response = client.get("/api/projects/my-workspace")
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["slug"] == "my-workspace"
    assert body["document_count"] == 1
    assert body["children"][0]["slug"] == "my-workspace-api"
    assert body["children"][0]["parent_slug"] == "my-workspace"
    assert body["children"][0]["document_count"] == 1
    assert body["children"][0]["trace_count"] == 1
