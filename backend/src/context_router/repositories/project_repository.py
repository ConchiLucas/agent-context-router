from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

import psycopg


class ProjectRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    id: str
    name: str
    agents_path: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ProjectStore(Protocol):
    def list_projects(self) -> list[ProjectRecord]: ...

    def create_project(
        self,
        *,
        project_id: str,
        name: str,
        agents_path: str,
        enabled: bool,
    ) -> None: ...

    def update_project(self, project_id: str, *, name: str, agents_path: str) -> None: ...

    def set_project_enabled(self, project_id: str, *, enabled: bool) -> None: ...

    def delete_project(self, project_id: str) -> None: ...


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[str, ProjectRecord] = {}

    def list_projects(self) -> list[ProjectRecord]:
        return list(self._projects.values())

    def create_project(
        self,
        *,
        project_id: str,
        name: str,
        agents_path: str,
        enabled: bool,
    ) -> None:
        if any(record.agents_path == agents_path for record in self._projects.values()):
            raise ProjectRepositoryError("这个 AGENTS.md 已经添加")
        now = datetime.now(UTC)
        self._projects[project_id] = ProjectRecord(
            id=project_id,
            name=name,
            agents_path=agents_path,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )

    def update_project(self, project_id: str, *, name: str, agents_path: str) -> None:
        record = self._get(project_id)
        if any(
            item.id != project_id and item.agents_path == agents_path
            for item in self._projects.values()
        ):
            raise ProjectRepositoryError("这个 AGENTS.md 已经添加")
        self._projects[project_id] = replace(
            record,
            name=name,
            agents_path=agents_path,
            updated_at=datetime.now(UTC),
        )

    def set_project_enabled(self, project_id: str, *, enabled: bool) -> None:
        record = self._get(project_id)
        self._projects[project_id] = replace(
            record,
            enabled=enabled,
            updated_at=datetime.now(UTC),
        )

    def delete_project(self, project_id: str) -> None:
        self._get(project_id)
        del self._projects[project_id]

    def _get(self, project_id: str) -> ProjectRecord:
        record = self._projects.get(project_id)
        if record is None:
            raise ProjectRepositoryError("项目不存在")
        return record


class PostgresProjectRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.strip()

    def list_projects(self) -> list[ProjectRecord]:
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT id, name, agents_path, enabled, created_at, updated_at
                    FROM document_projects
                    ORDER BY created_at, id
                    """
                ).fetchall()
        except psycopg.Error as exc:
            raise ProjectRepositoryError("项目配置读取失败") from exc
        return [self._record(row) for row in rows]

    def create_project(
        self,
        *,
        project_id: str,
        name: str,
        agents_path: str,
        enabled: bool,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """
                    INSERT INTO document_projects (id, name, agents_path, enabled)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (project_id, name, agents_path, enabled),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProjectRepositoryError("这个 AGENTS.md 已经添加") from exc
        except psycopg.Error as exc:
            raise ProjectRepositoryError("项目配置写入失败") from exc

    def update_project(self, project_id: str, *, name: str, agents_path: str) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    """
                    UPDATE document_projects
                    SET name = %s, agents_path = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (name, agents_path, project_id),
                )
                if cursor.rowcount == 0:
                    raise ProjectRepositoryError("项目不存在")
        except psycopg.errors.UniqueViolation as exc:
            raise ProjectRepositoryError("这个 AGENTS.md 已经添加") from exc
        except ProjectRepositoryError:
            raise
        except psycopg.Error as exc:
            raise ProjectRepositoryError("项目配置更新失败") from exc

    def set_project_enabled(self, project_id: str, *, enabled: bool) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    """
                    UPDATE document_projects
                    SET enabled = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (enabled, project_id),
                )
                if cursor.rowcount == 0:
                    raise ProjectRepositoryError("项目不存在")
        except ProjectRepositoryError:
            raise
        except psycopg.Error as exc:
            raise ProjectRepositoryError("项目启停状态更新失败") from exc

    def delete_project(self, project_id: str) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    "DELETE FROM document_projects WHERE id = %s",
                    (project_id,),
                )
                if cursor.rowcount == 0:
                    raise ProjectRepositoryError("项目不存在")
        except ProjectRepositoryError:
            raise
        except psycopg.Error as exc:
            raise ProjectRepositoryError("项目配置删除失败") from exc

    @staticmethod
    def _record(row: tuple[object, ...]) -> ProjectRecord:
        return ProjectRecord(
            id=str(row[0]),
            name=str(row[1]),
            agents_path=str(row[2]),
            enabled=bool(row[3]),
            created_at=row[4],  # type: ignore[arg-type]
            updated_at=row[5],  # type: ignore[arg-type]
        )
