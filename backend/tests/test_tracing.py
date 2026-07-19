from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.db.models import Base, Project, Trace, TraceEvent
from context_router.db.session import get_session
from context_router.main import create_app
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_store import upsert_document


def test_trace_detail_records_objective_mcp_lifecycle() -> None:
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
                tags=["webhook", "timeout"],
                content_markdown="# Payments\nWebhook timeout fixes require retry tests.",
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
                content_markdown="# Frontend\nReact layout notes.",
            ),
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    prepare_response = client.post(
        "/api/context/prepare",
        json={
            "project": "my-app",
            "task": "fix payments webhook timeout",
            "area": "payments",
            "cwd": "/repo/my-app",
            "entrypoint_path": "AI_CONTEXT_INDEX.md",
            "entrypoint_rule": "payments tasks",
            "route_hint": "payments",
            "source": "mcp",
            "agent_name": "codex",
            "max_documents": 2,
        },
    )
    assert prepare_response.status_code == 200
    trace_id = prepare_response.json()["trace_id"]

    read_response = client.get(
        "/api/documents/payments-runbook",
        params={"trace_id": trace_id, "source": "mcp"},
    )
    assert read_response.status_code == 200

    with TestingSession() as session:
        session.add(
            TraceEvent(
                trace_id=trace_id,
                event_type="feedback",
                payload={"duration_ms": 5000, "feedback": "historical"},
            )
        )
        session.commit()

    detail_response = client.get(f"/api/traces/{trace_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()

    assert detail["id"] == trace_id
    assert detail["project"]["slug"] == "my-app"
    assert detail["task"] == "fix payments webhook timeout"
    assert detail["area"] == "payments"
    assert detail["entrypoint_path"] == "AI_CONTEXT_INDEX.md"
    assert detail["entrypoint_rule"] == "payments tasks"
    assert detail["route_hint"] == "payments"
    assert detail["source"] == "mcp"
    assert detail["agent_name"] == "codex"
    assert detail["retrieval_hits"][0]["document_id"] == "payments-runbook"
    assert detail["retrieval_hits"][0]["document_title"] == "Payments runbook"
    assert "feedback" not in detail["retrieval_hits"][0]
    assert detail["events"][0]["event_type"] == "prepare"
    assert [event["event_type"] for event in detail["events"]] == [
        "prepare",
        "read",
    ]
    expected_mcp_duration_ms = round(
        sum(event["payload"]["duration_ms"] for event in detail["events"]),
        3,
    )

    list_response = client.get("/api/traces")
    assert list_response.status_code == 200
    traces = list_response.json()["traces"]
    assert traces[0]["id"] == trace_id
    assert traces[0]["project_slug"] == "my-app"
    assert traces[0]["area"] == "payments"
    assert traces[0]["source"] == "mcp"
    assert traces[0]["agent_name"] == "codex"
    assert traces[0]["mcp_duration_ms"] == expected_mcp_duration_ms
    assert "feedback_count" not in traces[0]
    assert traces[0]["returned_document_count"] == 1
    assert traces[0]["read_event_count"] == 1

    area_response = client.get("/api/traces", params={"area": "payments"})
    assert area_response.status_code == 200
    assert area_response.json()["traces"][0]["id"] == trace_id

    source_response = client.get("/api/traces", params={"source": "mcp"})
    assert source_response.status_code == 200
    assert source_response.json()["traces"][0]["id"] == trace_id


def test_usage_and_feedback_endpoints_are_removed() -> None:
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

    usage_response = client.get("/api/usage/cards")
    feedback_response = client.post(
        "/api/traces/ctx_missing/feedback",
        json={
            "document_id": "missing-doc",
            "feedback": "useful",
        },
    )

    assert usage_response.status_code == 404
    assert feedback_response.status_code == 404


def test_trace_list_project_filter_includes_child_projects() -> None:
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
        session.add_all(
            [
                Trace(id="ctx_parent_001", project_id=parent.id, task="Review workspace"),
                Trace(id="ctx_child_001", project_id=child.id, task="Fix API"),
                Trace(id="ctx_other_001", project_id=other.id, task="Fix other"),
            ]
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with TestingSession() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    response = client.get("/api/traces", params={"project": "workspace"})

    assert response.status_code == 200
    assert {trace["id"] for trace in response.json()["traces"]} == {
        "ctx_parent_001",
        "ctx_child_001",
    }
