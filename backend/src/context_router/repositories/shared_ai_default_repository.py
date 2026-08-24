from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import psycopg


class SharedAiDefaultRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SharedAiDefaultRecord:
    default_provider_id: str
    revision: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SharedAiDefaultStore(Protocol):
    def get_or_initialize(self, initial_provider_id: str) -> SharedAiDefaultRecord: ...

    def replace_default(
        self, *, provider_id: str, expected_revision: int | None = None
    ) -> SharedAiDefaultRecord: ...


class InMemorySharedAiDefaultRepository:
    def __init__(self) -> None:
        self._record: SharedAiDefaultRecord | None = None

    def get_or_initialize(self, initial_provider_id: str) -> SharedAiDefaultRecord:
        provider_id = _required_provider_id(initial_provider_id)
        if self._record is None:
            now = datetime.now(UTC)
            self._record = SharedAiDefaultRecord(provider_id, 1, now, now)
        return self._record

    def replace_default(
        self, *, provider_id: str, expected_revision: int | None = None
    ) -> SharedAiDefaultRecord:
        clean_provider_id = _required_provider_id(provider_id)
        if self._record is None:
            raise SharedAiDefaultRepositoryError("本地默认 AI 尚未初始化")
        if expected_revision is not None and self._record.revision != expected_revision:
            raise SharedAiDefaultRepositoryError("默认 AI 已被其他操作更新，请重新加载配置")
        now = datetime.now(UTC)
        self._record = SharedAiDefaultRecord(
            clean_provider_id,
            self._record.revision + 1,
            self._record.created_at,
            now,
        )
        return self._record


class PostgresSharedAiDefaultRepository:
    _KEY = "default"

    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def get_or_initialize(self, initial_provider_id: str) -> SharedAiDefaultRecord:
        provider_id = _required_provider_id(initial_provider_id)
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """
                    INSERT INTO shared_ai_defaults (defaults_key, default_provider_id)
                    VALUES (%s, %s)
                    ON CONFLICT (defaults_key) DO NOTHING
                    RETURNING default_provider_id, revision, created_at, updated_at
                    """,
                    (self._KEY, provider_id),
                ).fetchone()
                if row is None:
                    row = connection.execute(
                        """
                        SELECT default_provider_id, revision, created_at, updated_at
                        FROM shared_ai_defaults
                        WHERE defaults_key = %s
                        """,
                        (self._KEY,),
                    ).fetchone()
        except psycopg.Error as exc:
            raise SharedAiDefaultRepositoryError("本地默认 AI 读取失败") from exc
        if row is None:
            raise SharedAiDefaultRepositoryError("本地默认 AI 初始化失败")
        return _record(row)

    def replace_default(
        self, *, provider_id: str, expected_revision: int | None = None
    ) -> SharedAiDefaultRecord:
        clean_provider_id = _required_provider_id(provider_id)
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                if expected_revision is None:
                    row = connection.execute(
                        """
                        UPDATE shared_ai_defaults
                        SET default_provider_id = %s,
                            revision = revision + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE defaults_key = %s
                        RETURNING default_provider_id, revision, created_at, updated_at
                        """,
                        (clean_provider_id, self._KEY),
                    ).fetchone()
                else:
                    row = connection.execute(
                        """
                        UPDATE shared_ai_defaults
                        SET default_provider_id = %s,
                            revision = revision + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE defaults_key = %s AND revision = %s
                        RETURNING default_provider_id, revision, created_at, updated_at
                        """,
                        (clean_provider_id, self._KEY, expected_revision),
                    ).fetchone()
        except psycopg.Error as exc:
            raise SharedAiDefaultRepositoryError("本地默认 AI 保存失败") from exc
        if row is None:
            if expected_revision is not None:
                raise SharedAiDefaultRepositoryError("默认 AI 已被其他操作更新，请重新加载配置")
            raise SharedAiDefaultRepositoryError("本地默认 AI 尚未初始化")
        return _record(row)

    def _require_database_url(self) -> str:
        if not self._database_url:
            raise SharedAiDefaultRepositoryError("控制面数据库尚未配置")
        return self._database_url


def _required_provider_id(value: str) -> str:
    provider_id = value.strip()
    if not provider_id:
        raise SharedAiDefaultRepositoryError("配置中心没有可用的默认 AI")
    return provider_id


def _record(row: tuple[object, ...]) -> SharedAiDefaultRecord:
    return SharedAiDefaultRecord(
        default_provider_id=str(row[0]),
        revision=int(row[1]),
        created_at=row[2],  # type: ignore[arg-type]
        updated_at=row[3],  # type: ignore[arg-type]
    )
