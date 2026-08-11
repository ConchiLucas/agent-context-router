from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.api.nacos_profiles import router
from context_router.repositories.nacos_profile_repository import (
    InMemoryNacosProfileRepository,
)


class _WorkspaceRepository:
    def get_workspace(self, workspace_id: str) -> object:
        assert workspace_id == "workspace-1"
        return object()


def _client() -> TestClient:
    app = FastAPI()
    app.state.nacos_profile_repository = InMemoryNacosProfileRepository()
    app.state.workspace_repository = _WorkspaceRepository()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _payload() -> dict[str, object]:
    return {
        "base_url": "http://host.docker.internal:9102/",
        "namespace_id": "test-namespace",
        "username": "nacos",
        "password": "nacos-profile-password",
        "request_timeout_ms": 5000,
        "components": [
            {
                "id": "redis-main",
                "type": "redis",
                "sources": [{"data_id": "c12-common.yaml", "group": "DEFAULT_GROUP"}],
                "fields": {
                    "host": {"paths": ["spring.data.redis.host"]},
                    "password": {
                        "paths": ["spring.data.redis.password"],
                        "secret": True,
                    },
                },
            }
        ],
    }


def test_nacos_profile_api_never_returns_stored_password() -> None:
    with _client() as client:
        saved = client.put(
            "/api/workspaces/workspace-1/nacos-profiles/test",
            json=_payload(),
        )
        listed = client.get("/api/workspaces/workspace-1/nacos-profiles")

    assert saved.status_code == 200
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "no-store"
    assert saved.json()["base_url"] == "http://host.docker.internal:9102"
    assert saved.json()["password_configured"] is True
    serialized = f"{saved.json()} {listed.json()}"
    assert "nacos-profile-password" not in serialized
    assert listed.json()["profiles"][0]["profile_key"] == "test"


def test_nacos_profile_api_rejects_embedded_url_credentials_and_duplicate_components() -> None:
    with _client() as client:
        payload = _payload()
        payload["base_url"] = "http://user:password@localhost:8848"
        invalid_url = client.put(
            "/api/workspaces/workspace-1/nacos-profiles/default",
            json=payload,
        )
        payload = _payload()
        payload["components"] = [payload["components"][0], payload["components"][0]]  # type: ignore[index]
        duplicates = client.put(
            "/api/workspaces/workspace-1/nacos-profiles/default",
            json=payload,
        )

    assert invalid_url.status_code == 422
    assert duplicates.status_code == 422
