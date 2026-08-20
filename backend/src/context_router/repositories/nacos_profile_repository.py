from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

import psycopg
from psycopg.types.json import Jsonb

from context_router.schemas.nacos_profiles import NacosProfileKey

_ENVIRONMENT_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class NacosProfileRepositoryError(RuntimeError):
    def __init__(self, message: str, *, code: str = "nacos_profile_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class NacosProfileWrite:
    workspace_id: str
    profile_key: NacosProfileKey
    base_url: str
    namespace_id: str
    username: str
    password: str
    request_timeout_ms: int
    components: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class NacosProfileRecord(NacosProfileWrite):
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NacosProfileStore(Protocol):
    def list_profiles(self, workspace_id: str) -> list[NacosProfileRecord]: ...

    def get_profile(
        self,
        workspace_id: str,
        profile_key: NacosProfileKey,
    ) -> NacosProfileRecord: ...

    def upsert_profile(self, profile: NacosProfileWrite) -> NacosProfileRecord: ...

    def delete_profile(self, workspace_id: str, profile_key: NacosProfileKey) -> None: ...


class InMemoryNacosProfileRepository:
    def __init__(self) -> None:
        self._profiles: dict[tuple[str, NacosProfileKey], NacosProfileRecord] = {}

    def list_profiles(self, workspace_id: str) -> list[NacosProfileRecord]:
        return [
            _copy_record(record)
            for key, record in sorted(
                self._profiles.items(),
                key=lambda item: (_profile_order(item[0][1]), item[0][1]),
            )
            if key[0] == workspace_id
        ]

    def get_profile(
        self,
        workspace_id: str,
        profile_key: NacosProfileKey,
    ) -> NacosProfileRecord:
        record = self._profiles.get((workspace_id, profile_key))
        if record is None:
            raise NacosProfileRepositoryError(
                "当前工作空间没有配置所选环境的 Nacos profile",
                code="nacos_not_configured",
            )
        return _copy_record(record)

    def upsert_profile(self, profile: NacosProfileWrite) -> NacosProfileRecord:
        _validate_write(profile)
        previous = self._profiles.get((profile.workspace_id, profile.profile_key))
        now = datetime.now(UTC)
        record = NacosProfileRecord(
            workspace_id=profile.workspace_id,
            profile_key=profile.profile_key,
            base_url=profile.base_url,
            namespace_id=profile.namespace_id,
            username=profile.username,
            password=profile.password,
            request_timeout_ms=profile.request_timeout_ms,
            components=copy.deepcopy(profile.components),
            created_at=previous.created_at if previous is not None else now,
            updated_at=now,
        )
        self._profiles[(profile.workspace_id, profile.profile_key)] = record
        return _copy_record(record)

    def delete_profile(self, workspace_id: str, profile_key: NacosProfileKey) -> None:
        if self._profiles.pop((workspace_id, profile_key), None) is None:
            raise NacosProfileRepositoryError(
                "Nacos profile 不存在",
                code="nacos_not_configured",
            )


class PostgresNacosProfileRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def list_profiles(self, workspace_id: str) -> list[NacosProfileRecord]:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                rows = connection.execute(
                    """
                    SELECT workspace_id, profile_key, base_url, namespace_id,
                           username, password, request_timeout_ms, components,
                           created_at, updated_at
                    FROM workspace_nacos_profiles
                    WHERE workspace_id = %s
                    ORDER BY CASE profile_key
                        WHEN 'local' THEN 0 WHEN 'test' THEN 10 WHEN 'uat' THEN 20 ELSE 100 END,
                        profile_key
                    """,
                    (workspace_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise NacosProfileRepositoryError("Nacos profile 列表读取失败") from exc
        return [_record_from_row(row) for row in rows]

    def get_profile(
        self,
        workspace_id: str,
        profile_key: NacosProfileKey,
    ) -> NacosProfileRecord:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """
                    SELECT workspace_id, profile_key, base_url, namespace_id,
                           username, password, request_timeout_ms, components,
                           created_at, updated_at
                    FROM workspace_nacos_profiles
                    WHERE workspace_id = %s AND profile_key = %s
                    """,
                    (workspace_id, profile_key),
                ).fetchone()
        except psycopg.Error as exc:
            raise NacosProfileRepositoryError("Nacos profile 读取失败") from exc
        if row is None:
            raise NacosProfileRepositoryError(
                "当前工作空间没有配置所选环境的 Nacos profile",
                code="nacos_not_configured",
            )
        return _record_from_row(row)

    def upsert_profile(self, profile: NacosProfileWrite) -> NacosProfileRecord:
        _validate_write(profile)
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """
                    INSERT INTO workspace_nacos_profiles (
                        workspace_id, profile_key, base_url, namespace_id,
                        username, password, request_timeout_ms, components
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (workspace_id, profile_key) DO UPDATE SET
                        base_url = EXCLUDED.base_url,
                        namespace_id = EXCLUDED.namespace_id,
                        username = EXCLUDED.username,
                        password = EXCLUDED.password,
                        request_timeout_ms = EXCLUDED.request_timeout_ms,
                        components = EXCLUDED.components,
                        updated_at = NOW()
                    RETURNING workspace_id, profile_key, base_url, namespace_id,
                              username, password, request_timeout_ms, components,
                              created_at, updated_at
                    """,
                    (
                        profile.workspace_id,
                        profile.profile_key,
                        profile.base_url,
                        profile.namespace_id,
                        profile.username,
                        profile.password,
                        profile.request_timeout_ms,
                        Jsonb(profile.components),
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise NacosProfileRepositoryError("Nacos profile 保存失败") from exc
        if row is None:
            raise NacosProfileRepositoryError("Nacos profile 保存后没有返回记录")
        return _record_from_row(row)

    def delete_profile(self, workspace_id: str, profile_key: NacosProfileKey) -> None:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                cursor = connection.execute(
                    """
                    DELETE FROM workspace_nacos_profiles
                    WHERE workspace_id = %s AND profile_key = %s
                    """,
                    (workspace_id, profile_key),
                )
        except psycopg.Error as exc:
            raise NacosProfileRepositoryError("Nacos profile 删除失败") from exc
        if cursor.rowcount != 1:
            raise NacosProfileRepositoryError(
                "Nacos profile 不存在",
                code="nacos_not_configured",
            )

    def _require_database_url(self) -> str:
        if not self._database_url:
            raise NacosProfileRepositoryError("控制面数据库尚未配置")
        return self._database_url


def _record_from_row(row: tuple[object, ...]) -> NacosProfileRecord:
    profile_key = str(row[1])
    if not _ENVIRONMENT_PATTERN.fullmatch(profile_key):
        raise NacosProfileRepositoryError("Nacos profile 环境标识无效")
    components = row[7]
    if not isinstance(components, list):
        raise NacosProfileRepositoryError("Nacos profile 提取规则格式无效")
    return NacosProfileRecord(
        workspace_id=str(row[0]),
        profile_key=profile_key,
        base_url=str(row[2]),
        namespace_id=str(row[3]),
        username=str(row[4]),
        password=str(row[5]),
        request_timeout_ms=int(row[6]),
        components=copy.deepcopy(components),
        created_at=cast(datetime, row[8]),
        updated_at=cast(datetime, row[9]),
    )


def _copy_record(record: NacosProfileRecord) -> NacosProfileRecord:
    return NacosProfileRecord(
        workspace_id=record.workspace_id,
        profile_key=record.profile_key,
        base_url=record.base_url,
        namespace_id=record.namespace_id,
        username=record.username,
        password=record.password,
        request_timeout_ms=record.request_timeout_ms,
        components=copy.deepcopy(record.components),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _validate_write(profile: NacosProfileWrite) -> None:
    if not _ENVIRONMENT_PATTERN.fullmatch(profile.profile_key):
        raise NacosProfileRepositoryError("Nacos profile 环境标识无效")
    if not profile.workspace_id or not profile.base_url or not profile.namespace_id:
        raise NacosProfileRepositoryError("Nacos profile 缺少必填字段")
    if not 500 <= profile.request_timeout_ms <= 30_000:
        raise NacosProfileRepositoryError("Nacos 请求超时必须在 500 到 30000 毫秒之间")
    if not profile.components:
        raise NacosProfileRepositoryError("Nacos profile 至少需要一个组件规则")


def _profile_order(profile_key: NacosProfileKey) -> int:
    return {"local": 0, "test": 10, "uat": 20}.get(profile_key, 100)
