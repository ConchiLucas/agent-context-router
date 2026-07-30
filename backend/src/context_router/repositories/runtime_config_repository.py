from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol
from uuid import uuid4

import psycopg


class RuntimeConfigRepositoryError(RuntimeError):
    """Raised when project runtime files cannot be persisted."""


@dataclass(frozen=True)
class RuntimeConfigFileDraft:
    relative_path: str
    content: str
    executable: bool


@dataclass(frozen=True)
class RuntimeConfigFileRecord:
    id: str
    project_id: str
    mode: str
    relative_path: str
    content: str
    executable: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class RuntimeConfigStore(Protocol):
    def list_files(self, project_id: str, mode: str) -> list[RuntimeConfigFileRecord]: ...

    def replace_files(
        self,
        project_id: str,
        mode: str,
        files: list[RuntimeConfigFileDraft],
    ) -> list[RuntimeConfigFileRecord]: ...


class InMemoryRuntimeConfigRepository:
    def __init__(self) -> None:
        self._files: dict[tuple[str, str], list[RuntimeConfigFileRecord]] = {}
        self._lock = RLock()

    def list_files(self, project_id: str, mode: str) -> list[RuntimeConfigFileRecord]:
        with self._lock:
            return list(self._files.get((project_id, mode), []))

    def replace_files(
        self,
        project_id: str,
        mode: str,
        files: list[RuntimeConfigFileDraft],
    ) -> list[RuntimeConfigFileRecord]:
        now = datetime.now(timezone.utc)
        records = [
            RuntimeConfigFileRecord(
                id=uuid4().hex,
                project_id=project_id,
                mode=mode,
                relative_path=item.relative_path,
                content=item.content,
                executable=item.executable,
                sort_order=index,
                created_at=now,
                updated_at=now,
            )
            for index, item in enumerate(files)
        ]
        with self._lock:
            self._files[(project_id, mode)] = records
        return list(records)


class PostgresRuntimeConfigRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def list_files(self, project_id: str, mode: str) -> list[RuntimeConfigFileRecord]:
        try:
            with psycopg.connect(self._database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, project_id, mode, relative_path, content,
                               executable, sort_order, created_at, updated_at
                        FROM project_runtime_files
                        WHERE project_id = %s AND mode = %s
                        ORDER BY sort_order, relative_path, id
                        """,
                        (project_id, mode),
                    )
                    return [self._record(row) for row in cursor.fetchall()]
        except psycopg.Error as exc:
            raise RuntimeConfigRepositoryError("运行配置数据库当前不可用") from exc

    def replace_files(
        self,
        project_id: str,
        mode: str,
        files: list[RuntimeConfigFileDraft],
    ) -> list[RuntimeConfigFileRecord]:
        records: list[RuntimeConfigFileRecord] = []
        try:
            with psycopg.connect(self._database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM project_runtime_files
                        WHERE project_id = %s AND mode = %s
                        """,
                        (project_id, mode),
                    )
                    for index, item in enumerate(files):
                        cursor.execute(
                            """
                            INSERT INTO project_runtime_files (
                                id, project_id, mode, relative_path, content,
                                executable, sort_order
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            RETURNING id, project_id, mode, relative_path, content,
                                      executable, sort_order, created_at, updated_at
                            """,
                            (
                                uuid4().hex,
                                project_id,
                                mode,
                                item.relative_path,
                                item.content,
                                item.executable,
                                index,
                            ),
                        )
                        row = cursor.fetchone()
                        if row is not None:
                            records.append(self._record(row))
            return records
        except psycopg.Error as exc:
            raise RuntimeConfigRepositoryError("运行配置数据库当前不可用") from exc

    @staticmethod
    def _record(row: tuple[object, ...]) -> RuntimeConfigFileRecord:
        return RuntimeConfigFileRecord(
            id=str(row[0]),
            project_id=str(row[1]),
            mode=str(row[2]),
            relative_path=str(row[3]),
            content=str(row[4]),
            executable=bool(row[5]),
            sort_order=int(row[6]),
            created_at=row[7],  # type: ignore[arg-type]
            updated_at=row[8],  # type: ignore[arg-type]
        )
