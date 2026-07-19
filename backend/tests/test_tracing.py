from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.config import settings
from context_router.db.models import Base, Project, Trace, TraceEvent
from context_router.db.session import get_session
from context_router.main import create_app


def _test_client(testing_session):
    def override_session() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_trace_detail_records_objective_mcp_lifecycle(tmp_path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    documents_root = tmp_path / "documents"
    project_docs = documents_root / "my-app-docs"
    (project_docs / "docs").mkdir(parents=True)
    (project_docs / "AGENTS.md").write_text(
        """---
doc_id: my-app-entry
title: My App entry
---

# My App entry

Project rules.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "documents_container_root", str(documents_root))
    with testing_session() as session:
        session.add(
            Project(
                slug="my-app",
                name="My App",
                root_path="/repo/my-app",
                docs_path="my-app-docs",
            )
        )
        session.commit()
    client = _test_client(testing_session)
    assert client.post("/api/projects/my-app/documents/sync-local", json={}).status_code == 200

    prepare_response = client.post(
        "/api/context/prepare",
        json={
            "project": "my-app",
            "task": "fix payments webhook timeout",
            "area": "payments",
            "cwd": "/repo/my-app",
            "entrypoint_path": "AGENTS.md",
            "entrypoint_rule": "mapped entry",
            "route_hint": "payments",
            "source": "mcp",
            "agent_name": "codex",
            "max_documents": 2,
        },
    )
    assert prepare_response.status_code == 200
    trace_id = prepare_response.json()["trace_id"]
    read_response = client.get(
        "/api/documents/my-app-entry",
        params={"trace_id": trace_id, "source": "mcp"},
    )
    assert read_response.status_code == 200

    with testing_session() as session:
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
    assert detail["entrypoint_path"] == "AGENTS.md"
    assert detail["entrypoint_rule"] == "mapped entry"
    assert detail["route_hint"] == "payments"
    assert detail["source"] == "mcp"
    assert detail["agent_name"] == "codex"
    assert detail["retrieval_hits"][0]["document_id"] == "my-app-entry"
    assert detail["retrieval_hits"][0]["document_title"] == "My App entry"
    assert "feedback" not in detail["retrieval_hits"][0]
    assert [event["event_type"] for event in detail["events"]] == ["prepare", "read"]
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
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    client = _test_client(testing_session)

    usage_response = client.get("/api/usage/cards")
    feedback_response = client.post(
        "/api/traces/ctx_missing/feedback",
        json={"document_id": "missing-doc", "feedback": "useful"},
    )

    assert usage_response.status_code == 404
    assert feedback_response.status_code == 404


def test_trace_list_project_filter_includes_child_projects() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    with testing_session() as session:
        parent = Project(slug="workspace", name="Workspace")
        other = Project(slug="other", name="Other")
        session.add_all([parent, other])
        session.flush()
        child = Project(
            slug="workspace-api",
            name="Workspace API",
            parent_project_id=parent.id,
        )
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
    client = _test_client(testing_session)

    response = client.get("/api/traces", params={"project": "workspace"})

    assert response.status_code == 200
    assert {trace["id"] for trace in response.json()["traces"]} == {
        "ctx_parent_001",
        "ctx_child_001",
    }
