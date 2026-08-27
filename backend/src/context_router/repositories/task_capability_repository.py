from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol

import psycopg


class TaskCapabilityRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TaskCapabilityEvent:
    capability: str
    source: str
    reason_code: str
    revision: int
    evidence_call_id: int | None = None


class TaskCapabilityStore(Protocol):
    def enable(
        self,
        *,
        task_id: int,
        capability: str,
        source: str,
        reason_code: str,
        evidence_call_id: int | None = None,
    ) -> TaskCapabilityEvent: ...

    def list_for_task(self, task_id: int) -> list[TaskCapabilityEvent]: ...


class PostgresTaskCapabilityRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def enable(
        self,
        *,
        task_id: int,
        capability: str,
        source: str,
        reason_code: str,
        evidence_call_id: int | None = None,
    ) -> TaskCapabilityEvent:
        if not self._database_url:
            raise TaskCapabilityRepositoryError("任务数据库尚未配置")
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    WITH task_revision AS (
                        UPDATE mcp_tasks
                        SET capability_revision = capability_revision + 1
                        WHERE id = %s
                          AND NOT EXISTS (
                              SELECT 1
                              FROM mcp_task_capability_events
                              WHERE task_id = %s AND capability = %s
                          )
                        RETURNING capability_revision
                    ), inserted AS (
                        INSERT INTO mcp_task_capability_events (
                            task_id, capability, source, reason_code,
                            evidence_call_id, revision
                        )
                        SELECT %s, %s, %s, %s, %s, capability_revision
                        FROM task_revision
                        ON CONFLICT (task_id, capability) DO NOTHING
                        RETURNING capability, source, reason_code, revision, evidence_call_id
                    )
                    SELECT capability, source, reason_code, revision, evidence_call_id
                    FROM inserted
                    UNION ALL
                    SELECT capability, source, reason_code, revision, evidence_call_id
                    FROM mcp_task_capability_events
                    WHERE task_id = %s AND capability = %s
                    LIMIT 1
                    """,
                    (
                        task_id,
                        task_id,
                        capability,
                        task_id,
                        capability,
                        source,
                        reason_code,
                        evidence_call_id,
                        task_id,
                        capability,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise TaskCapabilityRepositoryError("任务能力写入失败") from exc
        if row is None:
            raise TaskCapabilityRepositoryError("任务不存在或能力写入失败")
        return TaskCapabilityEvent(
            capability=str(row[0]),
            source=str(row[1]),
            reason_code=str(row[2]),
            revision=int(row[3]),
            evidence_call_id=int(row[4]) if row[4] is not None else None,
        )

    def list_for_task(self, task_id: int) -> list[TaskCapabilityEvent]:
        if not self._database_url:
            raise TaskCapabilityRepositoryError("任务数据库尚未配置")
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT capability, source, reason_code, revision, evidence_call_id
                    FROM mcp_task_capability_events
                    WHERE task_id = %s
                    ORDER BY id
                    """,
                    (task_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise TaskCapabilityRepositoryError("任务能力读取失败") from exc
        return [
            TaskCapabilityEvent(
                capability=str(row[0]),
                source=str(row[1]),
                reason_code=str(row[2]),
                revision=int(row[3]),
                evidence_call_id=int(row[4]) if row[4] is not None else None,
            )
            for row in rows
        ]


class InMemoryTaskCapabilityRepository:
    def __init__(self) -> None:
        self._events: dict[int, dict[str, TaskCapabilityEvent]] = {}
        self._lock = Lock()

    def enable(
        self,
        *,
        task_id: int,
        capability: str,
        source: str,
        reason_code: str,
        evidence_call_id: int | None = None,
    ) -> TaskCapabilityEvent:
        with self._lock:
            task_events = self._events.setdefault(task_id, {})
            existing = task_events.get(capability)
            if existing is not None:
                return existing
            event = TaskCapabilityEvent(
                capability=capability,
                source=source,
                reason_code=reason_code,
                revision=len(task_events) + 2,
                evidence_call_id=evidence_call_id,
            )
            task_events[capability] = event
            return event

    def list_for_task(self, task_id: int) -> list[TaskCapabilityEvent]:
        with self._lock:
            return list(self._events.get(task_id, {}).values())
