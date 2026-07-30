from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.api.database_environments import router
from context_router.repositories.database_environment_repository import (
    DatabaseEnvironmentMappingWrite,
    InMemoryDatabaseEnvironmentRepository,
)


class _WorkspaceRepository:
    def get_workspace(self, workspace_id: str) -> object:
        assert workspace_id == "workspace-1"
        return object()


def _client(*, with_database_mapping: bool = True) -> TestClient:
    repository = InMemoryDatabaseEnvironmentRepository()
    if with_database_mapping:
        repository.replace_mappings(
            workspace_id="workspace-1",
            expected_revision=0,
            mappings=[
                DatabaseEnvironmentMappingWrite(
                    id="mapping-1",
                    workspace_id="workspace-1",
                    project_id="project-1",
                    logical_name="admin",
                    mcp_alias="admin_db",
                    test_link_id="test-link",
                    uat_link_id="uat-link",
                )
            ],
        )
    app = FastAPI()
    app.state.database_environment_repository = repository
    app.state.workspace_repository = _WorkspaceRepository()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_environment_config_get_and_put_return_active_json() -> None:
    with _client() as client:
        initial = client.get("/api/workspaces/workspace-1/environment-config")
        assert initial.status_code == 200
        assert initial.json() == {
            "workspace_id": "workspace-1",
            "configured": False,
            "active_environment": "uat",
            "revision": 1,
            "environments": {"test": {}, "uat": {}},
            "active_config": None,
        }
        assert initial.headers["cache-control"] == "no-store"

        saved = client.put(
            "/api/workspaces/workspace-1/environment-config",
            json={
                "expected_revision": 1,
                "environments": {
                    "test": {
                        "services": [
                            {"kind": "mq", "nameServer": "test-mq:9876"},
                            {"kind": "es", "endpoint": "http://test-es:9200"},
                        ]
                    },
                    "uat": {
                        "mq": {"nameServer": "uat-mq:9876"},
                        "minio": None,
                    },
                },
            },
        )

        assert saved.status_code == 200
        body = saved.json()
        assert body["revision"] == 2
        assert body["active_environment"] == "uat"
        assert body["active_config"] == {
            "mq": {"nameServer": "uat-mq:9876"},
            "minio": None,
        }
        assert body["environments"]["test"]["services"][0]["kind"] == "mq"


def test_environment_config_put_rejects_stale_revision() -> None:
    with _client() as client:
        payload = {
            "expected_revision": 1,
            "environments": {"test": {}, "uat": {}},
        }
        assert (
            client.put(
                "/api/workspaces/workspace-1/environment-config",
                json=payload,
            ).status_code
            == 200
        )

        conflict = client.put(
            "/api/workspaces/workspace-1/environment-config",
            json=payload,
        )

        assert conflict.status_code == 409
        assert "刷新后重试" in conflict.json()["detail"]


def test_environment_config_can_be_created_without_database_mappings() -> None:
    with _client(with_database_mapping=False) as client:
        initial = client.get("/api/workspaces/workspace-1/environment-config")
        assert initial.status_code == 200
        assert initial.json()["configured"] is False
        assert initial.json()["revision"] == 0

        saved = client.put(
            "/api/workspaces/workspace-1/environment-config",
            json={
                "expected_revision": 0,
                "environments": {
                    "test": {"minio": {"bucket": "test"}},
                    "uat": {"minio": {"bucket": "uat"}},
                },
            },
        )

        assert saved.status_code == 200
        assert saved.json()["configured"] is True
        assert saved.json()["active_environment"] == "uat"
        assert saved.json()["revision"] == 1
        assert saved.json()["active_config"] == {"minio": {"bucket": "uat"}}


def test_environment_config_rejects_non_object_and_unsafe_payloads() -> None:
    with _client(with_database_mapping=False) as client:
        non_object = client.put(
            "/api/workspaces/workspace-1/environment-config",
            json={
                "expected_revision": 0,
                "environments": {"test": [], "uat": {}},
            },
        )
        assert non_object.status_code == 422

        unsafe_integer = client.put(
            "/api/workspaces/workspace-1/environment-config",
            json={
                "expected_revision": 0,
                "environments": {
                    "test": {"sequence": 9_007_199_254_740_992},
                    "uat": {},
                },
            },
        )
        assert unsafe_integer.status_code == 400
        assert "字符串" in unsafe_integer.json()["detail"]

        oversized = client.put(
            "/api/workspaces/workspace-1/environment-config",
            json={
                "expected_revision": 0,
                "environments": {
                    "test": {"value": "x" * (256 * 1024)},
                    "uat": {},
                },
            },
        )
        assert oversized.status_code == 400
        assert "256 KiB" in oversized.json()["detail"]
