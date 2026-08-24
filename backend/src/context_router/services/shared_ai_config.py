from __future__ import annotations

from context_router.repositories.shared_ai_default_repository import (
    SharedAiDefaultStore,
)
from context_router.schemas.shared_config import (
    SharedAiCatalog,
    SharedAiCenterConfiguration,
    SharedConfigurationCatalog,
    SharedImageModelCatalog,
)
from context_router.services.shared_config_client import SharedConfigCenterClient


class SharedAiConfigService:
    def __init__(
        self,
        client: SharedConfigCenterClient,
        defaults: SharedAiDefaultStore,
    ) -> None:
        self._client = client
        self._defaults = defaults

    def catalog(self, *, refresh: bool = True) -> SharedAiCatalog:
        center = self._client.refresh_ai() if refresh else self._client.require_ai()
        return self._catalog_from_center(center)

    def save_default(self, provider_id: str, revision: int) -> SharedAiCatalog:
        center = self._client.refresh_ai()
        clean_provider_id = provider_id.strip()
        if not any(provider.id == clean_provider_id for provider in center.providers):
            raise ValueError("所选默认 AI 不存在")
        self._defaults.get_or_initialize(_required_center_default(center))
        self._defaults.replace_default(
            provider_id=clean_provider_id,
            expected_revision=revision,
        )
        return self._catalog_from_center(center)

    def full_catalog(self) -> SharedConfigurationCatalog:
        ai = self._catalog_from_center(self._client.refresh_ai())
        databases = self._client.refresh_databases().databases
        local_cli = self._client.refresh_local_cli()
        local_cli.configs = [
            item.model_copy(update={"active": item.id == local_cli.active_config_id})
            for item in local_cli.configs
        ]
        object_storage = self._client.refresh_object_storage()
        image_center = self._client.refresh_image_models()
        image_models = SharedImageModelCatalog(
            active_provider_id=image_center.active_provider_id,
            providers=[
                item.model_copy(update={"active": item.id == image_center.active_provider_id})
                for item in image_center.providers
            ],
        )
        return SharedConfigurationCatalog(
            ai=ai,
            databases=databases,
            local_cli=local_cli,
            object_storage=object_storage,
            image_models=image_models,
            runtime=self._client.refresh_runtime(),
        )

    def _catalog_from_center(self, center: SharedAiCenterConfiguration) -> SharedAiCatalog:
        center_default = _required_center_default(center)
        local = self._defaults.get_or_initialize(center_default)
        provider_ids = {provider.id for provider in center.providers}
        recovered = local.default_provider_id not in provider_ids
        if recovered:
            local = self._defaults.replace_default(provider_id=center_default)
        active_id = local.default_provider_id
        providers = [
            provider.model_copy(update={"active": provider.id == active_id})
            for provider in center.providers
        ]
        return SharedAiCatalog(
            configured_default_provider_id=local.default_provider_id,
            center_active_provider_id=center_default,
            active_provider_id=active_id,
            default_source="local",
            default_recovered=recovered,
            notice=(
                "原本地默认 AI 已在配置中心删除，已自动切换为配置中心默认 AI。"
                if recovered
                else None
            ),
            revision=local.revision,
            providers=providers,
        )


def _required_center_default(center: SharedAiCenterConfiguration) -> str:
    provider_id = center.active_provider_id.strip()
    if not provider_id or not any(provider.id == provider_id for provider in center.providers):
        raise ValueError("配置中心没有可用的默认 AI")
    return provider_id
