from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

import psycopg

from context_router.services.visualization_security import VISUALIZATION_RETENTION_DAYS


class AiLogInvestigationRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AiLogInvestigationRecord:
    id: str
    workspace_id: str
    workspace_name: str
    task_id: int | None
    source: str
    description: str
    environment: str
    container_id: str
    container_name: str
    image: str
    project_id: str | None
    project_name: str | None
    project_kind: str | None
    severity: str
    error_title: str
    error_excerpt: str
    occurred_at: datetime | None
    occurrence_count: int
    log_line_count: int
    truncated: bool
    fingerprint: str
    idempotency_key: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AiLogInvestigationSaveResult:
    record: AiLogInvestigationRecord
    created: bool


class AiLogInvestigationStore(Protocol):
    def upsert(self, record: AiLogInvestigationRecord) -> AiLogInvestigationSaveResult: ...

    def list_records(
        self,
        *,
        workspace_id: str | None,
        severity: str | None,
        limit: int,
        offset: int,
        before_updated_at: datetime | None = None,
        before_id: str | None = None,
        task_id: int | None = None,
    ) -> list[AiLogInvestigationRecord]: ...

    def get(self, record_id: str) -> AiLogInvestigationRecord | None: ...


class InMemoryAiLogInvestigationRepository:
    def __init__(self) -> None:
        self._records: dict[str, AiLogInvestigationRecord] = {}
        self._ids_by_idempotency_key: dict[str, str] = {}

    def upsert(self, record: AiLogInvestigationRecord) -> AiLogInvestigationSaveResult:
        existing_id = self._ids_by_idempotency_key.get(record.idempotency_key)
        created = existing_id is None
        if existing_id is not None:
            current = self._records[existing_id]
            record = replace(record, id=current.id, created_at=current.created_at)
        self._records[record.id] = record
        self._ids_by_idempotency_key[record.idempotency_key] = record.id
        self._prune()
        return AiLogInvestigationSaveResult(record=record, created=created)

    def list_records(
        self,
        *,
        workspace_id: str | None,
        severity: str | None,
        limit: int,
        offset: int,
        before_updated_at: datetime | None = None,
        before_id: str | None = None,
        task_id: int | None = None,
    ) -> list[AiLogInvestigationRecord]:
        records = [
            record
            for record in self._records.values()
            if (workspace_id is None or record.workspace_id == workspace_id)
            and (severity is None or record.severity == severity)
            and (task_id is None or record.task_id == task_id)
            and record.updated_at
            >= datetime.now(UTC) - timedelta(days=VISUALIZATION_RETENTION_DAYS)
            and (
                before_updated_at is None
                or (record.updated_at, record.id) < (before_updated_at, before_id or "")
            )
        ]
        records.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return records[offset : offset + limit]

    def get(self, record_id: str) -> AiLogInvestigationRecord | None:
        record = self._records.get(record_id)
        if record and record.updated_at >= datetime.now(UTC) - timedelta(
            days=VISUALIZATION_RETENTION_DAYS
        ):
            return record
        return None

    def _prune(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=VISUALIZATION_RETENTION_DAYS)
        expired = [key for key, value in self._records.items() if value.updated_at < cutoff]
        for key in expired:
            record = self._records.pop(key)
            self._ids_by_idempotency_key.pop(record.idempotency_key, None)


class PostgresAiLogInvestigationRepository:
    _SELECT = """
        SELECT record.id, record.workspace_id, workspace.name, record.task_id,
               record.source, record.description, record.environment,
               record.container_id, record.container_name, record.image,
               record.project_id, record.project_name, record.project_kind,
               record.severity, record.error_title, record.error_excerpt,
               record.occurred_at, record.occurrence_count, record.log_line_count,
               record.truncated, record.fingerprint, record.idempotency_key,
               record.created_at, record.updated_at
        FROM ai_log_investigations AS record
        JOIN workspaces AS workspace ON workspace.id = record.workspace_id
    """

    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def upsert(self, record: AiLogInvestigationRecord) -> AiLogInvestigationSaveResult:
        if not self._database_url:
            raise AiLogInvestigationRepositoryError("日志可视化数据库尚未配置")
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    INSERT INTO ai_log_investigations (
                        id, workspace_id, task_id, source, description, environment,
                        container_id, container_name, image, project_id, project_name,
                        project_kind, severity, error_title, error_excerpt, occurred_at,
                        occurrence_count, log_line_count, truncated, fingerprint,
                        idempotency_key, created_at, updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (idempotency_key) DO UPDATE SET
                        source = EXCLUDED.source,
                        description = EXCLUDED.description,
                        environment = EXCLUDED.environment,
                        container_id = EXCLUDED.container_id,
                        container_name = EXCLUDED.container_name,
                        image = EXCLUDED.image,
                        project_id = EXCLUDED.project_id,
                        project_name = EXCLUDED.project_name,
                        project_kind = EXCLUDED.project_kind,
                        severity = EXCLUDED.severity,
                        error_title = EXCLUDED.error_title,
                        error_excerpt = EXCLUDED.error_excerpt,
                        occurred_at = EXCLUDED.occurred_at,
                        occurrence_count = EXCLUDED.occurrence_count,
                        log_line_count = EXCLUDED.log_line_count,
                        truncated = EXCLUDED.truncated,
                        updated_at = EXCLUDED.updated_at
                    RETURNING id, (xmax = 0) AS created
                    """,
                    (
                        record.id,
                        record.workspace_id,
                        record.task_id,
                        record.source,
                        record.description,
                        record.environment,
                        record.container_id,
                        record.container_name,
                        record.image,
                        record.project_id,
                        record.project_name,
                        record.project_kind,
                        record.severity,
                        record.error_title,
                        record.error_excerpt,
                        record.occurred_at,
                        record.occurrence_count,
                        record.log_line_count,
                        record.truncated,
                        record.fingerprint,
                        record.idempotency_key,
                        record.created_at,
                        record.updated_at,
                    ),
                ).fetchone()
                if row is None:
                    raise AiLogInvestigationRepositoryError("日志可视化记录写入失败")
                connection.execute(
                    """DELETE FROM ai_log_investigations
                       WHERE updated_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')""",
                    (VISUALIZATION_RETENTION_DAYS,),
                )
                stored = self._get_with_connection(connection, str(row[0]))
        except psycopg.Error as exc:
            raise AiLogInvestigationRepositoryError("日志可视化记录写入失败") from exc
        if stored is None:
            raise AiLogInvestigationRepositoryError("日志可视化记录写入后无法读取")
        return AiLogInvestigationSaveResult(record=stored, created=bool(row[1]))

    def list_records(
        self,
        *,
        workspace_id: str | None,
        severity: str | None,
        limit: int,
        offset: int,
        before_updated_at: datetime | None = None,
        before_id: str | None = None,
        task_id: int | None = None,
    ) -> list[AiLogInvestigationRecord]:
        if not self._database_url:
            raise AiLogInvestigationRepositoryError("日志可视化数据库尚未配置")
        clauses: list[str] = ["record.updated_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')"]
        parameters: list[object] = [VISUALIZATION_RETENTION_DAYS]
        if workspace_id is not None:
            clauses.append("record.workspace_id = %s")
            parameters.append(workspace_id)
        if severity is not None:
            clauses.append("record.severity = %s")
            parameters.append(severity)
        if before_updated_at is not None:
            clauses.append("(record.updated_at, record.id) < (%s, %s)")
            parameters.extend((before_updated_at, before_id or ""))
        if task_id is not None:
            clauses.append("record.task_id = %s")
            parameters.append(task_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.extend((limit, offset))
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    f"""{self._SELECT}
                    {where}
                    ORDER BY record.updated_at DESC, record.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(parameters),
                ).fetchall()
        except psycopg.Error as exc:
            raise AiLogInvestigationRepositoryError("日志可视化列表读取失败") from exc
        return [self._record(row) for row in rows]

    def get(self, record_id: str) -> AiLogInvestigationRecord | None:
        if not self._database_url:
            raise AiLogInvestigationRepositoryError("日志可视化数据库尚未配置")
        try:
            with psycopg.connect(self._database_url) as connection:
                return self._get_with_connection(connection, record_id)
        except psycopg.Error as exc:
            raise AiLogInvestigationRepositoryError("日志可视化详情读取失败") from exc

    def _get_with_connection(
        self,
        connection: psycopg.Connection[object],
        record_id: str,
    ) -> AiLogInvestigationRecord | None:
        row = connection.execute(
            f"""{self._SELECT}
                WHERE record.id = %s
                  AND record.updated_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')""",
            (record_id, VISUALIZATION_RETENTION_DAYS),
        ).fetchone()
        return self._record(row) if row else None

    @staticmethod
    def _record(row: tuple[object, ...]) -> AiLogInvestigationRecord:
        return AiLogInvestigationRecord(
            id=str(row[0]),
            workspace_id=str(row[1]),
            workspace_name=str(row[2]),
            task_id=int(row[3]) if row[3] is not None else None,
            source=str(row[4]),
            description=str(row[5]),
            environment=str(row[6]),
            container_id=str(row[7]),
            container_name=str(row[8]),
            image=str(row[9]),
            project_id=str(row[10]) if row[10] is not None else None,
            project_name=str(row[11]) if row[11] is not None else None,
            project_kind=str(row[12]) if row[12] is not None else None,
            severity=str(row[13]),
            error_title=str(row[14]),
            error_excerpt=str(row[15]),
            occurred_at=row[16] if isinstance(row[16], datetime) else None,
            occurrence_count=int(row[17]),
            log_line_count=int(row[18]),
            truncated=bool(row[19]),
            fingerprint=str(row[20]),
            idempotency_key=str(row[21]),
            created_at=row[22],  # type: ignore[arg-type]
            updated_at=row[23],  # type: ignore[arg-type]
        )
