from fastapi.testclient import TestClient

from context_router.main import create_app


def test_health_returns_service_status() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "agent-context-router",
        "status": "ok",
    }
