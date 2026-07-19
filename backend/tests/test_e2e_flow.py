from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.db.models import Base
from context_router.db.session import get_session
from context_router.main import create_app

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_docs"


def test_e2e_ingest_prepare_read_and_view_trace() -> None:
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

    project_response = client.post(
        "/api/projects",
        json={
            "slug": "sample-app",
            "name": "Sample App",
            "root_path": "/repo/sample-app",
            "description": "Fixture project",
        },
    )
    assert project_response.status_code == 200

    docs = [
        (
            "payments-webhook-timeout",
            "Payments webhook timeout",
            "debugging",
            "payments",
            ["payments", "webhook", "timeout"],
            "payments-webhook-timeout.md",
        ),
        (
            "build-failure-runbook",
            "Build failure runbook",
            "test_command",
            "build",
            ["build", "test"],
            "build-failure-runbook.md",
        ),
        (
            "frontend-layout-notes",
            "Frontend layout notes",
            "architecture",
            "frontend",
            ["frontend", "dashboard"],
            "frontend-layout-notes.md",
        ),
        (
            "unrelated-marketing-copy",
            "Marketing copy",
            "decision",
            "marketing",
            ["campaign"],
            "unrelated-marketing-copy.md",
        ),
    ]

    for document_id, title, doc_type, area, tags, filename in docs:
        response = client.post(
            "/api/projects/sample-app/documents",
            json={
                "id": document_id,
                "title": title,
                "source_path": f"docs/{filename}",
                "doc_type": doc_type,
                "area": area,
                "tags": tags,
                "content_markdown": (FIXTURE_DIR / filename).read_text(encoding="utf-8"),
            },
        )
        assert response.status_code == 200

    prepare_response = client.post(
        "/api/context/prepare",
        json={
            "project": "sample-app",
            "task": "fix payments webhook timeout",
            "area": "payments",
            "cwd": "/repo/sample-app",
            "entrypoint_path": "AI_CONTEXT_INDEX.md",
            "entrypoint_rule": "payments tasks",
            "source": "mcp",
            "max_documents": 3,
        },
    )
    assert prepare_response.status_code == 200
    prepare_body = prepare_response.json()
    trace_id = prepare_body["trace_id"]
    document_ids = [document["document_id"] for document in prepare_body["documents"]]
    assert document_ids[0] == "payments-webhook-timeout"
    assert "unrelated-marketing-copy" not in document_ids

    read_response = client.get(
        "/api/documents/payments-webhook-timeout",
        params={
            "trace_id": trace_id,
            "source": "mcp",
        },
    )
    assert read_response.status_code == 200
    assert "Fix Checklist" in read_response.json()["content_markdown"]

    trace_response = client.get(f"/api/traces/{trace_id}")
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["area"] == "payments"
    assert trace["entrypoint_path"] == "AI_CONTEXT_INDEX.md"
    assert trace["entrypoint_rule"] == "payments tasks"
    assert trace["retrieval_hits"][0]["document_id"] == "payments-webhook-timeout"
    assert [event["event_type"] for event in trace["events"]] == ["prepare", "read"]
