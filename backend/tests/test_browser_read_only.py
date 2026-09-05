from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.middleware.browser_read_only import BrowserReadOnlyMiddleware

FRONTEND_ORIGIN = "http://127.0.0.1:49175"


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        BrowserReadOnlyMiddleware,
        api_prefix="/api",
    )

    @app.get("/api/workspaces")
    def list_workspaces() -> dict[str, bool]:
        return {"read": True}

    @app.post("/api/workspaces")
    def create_workspace() -> dict[str, bool]:
        return {"written": True}

    @app.put("/api/workspaces/workspace-1")
    def update_workspace() -> dict[str, bool]:
        return {"written": True}

    @app.put("/api/workspaces/workspace-1/mcp-environment-defaults/read_middleware_context")
    def update_mcp_environment_default() -> dict[str, bool]:
        return {"written": True}

    @app.post("/api/workspaces/workspace-1/refresh")
    def refresh_workspace() -> dict[str, bool]:
        return {"refreshed": True}

    @app.post("/api/workspaces/reload-local-mapping")
    def reload_mapping() -> dict[str, bool]:
        return {"reloaded": True}

    @app.post("/api/workspaces/workspace-1/shared-files/restore")
    def restore_shared_files() -> dict[str, bool]:
        return {"restored": True}

    @app.post("/api/workspaces/workspace-1/containers/bulk-action")
    def control_containers() -> dict[str, bool]:
        return {"controlled": True}

    @app.post("/api/workspaces/workspace-1/host-runtime/actions")
    def run_host_runtime_action() -> dict[str, bool]:
        return {"queued": True}

    @app.post("/api/workspaces/workspace-1/relation-records/search")
    def search_relation_records() -> dict[str, bool]:
        return {"read": True}

    @app.post("/api/projects/project-1/runtime-config/{mode}/execute")
    def execute_project_update(mode: str) -> dict[str, str]:
        return {"mode": mode}

    @app.post("/api/data-sources/source-1/test")
    def test_connection() -> dict[str, bool]:
        return {"diagnostic": True}

    @app.post("/api/data-sources/source-1/reveal-password")
    def reveal_password() -> dict[str, bool]:
        return {"read": True}

    @app.post("/api/interface-forwarding/interfaces/interface-1/execute")
    def execute_forwarding() -> dict[str, bool]:
        return {"forwarded": True}

    @app.delete("/api/interface-forwarding/interfaces/interface-1")
    def delete_forwarding_interface() -> dict[str, bool]:
        return {"deleted": True}

    @app.put("/api/interface-forwarding/interfaces/interface-1/semantics")
    def update_forwarding_semantics() -> dict[str, bool]:
        return {"written": True}

    @app.post("/api/value-mappings")
    def create_value_mapping() -> dict[str, bool]:
        return {"written": True}

    @app.put("/api/value-mappings/mapping-1")
    def update_value_mapping() -> dict[str, bool]:
        return {"written": True}

    @app.delete("/api/value-mappings/mapping-1")
    def delete_value_mapping() -> dict[str, bool]:
        return {"deleted": True}

    @app.post("/api/value-mappings/mapping-1/preview")
    def preview_value_mapping() -> dict[str, bool]:
        return {"read": True}

    @app.post("/api/shared-config/ai/refresh")
    def refresh_shared_ai() -> dict[str, bool]:
        return {"refreshed": True}

    @app.put("/api/shared-config/ai/default")
    def save_shared_ai_default() -> dict[str, bool]:
        return {"saved": True}

    return app


def test_browser_origin_can_read_and_run_allowlisted_actions() -> None:
    with TestClient(_app()) as client:
        headers = {"Origin": FRONTEND_ORIGIN}
        assert client.get("/api/workspaces", headers=headers).status_code == 200
        assert (
            client.post(
                "/api/data-sources/source-1/test",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/workspaces/reload-local-mapping",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/workspaces/workspace-1/shared-files/restore",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/workspaces/workspace-1/containers/bulk-action",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/workspaces/workspace-1/host-runtime/actions",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/workspaces/workspace-1/relation-records/search",
                headers=headers,
            ).status_code
            == 200
        )
        for mode in ("fast", "full"):
            assert (
                client.post(
                    f"/api/projects/project-1/runtime-config/{mode}/execute",
                    headers=headers,
                ).status_code
                == 200
            )
        assert (
            client.post(
                "/api/data-sources/source-1/reveal-password",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/workspaces/workspace-1/refresh",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.put(
                "/api/workspaces/workspace-1/mcp-environment-defaults/read_middleware_context",
                headers=headers,
            ).status_code
            == 405
        )
        assert (
            client.post(
                "/api/interface-forwarding/interfaces/interface-1/execute", headers=headers
            ).status_code
            == 200
        )
        assert (
            client.delete(
                "/api/interface-forwarding/interfaces/interface-1", headers=headers
            ).status_code
            == 200
        )
        assert (
            client.put(
                "/api/interface-forwarding/interfaces/interface-1/semantics",
                headers=headers,
            ).status_code
            == 200
        )
        assert client.post("/api/value-mappings", headers=headers).status_code == 200
        assert client.put("/api/value-mappings/mapping-1", headers=headers).status_code == 200
        assert client.delete("/api/value-mappings/mapping-1", headers=headers).status_code == 200
        assert (
            client.post("/api/value-mappings/mapping-1/preview", headers=headers).status_code == 200
        )
        assert client.post("/api/shared-config/ai/refresh", headers=headers).status_code == 200
        assert client.put("/api/shared-config/ai/default", headers=headers).status_code == 200


def test_browser_origin_cannot_call_configuration_commands() -> None:
    with TestClient(_app()) as client:
        headers = {"Origin": FRONTEND_ORIGIN}
        create_response = client.post("/api/workspaces", headers=headers)
        update_response = client.put(
            "/api/workspaces/workspace-1",
            headers=headers,
        )
        refresh_extra_response = client.post(
            "/api/workspaces/workspace-1/refresh/extra",
            headers=headers,
        )
        unsupported_mode_response = client.post(
            "/api/projects/project-1/runtime-config/turbo/execute",
            headers=headers,
        )

    assert create_response.status_code == 405
    assert update_response.status_code == 405
    assert refresh_extra_response.status_code == 405
    assert unsupported_mode_response.status_code == 405
    assert create_response.json()["detail"].startswith("management_read_only:")


def test_any_browser_origin_cannot_call_configuration_commands() -> None:
    with TestClient(_app()) as client:
        for origin in (
            "http://127.0.0.1:49173",
            "http://192.168.8.10:49175",
            "https://example.invalid",
        ):
            response = client.post(
                "/api/workspaces",
                headers={"Origin": origin},
            )
            assert response.status_code == 405


def test_fetch_metadata_without_origin_is_still_treated_as_browser() -> None:
    with TestClient(_app()) as client:
        mode_response = client.post(
            "/api/workspaces",
            headers={"Sec-Fetch-Mode": "cors"},
        )
        site_response = client.put(
            "/api/workspaces/workspace-1",
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert mode_response.status_code == 405
    assert site_response.status_code == 405


def test_local_ai_or_ops_client_without_browser_origin_can_use_commands() -> None:
    with TestClient(_app()) as client:
        assert client.post("/api/workspaces").status_code == 200
        assert client.put("/api/workspaces/workspace-1").status_code == 200
