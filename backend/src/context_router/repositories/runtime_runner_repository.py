from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol

import psycopg
from psycopg.types.json import Jsonb


class RuntimeRunnerRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeRunnerRecord:
    id: str
    hostname: str
    platform: str
    version: str
    capabilities: tuple[str, ...]
    status: str
    started_at: datetime
    last_heartbeat_at: datetime


class RuntimeRunnerStore(Protocol):
    def register(
        self,
        *,
        runner_id: str,
        hostname: str,
        platform: str,
        version: str,
        capabilities: list[str],
    ) -> RuntimeRunnerRecord: ...

    def heartbeat(self, runner_id: str) -> RuntimeRunnerRecord: ...
    def get(self, runner_id: str) -> RuntimeRunnerRecord | None: ...
    def is_available(self, ttl_seconds: int) -> bool: ...


class InMemoryRuntimeRunnerRepository:
    def __init__(self) -> None:
        self._runners: dict[str, RuntimeRunnerRecord] = {}
        self._lock = RLock()

    def register(
        self,
        *,
        runner_id: str,
        hostname: str,
        platform: str,
        version: str,
        capabilities: list[str],
    ) -> RuntimeRunnerRecord:
        now = datetime.now(UTC)
        record = RuntimeRunnerRecord(
            id=runner_id,
            hostname=hostname,
            platform=platform,
            version=version,
            capabilities=tuple(capabilities),
            status="online",
            started_at=now,
            last_heartbeat_at=now,
        )
        with self._lock:
            self._runners[runner_id] = record
        return record

    def heartbeat(self, runner_id: str) -> RuntimeRunnerRecord:
        with self._lock:
            current = self._runners.get(runner_id)
            if current is None:
                raise RuntimeRunnerRepositoryError("宿主机 Runner 尚未注册")
            updated = replace(current, status="online", last_heartbeat_at=datetime.now(UTC))
            self._runners[runner_id] = updated
            return updated

    def get(self, runner_id: str) -> RuntimeRunnerRecord | None:
        with self._lock:
            return self._runners.get(runner_id)

    def is_available(self, ttl_seconds: int) -> bool:
        threshold = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
        with self._lock:
            return any(
                item.status == "online" and item.last_heartbeat_at >= threshold
                for item in self._runners.values()
            )


class PostgresRuntimeRunnerRepository:
    _COLUMNS = """
        id, hostname, platform, version, capabilities, status,
        started_at, last_heartbeat_at
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def register(
        self,
        *,
        runner_id: str,
        hostname: str,
        platform: str,
        version: str,
        capabilities: list[str],
    ) -> RuntimeRunnerRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    "UPDATE runtime_runner_instances SET status = 'offline' WHERE id <> %s",
                    (runner_id,),
                )
                row = connection.execute(
                    f"""INSERT INTO runtime_runner_instances
                        (id, hostname, platform, version, capabilities, status)
                        VALUES (%s, %s, %s, %s, %s, 'online')
                        ON CONFLICT (id) DO UPDATE SET
                          hostname = EXCLUDED.hostname,
                          platform = EXCLUDED.platform,
                          version = EXCLUDED.version,
                          capabilities = EXCLUDED.capabilities,
                          status = 'online',
                          started_at = CURRENT_TIMESTAMP,
                          last_heartbeat_at = CURRENT_TIMESTAMP
                        RETURNING {self._COLUMNS}""",
                    (runner_id, hostname, platform, version, Jsonb(capabilities)),
                ).fetchone()
            if row is None:
                raise RuntimeRunnerRepositoryError("宿主机 Runner 注册失败")
            return self._record(row)
        except psycopg.Error as exc:
            raise RuntimeRunnerRepositoryError("宿主机 Runner 数据库当前不可用") from exc

    def heartbeat(self, runner_id: str) -> RuntimeRunnerRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    f"""UPDATE runtime_runner_instances
                        SET status = 'online', last_heartbeat_at = CURRENT_TIMESTAMP
                        WHERE id = %s RETURNING {self._COLUMNS}""",
                    (runner_id,),
                ).fetchone()
            if row is None:
                raise RuntimeRunnerRepositoryError("宿主机 Runner 尚未注册")
            return self._record(row)
        except psycopg.Error as exc:
            raise RuntimeRunnerRepositoryError("宿主机 Runner 数据库当前不可用") from exc

    def get(self, runner_id: str) -> RuntimeRunnerRecord | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    f"""SELECT {self._COLUMNS}
                        FROM runtime_runner_instances WHERE id = %s""",
                    (runner_id,),
                ).fetchone()
            return self._record(row) if row else None
        except psycopg.Error as exc:
            raise RuntimeRunnerRepositoryError("宿主机 Runner 数据库当前不可用") from exc

    def is_available(self, ttl_seconds: int) -> bool:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """SELECT EXISTS (
                         SELECT 1 FROM runtime_runner_instances
                         WHERE status = 'online'
                           AND last_heartbeat_at >= CURRENT_TIMESTAMP
                               - (%s * INTERVAL '1 second')
                       )""",
                    (ttl_seconds,),
                ).fetchone()
            return bool(row and row[0])
        except psycopg.Error as exc:
            raise RuntimeRunnerRepositoryError("宿主机 Runner 数据库当前不可用") from exc

    @staticmethod
    def _record(row: tuple[object, ...]) -> RuntimeRunnerRecord:
        return RuntimeRunnerRecord(
            id=str(row[0]),
            hostname=str(row[1]),
            platform=str(row[2]),
            version=str(row[3]),
            capabilities=tuple(row[4]),
            status=str(row[5]),
            started_at=row[6],  # type: ignore[arg-type]
            last_heartbeat_at=row[7],  # type: ignore[arg-type]
        )
