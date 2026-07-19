from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.config import settings
from context_router.db.models import Base
from context_router.db.session import get_session
from context_router.main import create_app

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_docs"


def _mapped_markdown(doc_id: str, title: str, content: str) -> str:
    return f"---\ndoc_id: {doc_id}\ntitle: {title}\n---\n\n{content}"


def test_e2e_map_sync_prepare_read_tree_and_view_trace(tmp_path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    documents_root = tmp_path / "documents"
    project_docs = documents_root / "sample-docs"
    docs_dir = project_docs / "docs"
    docs_dir.mkdir(parents=True)
    (project_docs / "AGENTS.md").write_text(
        _mapped_markdown(
            "sample-entry",
            "Sample entry",
            "# Sample entry\n\n[Payments](./docs/payments.md)\n",
        ),
        encoding="utf-8",
    )
    (docs_dir / "payments.md").write_text(
        _mapped_markdown(
            "payments-webhook-timeout",
            "Payments webhook timeout",
            (FIXTURE_DIR / "payments-webhook-timeout.md").read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "documents_container_root", str(documents_root))

    def override_session() -> Generator[Session, None, None]:
        with testing_session() as session:
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
    mapping_response = client.put(
        "/api/projects/sample-app/document-mapping",
        json={"docs_path": "sample-docs"},
    )
    assert mapping_response.status_code == 200
    sync_response = client.post("/api/projects/sample-app/documents/sync-local", json={})
    assert sync_response.status_code == 200
    assert sync_response.json()["reachable_count"] == 2

    prepare_response = client.post(
        "/api/context/prepare",
        json={
            "task": "fix payments webhook timeout",
            "area": "payments",
            "cwd": "/repo/sample-app",
            "entrypoint_path": "AGENTS.md",
            "entrypoint_rule": "mapped project entry",
            "source": "mcp",
        },
    )
    assert prepare_response.status_code == 200
    prepare_body = prepare_response.json()
    trace_id = prepare_body["trace_id"]
    assert [document["document_id"] for document in prepare_body["documents"]] == ["sample-entry"]

    entry_response = client.get(
        "/api/documents/sample-entry",
        params={"trace_id": trace_id, "source": "mcp"},
    )
    assert entry_response.status_code == 200
    assert entry_response.json()["links"][0]["target_document_id"] == ("payments-webhook-timeout")
    child_response = client.get(
        "/api/documents/payments-webhook-timeout",
        params={
            "trace_id": trace_id,
            "parent_document_id": "sample-entry",
            "source": "mcp",
        },
    )
    assert child_response.status_code == 200
    assert "Fix Checklist" in child_response.json()["content_markdown"]

    trace_response = client.get(f"/api/traces/{trace_id}")
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["area"] == "payments"
    assert trace["entrypoint_path"] == "AGENTS.md"
    assert trace["retrieval_hits"][0]["document_id"] == "sample-entry"
    assert [event["event_type"] for event in trace["events"]] == [
        "prepare",
        "read",
        "read",
    ]
    assert trace["events"][2]["payload"]["parent_document_id"] == "sample-entry"
