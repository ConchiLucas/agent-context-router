from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.db.models import Base
from context_router.db.session import get_session
from context_router.main import create_app


def test_usage_cards_seed_default_ctx_card() -> None:
    client = _client()

    response = client.get("/api/usage/cards")

    assert response.status_code == 200
    cards = response.json()["cards"]
    assert len(cards) == 1
    assert cards[0]["slug"] == "ctx-session-usage"
    assert cards[0]["is_builtin"] is True
    assert "SESSION_ID" in cards[0]["content_markdown"]
    assert '"$CTX" read <doc-id> --session "$SESSION_ID"' in cards[0]["content_markdown"]


def test_usage_cards_can_be_created_and_updated() -> None:
    client = _client()

    create_response = client.post(
        "/api/usage/cards",
        json={
            "title": "Development Rules",
            "description": "How to work in this repo.",
            "content_markdown": "# Development Rules\n\nUse Docker Compose.",
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["slug"] == "development-rules"
    assert created["is_builtin"] is False

    update_response = client.put(
        "/api/usage/cards/development-rules",
        json={
            "title": "Development Rules",
            "description": "Updated guidance.",
            "content_markdown": "# Development Rules\n\nRun tests in Docker Compose.",
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["description"] == "Updated guidance."
    assert "Run tests" in updated["content_markdown"]


def test_builtin_usage_card_cannot_be_deleted() -> None:
    client = _client()
    client.get("/api/usage/cards")

    response = client.delete("/api/usage/cards/ctx-session-usage")

    assert response.status_code == 400


def _client() -> TestClient:
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
    return TestClient(app)
