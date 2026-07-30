from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb


class RuntimeRunRepositoryError(RuntimeError):
    """Raised when runtime execution records cannot be persisted."""


@dataclass(frozen=True)
class RuntimeRunRecord:
    id: str
    project_id: str
    mode: str
    trigger: str
    status: str
    snapshot_id: str
    materialized_path: str
    project_root: str
    entry_file: str
    log_path: str
    changed_files: tuple[str, ...]
    decision_reason: str
    exit_code: int | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RuntimeRunStore(Protocol):
    def create_run(
        self,
        *,
        project_id: str,
        mode: str,
        trigger: str,
        snapshot_id: str,
        materialized_path: str,
        project_root: str,
        entry_file: str,
        log_path: str,
        changed_files: list[str],
        decision_reason: str,
    ) -> RuntimeRunRecord: ...

    def mark_running(self, run_id: str) -> RuntimeRunRecord: ...

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        exit_code: int | None,
        error_message: str | None,
    ) -> RuntimeRunRecord: ...

    def get_run(self, run_id: str) -> RuntimeRunRecord | None: ...

    def list_runs(self, project_id: str, limit: int = 20) -> list[RuntimeRunRecord]: ...

    def reconcile_interrupted(self) -> int: ...


class InMemoryRuntimeRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, RuntimeRunRecord] = {}
        self._lock = RLock()

    def create_run(
        self,
        *,
        project_id: str,
        mode: str,
        trigger: str,
        snapshot_id: str,
        materialized_path: str,
        project_root: str,
        entry_file: str,
        log_path: str,
        changed_files: list[str],
        decision_reason: str,
    ) -> RuntimeRunRecord:
        run = RuntimeRunRecord(
            id=uuid4().hex,
            project_id=project_id,
            mode=mode,
            trigger=trigger,
            status="queued",
            snapshot_id=snapshot_id,
            materialized_path=materialized_path,
            project_root=project_root,
            entry_file=entry_file,
            log_path=log_path,
            changed_files=tuple(changed_files),
            decision_reason=decision_reason,
            exit_code=None,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            finished_at=None,
        )
        with self._lock:
            self._runs[run.id] = run
        return run

    def mark_running(self, run_id: str) -> RuntimeRunRecord:
        return self._update(
            run_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        exit_code: int | None,
        error_message: str | None,
    ) -> RuntimeRunRecord:
        return self._update(
            run_id,
            status=status,
            exit_code=exit_code,
            error_message=error_message,
            finished_at=datetime.now(timezone.utc),
        )

    def get_run(self, run_id: str) -> RuntimeRunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self, project_id: str, limit: int = 20) -> list[RuntimeRunRecord]:
        with self._lock:
            records = [
                item for item in self._runs.values() if item.project_id == project_id
            ]
        return sorted(records, key=lambda item: item.created_at, reverse=True)[:limit]

    def reconcile_interrupted(self) -> int:
        with self._lock:
            active_ids = [
                run_id
                for run_id, item in self._runs.items()
                if item.status in {"queued", "running"}
            ]
        for run_id in active_ids:
            self.finish_run(
                run_id,
                status="failed",
                exit_code=None,
                error_message="Runtime Runner 服务重启，任务已中断",
            )
        return len(active_ids)

    def _update(self, run_id: str, **changes: object) -> RuntimeRunRecord:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                raise RuntimeRunRepositoryError("运行任务不存在")
            updated = replace(current, **changes)
            self._runs[run_id] = updated
            return updated


class PostgresRuntimeRunRepository:
    _SELECT_COLUMNS = """
        id, project_id, mode, trigger, status, snapshot_id,
        materialized_path, project_root, entry_file, log_path,
        changed_files, decision_reason, exit_code, error_message,
        created_at, started_at, finished_at
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def create_run(
        self,
        *,
        project_id: str,
        mode: str,
        trigger: str,
        snapshot_id: str,
        materialized_path: str,
        project_root: str,
        entry_file: str,
        log_path: str,
        changed_files: list[str],
        decision_reason: str,
    ) -> RuntimeRunRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO project_runtime_runs (
                            id, project_id, mode, trigger, status, snapshot_id,
                            materialized_path, project_root, entry_file, log_path,
                            changed_files, decision_reason
                        )
                        VALUES (
                            %s, %s, %s, %s, 'queued', %s,
                            %s, %s, %s, %s, %s, %s
                        )
                        RETURNING {self._SELECT_COLUMNS}
                        """,
                        (
                            uuid4().hex,
                            project_id,
                            mode,
                            trigger,
                            snapshot_id,
                            materialized_path,
                            project_root,
                            entry_file,
                            log_path,
                            Jsonb(changed_files),
                            decision_reason,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeRunRepositoryError("运行任务创建失败")
                    return self._record(row)
        except psycopg.Error as exc:
            raise RuntimeRunRepositoryError("运行任务数据库当前不可用") from exc

    def mark_running(self, run_id: str) -> RuntimeRunRecord:
        return self._update_status(
            run_id,
            "status = 'running', started_at = CURRENT_TIMESTAMP",
            (),
        )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        exit_code: int | None,
        error_message: str | None,
    ) -> RuntimeRunRecord:
        return self._update_status(
            run_id,
            """
            status = %s,
            exit_code = %s,
            error_message = %s,
            finished_at = CURRENT_TIMESTAMP
            """,
            (status, exit_code, error_message),
        )

    def get_run(self, run_id: str) -> RuntimeRunRecord | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT {self._SELECT_COLUMNS}
                        FROM project_runtime_runs
                        WHERE id = %s
                        """,
                        (run_id,),
                    )
                    row = cursor.fetchone()
                    return self._record(row) if row is not None else None
        except psycopg.Error as exc:
            raise RuntimeRunRepositoryError("运行任务数据库当前不可用") from exc

    def list_runs(self, project_id: str, limit: int = 20) -> list[RuntimeRunRecord]:
        try:
            with psycopg.connect(self._database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT {self._SELECT_COLUMNS}
                        FROM project_runtime_runs
                        WHERE project_id = %s
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                        """,
                        (project_id, limit),
                    )
                    return [self._record(row) for row in cursor.fetchall()]
        except psycopg.Error as exc:
            raise RuntimeRunRepositoryError("运行任务数据库当前不可用") from exc

    def reconcile_interrupted(self) -> int:
        try:
            with psycopg.connect(self._database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE project_runtime_runs
                        SET status = 'failed',
                            error_message = 'Runtime Runner 服务重启，任务已中断',
                            finished_at = CURRENT_TIMESTAMP
                        WHERE status IN ('queued', 'running')
                        """
                    )
                    return cursor.rowcount
        except psycopg.Error as exc:
            raise RuntimeRunRepositoryError("运行任务数据库当前不可用") from exc

    def _update_status(
        self,
        run_id: str,
        assignments: str,
        values: tuple[object, ...],
    ) -> RuntimeRunRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE project_runtime_runs
                        SET {assignments}
                        WHERE id = %s
                        RETURNING {self._SELECT_COLUMNS}
                        """,
                        (*values, run_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeRunRepositoryError("运行任务不存在")
                    return self._record(row)
        except psycopg.Error as exc:
            raise RuntimeRunRepositoryError("运行任务数据库当前不可用") from exc

    @staticmethod
    def _record(row: tuple[object, ...]) -> RuntimeRunRecord:
        changed_files = row[10] if isinstance(row[10], list) else []
        return RuntimeRunRecord(
            id=str(row[0]),
            project_id=str(row[1]),
            mode=str(row[2]),
            trigger=str(row[3]),
            status=str(row[4]),
            snapshot_id=str(row[5]),
            materialized_path=str(row[6]),
            project_root=str(row[7]),
            entry_file=str(row[8]),
            log_path=str(row[9]),
            changed_files=tuple(str(item) for item in changed_files),
            decision_reason=str(row[11]),
            exit_code=int(row[12]) if row[12] is not None else None,
            error_message=str(row[13]) if row[13] is not None else None,
            created_at=row[14],  # type: ignore[arg-type]
            started_at=row[15],  # type: ignore[arg-type]
            finished_at=row[16],  # type: ignore[arg-type]
        )
