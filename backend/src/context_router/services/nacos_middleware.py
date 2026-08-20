from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import httpx
import yaml

from context_router.database.errors import DatabaseAccessError
from context_router.repositories.mcp_environment_default_repository import (
    McpEnvironmentDefaultStore,
)
from context_router.repositories.nacos_profile_repository import (
    NacosProfileRecord,
    NacosProfileRepositoryError,
    NacosProfileStore,
)
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
from context_router.schemas.nacos_profiles import (
    MiddlewareComponentContext,
    MiddlewareSourceContext,
    NacosComponentRule,
    NacosProfileKey,
    ReadMiddlewareContextResult,
)
from context_router.services.database_access import DatabaseAccessService
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

_MAX_CONFIG_BYTES = 1_000_000
_MAX_TOTAL_CONFIG_BYTES = 4_000_000
_REDACTED = "***REDACTED***"
_PLACEHOLDER_PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?}")
_SECRET_TERMS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "access-key",
    "access_key",
    "private-key",
    "private_key",
)


class MiddlewareContextError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class NacosConfigDocument:
    data_id: str
    group: str
    content: str
    config_type: str | None = None
    md5: str | None = None
    modified_at: str | None = None


class NacosConfigReader(Protocol):
    def get_config(self, *, data_id: str, group: str) -> NacosConfigDocument: ...

    def close(self) -> None: ...


NacosReaderFactory = Callable[[NacosProfileRecord], NacosConfigReader]


class HttpNacosConfigReader:
    def __init__(self, profile: NacosProfileRecord) -> None:
        self._profile = profile
        self._client = httpx.Client(
            base_url=profile.base_url.rstrip("/") + "/",
            timeout=profile.request_timeout_ms / 1000,
            follow_redirects=False,
            trust_env=False,
        )
        self._v3_token: str | None = None
        self._v1_token: str | None = None

    def get_config(self, *, data_id: str, group: str) -> NacosConfigDocument:
        try:
            return self._get_v3_config(data_id=data_id, group=group)
        except MiddlewareContextError as exc:
            if exc.code != "nacos_api_not_supported":
                raise
        return self._get_v1_config(data_id=data_id, group=group)

    def close(self) -> None:
        self._client.close()

    def _get_v3_config(self, *, data_id: str, group: str) -> NacosConfigDocument:
        token = self._authenticate(version="v3")
        response = self._request(
            "GET",
            "v3/console/cs/config",
            headers=_auth_headers(token),
            params={
                "username": self._profile.username or None,
                "namespaceId": self._profile.namespace_id,
                "dataId": data_id,
                "groupName": group,
            },
            allow_not_supported=True,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MiddlewareContextError("nacos_invalid_response", "Nacos 返回格式无效") from exc
        if not isinstance(payload, dict):
            raise MiddlewareContextError("nacos_invalid_response", "Nacos 返回格式无效")
        if payload.get("code") not in {None, 0, 200}:
            raise _v3_payload_error(payload)
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("content"), str):
            raise MiddlewareContextError("nacos_config_not_found", "Nacos 配置不存在")
        content = data["content"]
        _ensure_content_size(content)
        return NacosConfigDocument(
            data_id=data_id,
            group=group,
            content=content,
            config_type=_optional_string(data.get("type")),
            md5=_optional_string(data.get("md5")) or _content_md5(content),
            modified_at=_optional_string(data.get("modifyTime")),
        )

    def _get_v1_config(self, *, data_id: str, group: str) -> NacosConfigDocument:
        token = self._authenticate(version="v1")
        response = self._request(
            "GET",
            "v1/cs/configs",
            params={
                "dataId": data_id,
                "group": group,
                "tenant": self._profile.namespace_id,
                "accessToken": token or None,
                "username": self._profile.username or None,
            },
        )
        content = response.text
        _ensure_content_size(content)
        return NacosConfigDocument(
            data_id=data_id,
            group=group,
            content=content,
            config_type=None,
            md5=response.headers.get("Content-MD5") or _content_md5(content),
        )

    def _authenticate(self, *, version: str) -> str | None:
        if not self._profile.username:
            return None
        if version == "v3" and self._v3_token is not None:
            return self._v3_token
        if version == "v1" and self._v1_token is not None:
            return self._v1_token
        endpoint = "v3/auth/user/login" if version == "v3" else "v1/auth/users/login"
        response = self._request(
            "POST",
            endpoint,
            data={
                "username": self._profile.username,
                "password": self._profile.password,
            },
            allow_not_supported=True,
            authentication_request=True,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MiddlewareContextError("nacos_auth_failed", "Nacos 登录失败") from exc
        token = _extract_access_token(payload)
        if not token:
            if response.status_code in {404, 405}:
                raise MiddlewareContextError(
                    "nacos_api_not_supported",
                    "Nacos API 版本不受支持",
                )
            raise MiddlewareContextError("nacos_auth_failed", "Nacos 登录失败")
        if version == "v3":
            self._v3_token = token
        else:
            self._v1_token = token
        return token

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, object] | None = None,
        data: dict[str, object] | None = None,
        allow_not_supported: bool = False,
        authentication_request: bool = False,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method,
                path,
                headers=headers,
                params={key: value for key, value in (params or {}).items() if value is not None},
                data=data,
            )
        except httpx.TimeoutException as exc:
            raise MiddlewareContextError("nacos_timeout", "Nacos 请求超时") from exc
        except httpx.HTTPError as exc:
            raise MiddlewareContextError("nacos_unavailable", "Nacos 当前无法连接") from exc
        if response.status_code in {401, 403}:
            code = "nacos_auth_failed" if authentication_request else "nacos_access_denied"
            raise MiddlewareContextError(code, "Nacos 认证失败或没有读取权限")
        if response.status_code in {404, 405} and allow_not_supported:
            raise MiddlewareContextError(
                "nacos_api_not_supported",
                "Nacos API 版本不受支持",
            )
        if response.status_code == 404:
            raise MiddlewareContextError("nacos_config_not_found", "Nacos 配置不存在")
        if response.status_code >= 400:
            raise MiddlewareContextError("nacos_request_failed", "Nacos 请求失败")
        return response


class MiddlewareContextService:
    def __init__(
        self,
        *,
        registry: ProjectRegistry,
        task_repository: TaskReader,
        profile_repository: NacosProfileStore,
        database_access_service: DatabaseAccessService,
        mcp_environment_defaults: McpEnvironmentDefaultStore | None = None,
        reader_factory: NacosReaderFactory | None = None,
    ) -> None:
        self._registry = registry
        self._tasks = task_repository
        self._profiles = profile_repository
        self._database_access = database_access_service
        self._mcp_environment_defaults = mcp_environment_defaults
        self._reader_factory = reader_factory or HttpNacosConfigReader

    def read(
        self,
        *,
        task_id: int,
        components: list[str] | None,
        reveal_secrets: bool,
        environment: str | None = None,
    ) -> ReadMiddlewareContextResult:
        task, workspace_id = self._resolve_task(task_id)
        profile_key, selected_environment = self._select_profile(
            task,
            workspace_id,
            requested_environment=environment,
        )
        try:
            profile = self._profiles.get_profile(workspace_id, profile_key)
        except NacosProfileRepositoryError as exc:
            raise MiddlewareContextError(exc.code, str(exc)) from exc
        try:
            rules = [NacosComponentRule.model_validate(item) for item in profile.components]
        except ValueError as exc:
            raise MiddlewareContextError(
                "nacos_profile_invalid",
                "Nacos profile 的组件提取规则无效",
            ) from exc
        selected_rules = _select_rules(rules, components)
        reader = self._reader_factory(profile)
        warnings: list[str] = []
        documents: dict[tuple[str, str], NacosConfigDocument] = {}
        parsed: dict[tuple[str, str], Mapping[str, Any]] = {}
        total_bytes = 0
        try:
            for rule in selected_rules:
                for source in rule.sources:
                    key = (source.data_id, source.group)
                    if key in documents:
                        continue
                    try:
                        document = reader.get_config(data_id=source.data_id, group=source.group)
                    except MiddlewareContextError as exc:
                        if exc.code != "nacos_config_not_found":
                            raise
                        warnings.append(f"组件配置不存在：{source.data_id} / {source.group}")
                        continue
                    total_bytes += len(document.content.encode("utf-8"))
                    if total_bytes > _MAX_TOTAL_CONFIG_BYTES:
                        raise MiddlewareContextError(
                            "nacos_response_too_large",
                            "本次 Nacos 配置正文总量超过限制",
                        )
                    documents[key] = document
                    try:
                        parsed[key] = _parse_config(document)
                    except MiddlewareContextError:
                        warnings.append(f"组件配置无法解析：{source.data_id} / {source.group}")
            results = [
                _extract_component(
                    rule,
                    documents=documents,
                    parsed=parsed,
                    reveal_secrets=reveal_secrets,
                )
                for rule in selected_rules
            ]
        finally:
            reader.close()
        for component in results:
            if component.missing_fields:
                warnings.append(f"{component.id} 缺少字段：{', '.join(component.missing_fields)}")
            if component.unresolved_fields:
                warnings.append(
                    f"{component.id} 存在未解析占位符：{', '.join(component.unresolved_fields)}"
                )
        return ReadMiddlewareContextResult(
            task_id=task_id,
            profile_key=profile_key,
            environment=selected_environment,
            fetched_at=datetime.now(UTC),
            secrets_revealed=reveal_secrets,
            components=results,
            warnings=warnings,
        )

    def _resolve_task(self, task_id: int) -> tuple[object, str]:
        try:
            task = self._tasks.get_task(task_id)
        except TaskRepositoryError as exc:
            raise MiddlewareContextError("task_not_found", "任务不存在，请重新 prepare") from exc
        if task.scope != "workspace" or not task.workspace_id:
            raise MiddlewareContextError(
                "workspace_task_required",
                "中间件上下文只支持新的 Workspace task，请重新 prepare",
            )
        try:
            workspace = self._registry.get_workspace_snapshot_for_task(
                workspace_id=task.workspace_id,
                workspace_key=task.workspace_key,
            )
            routed = self._registry.find_workspace_for_cwd(task.cwd)
        except ProjectRegistryError as exc:
            raise MiddlewareContextError(
                "workspace_unavailable",
                "任务绑定的工作空间当前不可用，请重新 prepare",
            ) from exc
        if routed.id != workspace.id:
            raise MiddlewareContextError(
                "workspace_unavailable",
                "任务绑定的工作空间已发生变化，请重新 prepare",
            )
        if routed.access_mode == "documents_only":
            raise MiddlewareContextError(
                "documents_only",
                "当前目录只能读取文档，不能读取中间件凭据",
            )
        return task, workspace.id

    def _validate_environment(self, task: object, workspace_id: str) -> str | None:
        try:
            return self._database_access.validate_task_environment(
                workspace_id,
                task_environment=getattr(task, "database_environment", None),
                task_environment_revision=getattr(task, "database_environment_revision", None),
                database_environment_selection=getattr(
                    task,
                    "database_environment_selection",
                    None,
                ),
            )
        except DatabaseAccessError as exc:
            raise MiddlewareContextError(exc.code, str(exc)) from exc

    def _select_profile(
        self,
        task: object,
        workspace_id: str,
        *,
        requested_environment: str | None,
    ) -> tuple[NacosProfileKey, str | None]:
        selected = requested_environment
        if selected is None:
            selected = self._validate_environment(task, workspace_id) or "local"
        has_environment = getattr(self._database_access, "has_workspace_environment", None)
        if callable(has_environment) and not has_environment(workspace_id, selected):
            raise MiddlewareContextError(
                "environment_not_configured",
                "工作空间没有配置所选环境",
            )
        return selected, selected


def _select_rules(
    rules: list[NacosComponentRule],
    requested: list[str] | None,
) -> list[NacosComponentRule]:
    if not requested:
        return rules
    normalized = [value.strip().casefold() for value in requested]
    if any(not value for value in normalized) or len(normalized) != len(set(normalized)):
        raise MiddlewareContextError(
            "invalid_middleware_components",
            "组件 ID 不能为空或重复",
        )
    by_id = {rule.id: rule for rule in rules}
    missing = [component_id for component_id in normalized if component_id not in by_id]
    if missing:
        raise MiddlewareContextError(
            "middleware_component_not_found",
            f"当前 Nacos profile 没有这些组件：{', '.join(missing)}",
        )
    return [by_id[component_id] for component_id in normalized]


def _extract_component(
    rule: NacosComponentRule,
    *,
    documents: dict[tuple[str, str], NacosConfigDocument],
    parsed: dict[tuple[str, str], Mapping[str, Any]],
    reveal_secrets: bool,
) -> MiddlewareComponentContext:
    source_keys = [(source.data_id, source.group) for source in rule.sources]
    flat_values: dict[str, Any] = {}
    for key in source_keys:
        config = parsed.get(key)
        if config is not None:
            flat_values.update(_flatten_mapping(config))
    properties: dict[str, Any] = {}
    missing_fields: list[str] = []
    unresolved_fields: list[str] = []
    for field_name, field_rule in rule.fields.items():
        found = False
        for path in field_rule.paths:
            for key in source_keys:
                config = parsed.get(key)
                if config is None:
                    continue
                exists, value = _lookup_path(config, path)
                if not exists:
                    continue
                found = True
                resolved, unresolved = _resolve_placeholders(value, flat_values)
                is_secret = field_rule.secret or _looks_secret(field_name, path)
                properties[field_name] = resolved if reveal_secrets or not is_secret else _REDACTED
                if unresolved:
                    unresolved_fields.append(field_name)
                break
            if found:
                break
        if not found:
            missing_fields.append(field_name)
    sources = [
        MiddlewareSourceContext(
            data_id=document.data_id,
            group=document.group,
            md5=document.md5,
            modified_at=document.modified_at,
        )
        for key in source_keys
        if (document := documents.get(key)) is not None
    ]
    return MiddlewareComponentContext(
        id=rule.id,
        type=rule.type,
        properties=properties,
        missing_fields=missing_fields,
        unresolved_fields=unresolved_fields,
        sources=sources,
    )


def _parse_config(document: NacosConfigDocument) -> Mapping[str, Any]:
    config_type = (document.config_type or "").strip().casefold()
    if not config_type:
        suffix = document.data_id.rsplit(".", 1)[-1].casefold()
        config_type = {"yml": "yaml"}.get(suffix, suffix)
    try:
        if config_type == "json":
            value = json.loads(document.content)
        elif config_type in {"yaml", "yml"}:
            value = yaml.safe_load(document.content)
        elif config_type in {"properties", "ini"}:
            value = _parse_properties(document.content)
        else:
            value = yaml.safe_load(document.content)
    except (ValueError, yaml.YAMLError) as exc:
        raise MiddlewareContextError(
            "nacos_config_parse_failed",
            "Nacos 配置正文无法解析",
        ) from exc
    if not isinstance(value, Mapping):
        raise MiddlewareContextError(
            "nacos_config_parse_failed",
            "Nacos 配置正文必须解析为对象",
        )
    return cast(Mapping[str, Any], value)


def _parse_properties(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    pending = ""
    for raw_line in content.splitlines():
        line = pending + raw_line.rstrip()
        if line.endswith("\\"):
            pending = line[:-1]
            continue
        pending = ""
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        separator = "=" if "=" in stripped else ":" if ":" in stripped else None
        if separator is None:
            values[stripped] = ""
            continue
        key, value = stripped.split(separator, 1)
        values[key.strip()] = value.strip()
    if pending:
        values[pending.strip()] = ""
    return values


def _lookup_path(config: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    if path in config:
        return True, config[path]
    current: Any = config
    for segment in path.split("."):
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
            continue
        if isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            current = current[int(segment)]
            continue
        return False, None
    return True, current


def _flatten_mapping(value: Any, prefix: tuple[str, ...] = ()) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key, child in value.items():
            flattened.update(_flatten_mapping(child, (*prefix, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            flattened.update(_flatten_mapping(child, (*prefix, str(index))))
    elif prefix:
        flattened[".".join(prefix)] = value
    return flattened


def _resolve_placeholders(value: Any, flat_values: dict[str, Any]) -> tuple[Any, bool]:
    if not isinstance(value, str) or "${" not in value:
        return value, False
    unresolved = False
    current = value
    for _ in range(5):
        changed = False

        def replacement(match: re.Match[str]) -> str:
            nonlocal unresolved, changed
            key = match.group(1).strip()
            default = match.group(2)
            if key in flat_values and not isinstance(flat_values[key], dict | list):
                changed = True
                return str(flat_values[key])
            if default is not None:
                changed = True
                return default
            unresolved = True
            return match.group(0)

        resolved = _PLACEHOLDER_PATTERN.sub(replacement, current)
        current = resolved
        if not changed or "${" not in current:
            break
    if "${" in current:
        unresolved = True
    return current, unresolved


def _looks_secret(field_name: str, path: str) -> bool:
    normalized = f"{field_name} {path}".casefold()
    return any(term in normalized for term in _SECRET_TERMS)


def _ensure_content_size(content: str) -> None:
    if len(content.encode("utf-8")) > _MAX_CONFIG_BYTES:
        raise MiddlewareContextError(
            "nacos_response_too_large",
            "单份 Nacos 配置正文超过限制",
        )


def _content_md5(content: str) -> str:
    return hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()


def _auth_headers(token: str | None) -> dict[str, str] | None:
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "accessToken": token}


def _extract_access_token(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    token = payload.get("accessToken") or payload.get("access_token")
    data = payload.get("data")
    if not token and isinstance(data, dict):
        token = data.get("accessToken") or data.get("access_token")
    return token if isinstance(token, str) and token else None


def _v3_payload_error(payload: dict[str, Any]) -> MiddlewareContextError:
    message = str(payload.get("message") or "").casefold()
    if "not found" in message or "不存在" in message:
        return MiddlewareContextError("nacos_config_not_found", "Nacos 配置不存在")
    if "permission" in message or "token" in message or "auth" in message:
        return MiddlewareContextError("nacos_access_denied", "Nacos 没有读取权限")
    return MiddlewareContextError("nacos_request_failed", "Nacos 请求失败")


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None and str(value) else None
