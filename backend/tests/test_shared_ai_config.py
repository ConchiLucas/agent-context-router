from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.api.shared_config import router
from context_router.repositories.shared_ai_default_repository import (
    InMemorySharedAiDefaultRepository,
)
from context_router.schemas.shared_config import (
    SharedAiCenterConfiguration,
    SharedAiProvider,
    SharedDatabaseConfiguration,
    SharedLocalCliConfiguration,
    SharedObjectStorageConfiguration,
)
from context_router.services.shared_ai_config import SharedAiConfigService


def _center(active: str, provider_ids: list[str]) -> SharedAiCenterConfiguration:
    return SharedAiCenterConfiguration(
        activeProviderId=active,
        providers=[
            SharedAiProvider(
                id=provider_id,
                label=provider_id,
                type="openai-compatible",
                baseUrl="https://example.invalid/v1",
                apiKey=f"secret-{provider_id}",
                model="test-model",
                maxTokens=4096,
            )
            for provider_id in provider_ids
        ],
    )


class _Client:
    def __init__(self, value: SharedAiCenterConfiguration) -> None:
        self.value = value

    def refresh_ai(self) -> SharedAiCenterConfiguration:
        return self.value

    def require_ai(self) -> SharedAiCenterConfiguration:
        return self.value

    def refresh_databases(self) -> SharedDatabaseConfiguration:
        return SharedDatabaseConfiguration(
            databases=[
                {
                    "id": "db-1",
                    "name": "Database One",
                    "type": "postgresql",
                    "host": "127.0.0.1",
                    "port": 5432,
                    "database": "app",
                    "username": "user",
                    "password": "db-secret",
                }
            ]
        )

    def refresh_local_cli(self) -> SharedLocalCliConfiguration:
        return SharedLocalCliConfiguration(
            activeConfigId="codex",
            configs=[
                {
                    "id": "codex",
                    "label": "Codex",
                    "command": "codex",
                    "timeoutSeconds": 60,
                }
            ],
        )

    def refresh_object_storage(self) -> SharedObjectStorageConfiguration:
        return SharedObjectStorageConfiguration(
            configured=True,
            endpoint="127.0.0.1:9000",
            accessKeyId="access-secret",
            secretAccessKey="storage-secret",
            bucketName="assets",
        )

    def refresh_image_models(self) -> SharedAiCenterConfiguration:
        return _center("image", ["image"])

    def refresh_runtime(self) -> dict[str, object]:
        return {"schemaVersion": "1", "ai": {"apiKey": "runtime-secret"}}


def test_initializes_required_local_default_and_recovers_removed_provider() -> None:
    client = _Client(_center("center", ["center", "local"]))
    defaults = InMemorySharedAiDefaultRepository()
    service = SharedAiConfigService(client, defaults)  # type: ignore[arg-type]

    initial = service.catalog()
    assert initial.active_provider_id == "center"
    assert initial.configured_default_provider_id == "center"
    saved = service.save_default("local", initial.revision)
    assert saved.active_provider_id == "local"

    client.value = _center("center", ["center"])
    recovered = service.catalog()
    assert recovered.active_provider_id == "center"
    assert recovered.default_recovered is True
    assert recovered.notice is not None
    assert defaults.get_or_initialize("center").default_provider_id == "center"


def test_api_returns_plaintext_key_with_no_store() -> None:
    client = _Client(_center("center", ["center"]))
    app = FastAPI()
    app.state.shared_ai_config_service = SharedAiConfigService(
        client,
        InMemorySharedAiDefaultRepository(),  # type: ignore[arg-type]
    )
    app.include_router(router, prefix="/api")

    with TestClient(app) as browser:
        response = browser.get("/api/shared-config/ai")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["providers"][0]["api_key"] == "secret-center"


def test_catalog_exposes_all_six_configuration_sections() -> None:
    client = _Client(_center("center", ["center"]))
    app = FastAPI()
    app.state.shared_ai_config_service = SharedAiConfigService(
        client,
        InMemorySharedAiDefaultRepository(),  # type: ignore[arg-type]
    )
    app.include_router(router, prefix="/api")

    with TestClient(app) as browser:
        response = browser.get("/api/shared-config/ai/catalog")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert set(payload) == {
        "ai",
        "databases",
        "local_cli",
        "object_storage",
        "image_models",
        "runtime",
    }
    assert payload["databases"][0]["password"] == "db-secret"
    assert payload["local_cli"]["configs"][0]["active"] is True
    assert payload["object_storage"]["secret_access_key"] == "storage-secret"
    assert payload["image_models"]["providers"][0]["id"] == "image"
