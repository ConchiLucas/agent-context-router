from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from context_router.schemas.shared_config import (
    SharedAiCenterConfiguration,
    SharedDatabaseConfiguration,
    SharedLocalCliConfiguration,
    SharedObjectStorageConfiguration,
)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class SharedConfigCenterError(RuntimeError):
    pass


class SharedConfigCenterClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._current: SharedAiCenterConfiguration | None = None

    def require_ai(self) -> SharedAiCenterConfiguration:
        return self._current if self._current is not None else self.refresh_ai()

    def refresh_ai(self) -> SharedAiCenterConfiguration:
        result = self._get_model("/api/admin/v1/configuration/ai", SharedAiCenterConfiguration)
        self._current = result
        return result

    def refresh_databases(self) -> SharedDatabaseConfiguration:
        return self._get_model("/api/admin/v1/configuration/databases", SharedDatabaseConfiguration)

    def refresh_local_cli(self) -> SharedLocalCliConfiguration:
        return self._get_model("/api/admin/v1/configuration/local-cli", SharedLocalCliConfiguration)

    def refresh_object_storage(self) -> SharedObjectStorageConfiguration:
        return self._get_model(
            "/api/admin/v1/configuration/object-storage",
            SharedObjectStorageConfiguration,
        )

    def refresh_image_models(self) -> SharedAiCenterConfiguration:
        return self._get_model(
            "/api/admin/v1/configuration/image-models", SharedAiCenterConfiguration
        )

    def refresh_runtime(self) -> dict[str, Any]:
        value = self._get_json("/api/runtime/v1/configuration")
        if not isinstance(value, dict):
            raise SharedConfigCenterError("共享配置中心运行契约格式错误")
        return value

    def _get_model(self, path: str, schema: type[SchemaT]) -> SchemaT:
        try:
            return schema.model_validate(self._get_json(path))
        except ValueError as exc:
            raise SharedConfigCenterError("共享配置中心响应格式错误") from exc

    def _get_json(self, path: str) -> Any:
        if not self._base_url:
            raise SharedConfigCenterError("共享配置中心地址尚未配置")
        try:
            response = httpx.get(
                f"{self._base_url}{path}",
                headers={"Accept": "application/json"},
                timeout=httpx.Timeout(
                    self._timeout_seconds, connect=min(5.0, self._timeout_seconds)
                ),
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SharedConfigCenterError("无法加载共享配置中心") from exc
