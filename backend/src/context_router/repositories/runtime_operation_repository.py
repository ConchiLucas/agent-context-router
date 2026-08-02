from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb


class RuntimeOperationRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeOperationStepDraft:
    owner_type: str
    owner_id: str
    mode: str
    snapshot_id: str
    snapshot_relative_path: str
    changed_files: tuple[str, ...]
    decision_reason: str
    log_relative_path: str


@dataclass(frozen=True, slots=True)
class RuntimeOperationDraft:
    task_id: int
    workspace_id: str
    kind: str
    trigger: str
    changed_files: tuple[str, ...]
    steps: tuple[RuntimeOperationStepDraft, ...]


@dataclass(frozen=True, slots=True)
class RuntimeStepResult:
    exit_code: int
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeOperationRecord:
    id: str
    task_id: int
    workspace_id: str
    kind: str
    trigger: str
    status: str
    changed_files: tuple[str, ...]
    current_step: int
    runner_id: str | None
    lease_token_hash: str | None
    lease_expires_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    leased_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    last_heartbeat_at: datetime | None


@dataclass(frozen=True, slots=True)
class RuntimeOperationStepRecord(RuntimeOperationStepDraft):
    id: str
    operation_id: str
    sequence: int
    status: str
    exit_code: int | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class RuntimeOperationLease:
    operation: RuntimeOperationRecord
    steps: tuple[RuntimeOperationStepRecord, ...]
    lease_token: str


class RuntimeOperationStore(Protocol):
    def create_operation(self, draft: RuntimeOperationDraft) -> RuntimeOperationRecord: ...
    def get_operation(self, operation_id: str) -> RuntimeOperationRecord | None: ...
    def list_steps(self, operation_id: str) -> list[RuntimeOperationStepRecord]: ...
    def lease_next(self, runner_id: str, lease_seconds: int) -> RuntimeOperationLease | None: ...
    def mark_started(self, operation_id: str, lease_token: str) -> RuntimeOperationRecord: ...
    def heartbeat(
        self, operation_id: str, lease_token: str, lease_seconds: int
    ) -> RuntimeOperationRecord: ...
    def complete_step(
        self, operation_id: str, step_id: str, lease_token: str, result: RuntimeStepResult
    ) -> RuntimeOperationRecord: ...
    def reconcile_expired(self) -> int: ...


class InMemoryRuntimeOperationRepository:
    def __init__(self) -> None:
        self._operations: dict[str, RuntimeOperationRecord] = {}
        self._steps: dict[str, list[RuntimeOperationStepRecord]] = {}
        self._lock = RLock()

    def create_operation(self, draft: RuntimeOperationDraft) -> RuntimeOperationRecord:
        if not draft.steps:
            raise RuntimeOperationRepositoryError("运行操作至少需要一个步骤")
        with self._lock:
            if any(
                item.workspace_id == draft.workspace_id
                and item.status in {"queued", "leased", "running"}
                for item in self._operations.values()
            ):
                raise RuntimeOperationRepositoryError("工作空间已有运行中的操作")
            now = datetime.now(UTC)
            operation = RuntimeOperationRecord(
                id=uuid4().hex,
                task_id=draft.task_id,
                workspace_id=draft.workspace_id,
                kind=draft.kind,
                trigger=draft.trigger,
                status="queued",
                changed_files=tuple(draft.changed_files),
                current_step=0,
                runner_id=None,
                lease_token_hash=None,
                lease_expires_at=None,
                error_code=None,
                error_message=None,
                created_at=now,
                leased_at=None,
                started_at=None,
                finished_at=None,
                last_heartbeat_at=None,
            )
            steps = [
                RuntimeOperationStepRecord(
                    owner_type=item.owner_type,
                    owner_id=item.owner_id,
                    mode=item.mode,
                    snapshot_id=item.snapshot_id,
                    snapshot_relative_path=item.snapshot_relative_path,
                    changed_files=item.changed_files,
                    decision_reason=item.decision_reason,
                    log_relative_path=item.log_relative_path,
                    id=uuid4().hex,
                    operation_id=operation.id,
                    sequence=index,
                    status="queued",
                    exit_code=None,
                    error_code=None,
                    error_message=None,
                    started_at=None,
                    finished_at=None,
                )
                for index, item in enumerate(draft.steps)
            ]
            self._operations[operation.id] = operation
            self._steps[operation.id] = steps
            return operation

    def get_operation(self, operation_id: str) -> RuntimeOperationRecord | None:
        with self._lock:
            return self._operations.get(operation_id)

    def list_steps(self, operation_id: str) -> list[RuntimeOperationStepRecord]:
        with self._lock:
            return list(self._steps.get(operation_id, ()))

    def lease_next(self, runner_id: str, lease_seconds: int) -> RuntimeOperationLease | None:
        with self._lock:
            queued = sorted(
                (item for item in self._operations.values() if item.status == "queued"),
                key=lambda item: (item.created_at, item.id),
            )
            if not queued:
                return None
            operation = queued[0]
            token = secrets.token_urlsafe(32)
            now = datetime.now(UTC)
            leased = replace(
                operation,
                status="leased",
                runner_id=runner_id,
                lease_token_hash=_digest(token),
                leased_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                last_heartbeat_at=now,
            )
            self._operations[operation.id] = leased
            return RuntimeOperationLease(leased, tuple(self._steps[operation.id]), token)

    def mark_started(self, operation_id: str, lease_token: str) -> RuntimeOperationRecord:
        with self._lock:
            operation = self._authorized(operation_id, lease_token)
            now = datetime.now(UTC)
            updated = replace(operation, status="running", started_at=now, last_heartbeat_at=now)
            self._operations[operation_id] = updated
            steps = self._steps[operation_id]
            steps[0] = replace(steps[0], status="running", started_at=now)
            return updated

    def heartbeat(
        self, operation_id: str, lease_token: str, lease_seconds: int
    ) -> RuntimeOperationRecord:
        with self._lock:
            operation = self._authorized(operation_id, lease_token)
            now = datetime.now(UTC)
            updated = replace(
                operation,
                last_heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            self._operations[operation_id] = updated
            return updated

    def complete_step(
        self, operation_id: str, step_id: str, lease_token: str, result: RuntimeStepResult
    ) -> RuntimeOperationRecord:
        with self._lock:
            operation = self._authorized(operation_id, lease_token)
            steps = self._steps[operation_id]
            index = next((i for i, item in enumerate(steps) if item.id == step_id), None)
            if index is None:
                raise RuntimeOperationRepositoryError("运行步骤不存在")
            now = datetime.now(UTC)
            success = result.exit_code == 0
            steps[index] = replace(
                steps[index],
                status="succeeded" if success else "failed",
                exit_code=result.exit_code,
                error_code=result.error_code,
                error_message=result.error_message,
                finished_at=now,
            )
            if not success:
                for remaining in range(index + 1, len(steps)):
                    steps[remaining] = replace(steps[remaining], status="skipped", finished_at=now)
                updated = replace(
                    operation,
                    status="failed",
                    error_code=result.error_code or "runtime_exit_nonzero",
                    error_message=result.error_message,
                    finished_at=now,
                )
            elif index + 1 == len(steps):
                updated = replace(
                    operation, status="succeeded", current_step=index, finished_at=now
                )
            else:
                steps[index + 1] = replace(steps[index + 1], status="running", started_at=now)
                updated = replace(operation, current_step=index + 1, last_heartbeat_at=now)
            self._operations[operation_id] = updated
            return updated

    def reconcile_expired(self) -> int:
        now = datetime.now(UTC)
        with self._lock:
            expired = [
                item
                for item in self._operations.values()
                if item.status in {"leased", "running"}
                and item.lease_expires_at
                and item.lease_expires_at < now
            ]
            for operation in expired:
                self._operations[operation.id] = replace(
                    operation,
                    status="interrupted",
                    error_code="runtime_interrupted",
                    error_message="宿主机 Runner 租约已过期",
                    finished_at=now,
                )
            return len(expired)

    def _authorized(self, operation_id: str, lease_token: str) -> RuntimeOperationRecord:
        operation = self._operations.get(operation_id)
        if operation is None:
            raise RuntimeOperationRepositoryError("运行操作不存在")
        if not operation.lease_token_hash or not hmac.compare_digest(
            operation.lease_token_hash, _digest(lease_token)
        ):
            raise RuntimeOperationRepositoryError("运行租约无效")
        return operation


class PostgresRuntimeOperationRepository:
    _OPERATION_COLUMNS = """
        id, task_id, workspace_id, kind, trigger, status, changed_files,
        current_step, runner_id, lease_token_hash, lease_expires_at,
        error_code, error_message, created_at, leased_at, started_at,
        finished_at, last_heartbeat_at
    """
    _STEP_COLUMNS = """
        id, operation_id, sequence, owner_type, owner_id, mode, snapshot_id,
        snapshot_relative_path, changed_files, decision_reason, log_relative_path,
        status, exit_code, error_code, error_message, started_at, finished_at
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def create_operation(self, draft: RuntimeOperationDraft) -> RuntimeOperationRecord:
        if not draft.steps:
            raise RuntimeOperationRepositoryError("运行操作至少需要一个步骤")
        operation_id = uuid4().hex
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    f"""INSERT INTO runtime_operations
                        (id, task_id, workspace_id, kind, trigger, status, changed_files)
                        VALUES (%s, %s, %s, %s, %s, 'queued', %s)
                        RETURNING {self._OPERATION_COLUMNS}""",
                    (
                        operation_id,
                        draft.task_id,
                        draft.workspace_id,
                        draft.kind,
                        draft.trigger,
                        Jsonb(list(draft.changed_files)),
                    ),
                ).fetchone()
                for sequence, step in enumerate(draft.steps):
                    connection.execute(
                        """INSERT INTO runtime_operation_steps
                           (id, operation_id, sequence, owner_type, owner_id, mode,
                            status, snapshot_id, snapshot_relative_path, changed_files,
                            decision_reason, log_relative_path)
                           VALUES (%s, %s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s, %s)""",
                        (
                            uuid4().hex,
                            operation_id,
                            sequence,
                            step.owner_type,
                            step.owner_id,
                            step.mode,
                            step.snapshot_id,
                            step.snapshot_relative_path,
                            Jsonb(list(step.changed_files)),
                            step.decision_reason,
                            step.log_relative_path,
                        ),
                    )
            if row is None:
                raise RuntimeOperationRepositoryError("运行操作创建失败")
            return self._operation(row)
        except psycopg.errors.UniqueViolation as exc:
            raise RuntimeOperationRepositoryError("工作空间或项目已有运行中的操作") from exc
        except psycopg.Error as exc:
            raise RuntimeOperationRepositoryError("运行操作数据库当前不可用") from exc

    def get_operation(self, operation_id: str) -> RuntimeOperationRecord | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    f"""SELECT {self._OPERATION_COLUMNS}
                        FROM runtime_operations WHERE id = %s""",
                    (operation_id,),
                ).fetchone()
            return self._operation(row) if row else None
        except psycopg.Error as exc:
            raise RuntimeOperationRepositoryError("运行操作数据库当前不可用") from exc

    def list_steps(self, operation_id: str) -> list[RuntimeOperationStepRecord]:
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    f"""SELECT {self._STEP_COLUMNS}
                        FROM runtime_operation_steps
                        WHERE operation_id = %s ORDER BY sequence""",
                    (operation_id,),
                ).fetchall()
            return [self._step(row) for row in rows]
        except psycopg.Error as exc:
            raise RuntimeOperationRepositoryError("运行操作数据库当前不可用") from exc

    def lease_next(self, runner_id: str, lease_seconds: int) -> RuntimeOperationLease | None:
        token = secrets.token_urlsafe(32)
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    f"""SELECT {self._OPERATION_COLUMNS}
                        FROM runtime_operations
                        WHERE status = 'queued'
                        ORDER BY created_at, id
                        FOR UPDATE SKIP LOCKED LIMIT 1"""
                ).fetchone()
                if row is None:
                    return None
                operation_id = str(row[0])
                leased_row = connection.execute(
                    f"""UPDATE runtime_operations
                        SET status = 'leased', runner_id = %s, lease_token_hash = %s,
                            leased_at = CURRENT_TIMESTAMP,
                            lease_expires_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                            last_heartbeat_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        RETURNING {self._OPERATION_COLUMNS}""",
                    (runner_id, _digest(token), lease_seconds, operation_id),
                ).fetchone()
                step_rows = connection.execute(
                    f"""SELECT {self._STEP_COLUMNS}
                        FROM runtime_operation_steps
                        WHERE operation_id = %s ORDER BY sequence""",
                    (operation_id,),
                ).fetchall()
            if leased_row is None:
                raise RuntimeOperationRepositoryError("运行操作租约创建失败")
            return RuntimeOperationLease(
                self._operation(leased_row),
                tuple(self._step(item) for item in step_rows),
                token,
            )
        except psycopg.Error as exc:
            raise RuntimeOperationRepositoryError("运行操作数据库当前不可用") from exc

    def mark_started(self, operation_id: str, lease_token: str) -> RuntimeOperationRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                self._authorize(connection, operation_id, lease_token)
                row = connection.execute(
                    f"""UPDATE runtime_operations
                        SET status = 'running',
                            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                            last_heartbeat_at = CURRENT_TIMESTAMP
                        WHERE id = %s RETURNING {self._OPERATION_COLUMNS}""",
                    (operation_id,),
                ).fetchone()
                connection.execute(
                    """UPDATE runtime_operation_steps
                       SET status = 'running', started_at = CURRENT_TIMESTAMP
                       WHERE operation_id = %s AND sequence = 0 AND status = 'queued'""",
                    (operation_id,),
                )
            if row is None:
                raise RuntimeOperationRepositoryError("运行操作不存在")
            return self._operation(row)
        except psycopg.Error as exc:
            raise RuntimeOperationRepositoryError("运行操作数据库当前不可用") from exc

    def heartbeat(
        self, operation_id: str, lease_token: str, lease_seconds: int
    ) -> RuntimeOperationRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                self._authorize(connection, operation_id, lease_token)
                row = connection.execute(
                    f"""UPDATE runtime_operations
                        SET last_heartbeat_at = CURRENT_TIMESTAMP,
                            lease_expires_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')
                        WHERE id = %s RETURNING {self._OPERATION_COLUMNS}""",
                    (lease_seconds, operation_id),
                ).fetchone()
            if row is None:
                raise RuntimeOperationRepositoryError("运行操作不存在")
            return self._operation(row)
        except psycopg.Error as exc:
            raise RuntimeOperationRepositoryError("运行操作数据库当前不可用") from exc

    def complete_step(
        self, operation_id: str, step_id: str, lease_token: str, result: RuntimeStepResult
    ) -> RuntimeOperationRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                self._authorize(connection, operation_id, lease_token)
                step_row = connection.execute(
                    """SELECT sequence FROM runtime_operation_steps
                       WHERE id = %s AND operation_id = %s FOR UPDATE""",
                    (step_id, operation_id),
                ).fetchone()
                if step_row is None:
                    raise RuntimeOperationRepositoryError("运行步骤不存在")
                sequence = int(step_row[0])
                success = result.exit_code == 0
                connection.execute(
                    """UPDATE runtime_operation_steps
                       SET status = %s, exit_code = %s, error_code = %s,
                           error_message = %s, finished_at = CURRENT_TIMESTAMP
                       WHERE id = %s""",
                    (
                        "succeeded" if success else "failed",
                        result.exit_code,
                        result.error_code,
                        result.error_message,
                        step_id,
                    ),
                )
                remaining = connection.execute(
                    """SELECT id FROM runtime_operation_steps
                       WHERE operation_id = %s AND sequence > %s ORDER BY sequence""",
                    (operation_id, sequence),
                ).fetchall()
                if not success:
                    connection.execute(
                        """UPDATE runtime_operation_steps
                           SET status = 'skipped', finished_at = CURRENT_TIMESTAMP
                           WHERE operation_id = %s AND sequence > %s AND status = 'queued'""",
                        (operation_id, sequence),
                    )
                    assignments = (
                        "status = 'failed', error_code = %s, error_message = %s, "
                        "finished_at = CURRENT_TIMESTAMP"
                    )
                    values: tuple[object, ...] = (
                        result.error_code or "runtime_exit_nonzero",
                        result.error_message,
                    )
                elif not remaining:
                    assignments = (
                        "status = 'succeeded', current_step = %s, finished_at = CURRENT_TIMESTAMP"
                    )
                    values = (sequence,)
                else:
                    next_id = str(remaining[0][0])
                    connection.execute(
                        """UPDATE runtime_operation_steps
                           SET status = 'running', started_at = CURRENT_TIMESTAMP
                           WHERE id = %s""",
                        (next_id,),
                    )
                    assignments = "current_step = %s, last_heartbeat_at = CURRENT_TIMESTAMP"
                    values = (sequence + 1,)
                row = connection.execute(
                    f"""UPDATE runtime_operations SET {assignments}
                        WHERE id = %s RETURNING {self._OPERATION_COLUMNS}""",
                    (*values, operation_id),
                ).fetchone()
            if row is None:
                raise RuntimeOperationRepositoryError("运行操作不存在")
            return self._operation(row)
        except psycopg.Error as exc:
            raise RuntimeOperationRepositoryError("运行操作数据库当前不可用") from exc

    def reconcile_expired(self) -> int:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    """UPDATE runtime_operations
                       SET status = 'interrupted', error_code = 'runtime_interrupted',
                           error_message = '宿主机 Runner 租约已过期',
                           finished_at = CURRENT_TIMESTAMP
                       WHERE status IN ('leased', 'running')
                         AND lease_expires_at < CURRENT_TIMESTAMP"""
                )
                return cursor.rowcount
        except psycopg.Error as exc:
            raise RuntimeOperationRepositoryError("运行操作数据库当前不可用") from exc

    @staticmethod
    def _authorize(
        connection: psycopg.Connection[tuple[object, ...]],
        operation_id: str,
        lease_token: str,
    ) -> None:
        row = connection.execute(
            """SELECT lease_token_hash FROM runtime_operations
               WHERE id = %s AND status IN ('leased', 'running') FOR UPDATE""",
            (operation_id,),
        ).fetchone()
        if row is None or not row[0] or not hmac.compare_digest(str(row[0]), _digest(lease_token)):
            raise RuntimeOperationRepositoryError("运行租约无效")

    @staticmethod
    def _operation(row: tuple[object, ...]) -> RuntimeOperationRecord:
        return RuntimeOperationRecord(
            id=str(row[0]),
            task_id=int(row[1]),
            workspace_id=str(row[2]),
            kind=str(row[3]),
            trigger=str(row[4]),
            status=str(row[5]),
            changed_files=tuple(row[6]),
            current_step=int(row[7]),
            runner_id=str(row[8]) if row[8] else None,
            lease_token_hash=str(row[9]) if row[9] else None,
            lease_expires_at=row[10],  # type: ignore[arg-type]
            error_code=str(row[11]) if row[11] else None,
            error_message=str(row[12]) if row[12] else None,
            created_at=row[13],  # type: ignore[arg-type]
            leased_at=row[14],  # type: ignore[arg-type]
            started_at=row[15],  # type: ignore[arg-type]
            finished_at=row[16],  # type: ignore[arg-type]
            last_heartbeat_at=row[17],  # type: ignore[arg-type]
        )

    @staticmethod
    def _step(row: tuple[object, ...]) -> RuntimeOperationStepRecord:
        return RuntimeOperationStepRecord(
            id=str(row[0]),
            operation_id=str(row[1]),
            sequence=int(row[2]),
            owner_type=str(row[3]),
            owner_id=str(row[4]),
            mode=str(row[5]),
            snapshot_id=str(row[6]),
            snapshot_relative_path=str(row[7]),
            changed_files=tuple(row[8]),
            decision_reason=str(row[9]),
            log_relative_path=str(row[10]),
            status=str(row[11]),
            exit_code=int(row[12]) if row[12] is not None else None,
            error_code=str(row[13]) if row[13] else None,
            error_message=str(row[14]) if row[14] else None,
            started_at=row[15],  # type: ignore[arg-type]
            finished_at=row[16],  # type: ignore[arg-type]
        )


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
