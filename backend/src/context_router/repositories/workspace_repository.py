from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Protocol

import psycopg

DEFAULT_WORKSPACE_TYPE = "公司项目"
PROJECT_ENTRY_FILENAME = "AGENTS.md"


class WorkspaceRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WorkspaceRecord:
    id: str
    name: str
    workspace_type: str
    root_path: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class InMemoryWorkspaceState:
    """Shared backing used by the in-memory workspace and project repositories."""

    workspaces: dict[str, WorkspaceRecord] = field(default_factory=dict)
    projects: dict[str, Any] = field(default_factory=dict)


def derive_workspace_root_path(agents_path: str) -> str:
    return str(PurePosixPath(agents_path).parent)


def build_project_agents_path(root_path: str, document_relative_path: str) -> str:
    return str(PurePosixPath(root_path) / PurePosixPath(document_relative_path))


class WorkspaceStore(Protocol):
    def list_workspaces(self) -> list[WorkspaceRecord]: ...

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord: ...

    def create_workspace(
        self,
        *,
        workspace_id: str,
        name: str,
        workspace_type: str,
        root_path: str,
        enabled: bool,
    ) -> None: ...

    def update_workspace(
        self,
        workspace_id: str,
        *,
        name: str,
        workspace_type: str,
        root_path: str,
    ) -> None: ...

    def set_workspace_enabled(self, workspace_id: str, *, enabled: bool) -> None: ...

    def delete_workspace(self, workspace_id: str) -> None: ...


class InMemoryWorkspaceRepository:
    def __init__(self, state: InMemoryWorkspaceState | None = None) -> None:
        self._state = state or InMemoryWorkspaceState()

    @property
    def state(self) -> InMemoryWorkspaceState:
        return self._state

    def list_workspaces(self) -> list[WorkspaceRecord]:
        return list(self._state.workspaces.values())

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord:
        record = self._state.workspaces.get(workspace_id)
        if record is None:
            raise WorkspaceRepositoryError("工作空间不存在")
        return record

    def create_workspace(
        self,
        *,
        workspace_id: str,
        name: str,
        workspace_type: str = DEFAULT_WORKSPACE_TYPE,
        root_path: str,
        enabled: bool,
    ) -> None:
        if workspace_id in self._state.workspaces:
            raise WorkspaceRepositoryError("工作空间已存在")
        if any(item.root_path == root_path for item in self._state.workspaces.values()):
            raise WorkspaceRepositoryError("这个工作空间目录已经添加")
        now = datetime.now(UTC)
        self._state.workspaces[workspace_id] = WorkspaceRecord(
            id=workspace_id,
            name=name,
            workspace_type=workspace_type,
            root_path=root_path,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )

    def update_workspace(
        self,
        workspace_id: str,
        *,
        name: str,
        workspace_type: str,
        root_path: str,
    ) -> None:
        record = self.get_workspace(workspace_id)
        if any(
            item.id != workspace_id and item.root_path == root_path
            for item in self._state.workspaces.values()
        ):
            raise WorkspaceRepositoryError("这个工作空间目录已经添加")
        now = datetime.now(UTC)
        self._state.workspaces[workspace_id] = replace(
            record,
            name=name,
            workspace_type=workspace_type,
            root_path=root_path,
            updated_at=now,
        )
        for project_id, project in list(self._state.projects.items()):
            if getattr(project, "workspace_id", None) != workspace_id:
                continue
            self._state.projects[project_id] = replace(
                project,
                project_type=workspace_type,
                agents_path=build_project_agents_path(
                    root_path,
                    str(project.document_relative_path),
                ),
                workspace_name=name,
                workspace_type=workspace_type,
                workspace_root_path=root_path,
                updated_at=now,
            )

    def set_workspace_enabled(self, workspace_id: str, *, enabled: bool) -> None:
        record = self.get_workspace(workspace_id)
        self._state.workspaces[workspace_id] = replace(
            record,
            enabled=enabled,
            updated_at=datetime.now(UTC),
        )
        for project_id, project in list(self._state.projects.items()):
            if getattr(project, "workspace_id", None) == workspace_id:
                self._state.projects[project_id] = replace(
                    project,
                    workspace_enabled=enabled,
                )

    def delete_workspace(self, workspace_id: str) -> None:
        self.get_workspace(workspace_id)
        remaining_projects = {
            project_id: project
            for project_id, project in self._state.projects.items()
            if getattr(project, "workspace_id", None) != workspace_id
        }
        self._state.projects.clear()
        self._state.projects.update(remaining_projects)
        del self._state.workspaces[workspace_id]


class PostgresWorkspaceRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.strip()

    def list_workspaces(self) -> list[WorkspaceRecord]:
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT id, name, workspace_type, root_path, enabled, created_at, updated_at
                    FROM workspaces
                    ORDER BY created_at, id
                    """
                ).fetchall()
        except psycopg.Error as exc:
            raise WorkspaceRepositoryError("工作空间配置读取失败") from exc
        return [self._record(row) for row in rows]

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    SELECT id, name, workspace_type, root_path, enabled, created_at, updated_at
                    FROM workspaces
                    WHERE id = %s
                    """,
                    (workspace_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise WorkspaceRepositoryError("工作空间配置读取失败") from exc
        if row is None:
            raise WorkspaceRepositoryError("工作空间不存在")
        return self._record(row)

    def create_workspace(
        self,
        *,
        workspace_id: str,
        name: str,
        workspace_type: str = DEFAULT_WORKSPACE_TYPE,
        root_path: str,
        enabled: bool,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """
                    INSERT INTO workspaces
                        (id, name, workspace_type, root_path, enabled)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (workspace_id, name, workspace_type, root_path, enabled),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise WorkspaceRepositoryError("这个工作空间目录已经添加") from exc
        except psycopg.Error as exc:
            raise WorkspaceRepositoryError("工作空间配置写入失败") from exc

    def update_workspace(
        self,
        workspace_id: str,
        *,
        name: str,
        workspace_type: str,
        root_path: str,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    """
                    UPDATE workspaces
                    SET name = %s, workspace_type = %s, root_path = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (name, workspace_type, root_path, workspace_id),
                )
                if cursor.rowcount == 0:
                    raise WorkspaceRepositoryError("工作空间不存在")
                projects = connection.execute(
                    """
                    SELECT id, document_relative_path
                    FROM document_projects
                    WHERE workspace_id = %s
                    """,
                    (workspace_id,),
                ).fetchall()
                for project_id, document_relative_path in projects:
                    connection.execute(
                        """
                        UPDATE document_projects
                        SET project_type = %s, agents_path = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (
                            workspace_type,
                            build_project_agents_path(
                                root_path,
                                str(document_relative_path),
                            ),
                            project_id,
                        ),
                    )
        except psycopg.errors.UniqueViolation as exc:
            raise WorkspaceRepositoryError("这个工作空间目录已经添加") from exc
        except WorkspaceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise WorkspaceRepositoryError("工作空间配置更新失败") from exc

    def set_workspace_enabled(self, workspace_id: str, *, enabled: bool) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    """
                    UPDATE workspaces
                    SET enabled = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (enabled, workspace_id),
                )
                if cursor.rowcount == 0:
                    raise WorkspaceRepositoryError("工作空间不存在")
        except WorkspaceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise WorkspaceRepositoryError("工作空间启停状态更新失败") from exc

    def delete_workspace(self, workspace_id: str) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    "DELETE FROM workspaces WHERE id = %s",
                    (workspace_id,),
                )
                if cursor.rowcount == 0:
                    raise WorkspaceRepositoryError("工作空间不存在")
        except WorkspaceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise WorkspaceRepositoryError("工作空间配置删除失败") from exc

    @staticmethod
    def _record(row: tuple[object, ...]) -> WorkspaceRecord:
        return WorkspaceRecord(
            id=str(row[0]),
            name=str(row[1]),
            workspace_type=str(row[2]),
            root_path=str(row[3]),
            enabled=bool(row[4]),
            created_at=row[5],  # type: ignore[arg-type]
            updated_at=row[6],  # type: ignore[arg-type]
        )
