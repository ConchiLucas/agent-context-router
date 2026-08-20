from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.api.database_environments import router
from context_router.repositories.database_environment_repository import (
    InMemoryDatabaseEnvironmentRepository,
)


class _WorkspaceRepository:
    def get_workspace(self, workspace_id: str) -> object:
        assert workspace_id == "workspace-1"
        return object()


def _client() -> TestClient:
    app = FastAPI()
    app.state.workspace_repository = _WorkspaceRepository()
    app.state.database_environment_repository = InMemoryDatabaseEnvironmentRepository()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_workspace_starts_with_local_only_and_can_add_its_own_environment() -> None:
    with _client() as client:
        initial = client.get("/api/workspaces/workspace-1/environments")
        saved = client.put(
            "/api/workspaces/workspace-1/environments/test",
            json={"display_name": "测试环境", "sort_order": 10},
        )
        listing = client.get("/api/workspaces/workspace-1/environments")

    assert initial.status_code == 200
    assert initial.json()["default_environment"] == "local"
    assert [item["key"] for item in initial.json()["environments"]] == ["local"]
    assert saved.status_code == 200
    assert saved.json() == {
        "key": "test",
        "display_name": "测试环境",
        "is_default": False,
        "sort_order": 10,
    }
    assert [item["key"] for item in listing.json()["environments"]] == ["local", "test"]


def test_local_environment_cannot_be_deleted() -> None:
    with _client() as client:
        response = client.delete("/api/workspaces/workspace-1/environments/local")

    assert response.status_code == 400
    assert "不能删除" in response.json()["detail"]
