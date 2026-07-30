from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

import psycopg

from context_router.repositories.workspace_repository import (
    DEFAULT_WORKSPACE_TYPE,
    InMemoryWorkspaceRepository,
    WorkspaceRecord,
    WorkspaceRepositoryError,
    WorkspaceStore,
    build_project_agents_path,
    derive_workspace_root_path,
)

DEFAULT_PROJECT_TYPE = DEFAULT_WORKSPACE_TYPE
DEFAULT_PROJECT_KIND = "backend"
PROJECT_KINDS = frozenset({"frontend", "backend"})


class ProjectRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    id: str
    name: str
    project_type: str
    project_kind: str
    workspace_id: str
    relative_path: str
    document_relative_path: str
    agents_path: str
    created_at: datetime
    updated_at: datetime
    workspace_name: str | None = None
    workspace_type: str | None = None
    workspace_root_path: str | None = None


class ProjectStore(Protocol):
    def list_projects(self, workspace_id: str | None = None) -> list[ProjectRecord]: ...

    def get_project(self, project_id: str) -> ProjectRecord: ...

    def create_project(
        self,
        *,
        project_id: str,
        name: str,
        project_type: str = DEFAULT_PROJECT_TYPE,
        project_kind: str = DEFAULT_PROJECT_KIND,
        agents_path: str | None = None,
        workspace_id: str | None = None,
        relative_path: str | None = None,
        document_relative_path: str | None = None,
    ) -> None: ...

    def update_project(
        self,
        project_id: str,
        *,
        name: str,
        project_type: str | None = None,
        project_kind: str | None = None,
        agents_path: str | None = None,
        workspace_id: str | None = None,
        relative_path: str | None = None,
        document_relative_path: str | None = None,
    ) -> None: ...

    def delete_project(self, project_id: str) -> None: ...


def _resolved_relative_path(relative_path: str | None) -> str:
    resolved = "." if relative_path is None else relative_path.strip()
    if not resolved:
        raise ProjectRepositoryError("项目相对路径不能为空")
    return resolved


def _resolved_project_kind(project_kind: str | None) -> str:
    resolved = DEFAULT_PROJECT_KIND if project_kind is None else project_kind.strip()
    if resolved not in PROJECT_KINDS:
        raise ProjectRepositoryError("项目类型必须是 frontend 或 backend")
    return resolved


def _legacy_document_relative_path(relative_path: str) -> str:
    if relative_path == ".":
        return "AGENTS.md"
    return f"{relative_path.rstrip('/')}/AGENTS.md"


def _resolved_document_relative_path(
    document_relative_path: str | None,
    *,
    relative_path: str,
) -> str:
    resolved = (
        _legacy_document_relative_path(relative_path)
        if document_relative_path is None
        else document_relative_path.strip()
    )
    if not resolved:
        raise ProjectRepositoryError("项目文档入口相对路径不能为空")
    return resolved


class InMemoryProjectRepository:
    def __init__(
        self,
        workspace_repository: WorkspaceStore | None = None,
    ) -> None:
        self._workspace_repository = workspace_repository or InMemoryWorkspaceRepository()
        if isinstance(self._workspace_repository, InMemoryWorkspaceRepository):
            self._projects: dict[str, ProjectRecord] = self._workspace_repository.state.projects
        else:
            self._projects = {}

    @property
    def workspace_repository(self) -> WorkspaceStore:
        return self._workspace_repository

    def list_projects(self, workspace_id: str | None = None) -> list[ProjectRecord]:
        return [
            self._hydrate(record)
            for record in self._projects.values()
            if workspace_id is None or record.workspace_id == workspace_id
        ]

    def get_project(self, project_id: str) -> ProjectRecord:
        return self._hydrate(self._get(project_id))

    def create_project(
        self,
        *,
        project_id: str,
        name: str,
        project_type: str = DEFAULT_PROJECT_TYPE,
        project_kind: str = DEFAULT_PROJECT_KIND,
        agents_path: str | None = None,
        workspace_id: str | None = None,
        relative_path: str | None = None,
        document_relative_path: str | None = None,
    ) -> None:
        if project_id in self._projects:
            raise ProjectRepositoryError("项目已存在")
        workspace, resolved_relative_path = self._resolve_create_workspace(
            project_id=project_id,
            name=name,
            project_type=project_type,
            agents_path=agents_path,
            workspace_id=workspace_id,
            relative_path=relative_path,
        )
        resolved_document_relative_path = _resolved_document_relative_path(
            document_relative_path,
            relative_path=resolved_relative_path,
        )
        resolved_agents_path = build_project_agents_path(
            workspace.root_path,
            resolved_document_relative_path,
        )
        self._ensure_unique_location(
            workspace_id=workspace.id,
            relative_path=resolved_relative_path,
            document_relative_path=resolved_document_relative_path,
            agents_path=resolved_agents_path,
        )
        now = datetime.now(UTC)
        self._projects[project_id] = ProjectRecord(
            id=project_id,
            name=name,
            project_type=workspace.workspace_type,
            project_kind=_resolved_project_kind(project_kind),
            workspace_id=workspace.id,
            relative_path=resolved_relative_path,
            document_relative_path=resolved_document_relative_path,
            agents_path=resolved_agents_path,
            created_at=now,
            updated_at=now,
            workspace_name=workspace.name,
            workspace_type=workspace.workspace_type,
            workspace_root_path=workspace.root_path,
        )

    def update_project(
        self,
        project_id: str,
        *,
        name: str,
        project_type: str | None = None,
        project_kind: str | None = None,
        agents_path: str | None = None,
        workspace_id: str | None = None,
        relative_path: str | None = None,
        document_relative_path: str | None = None,
    ) -> None:
        record = self._get(project_id)
        legacy_update = workspace_id is None and relative_path is None and agents_path is not None
        if legacy_update:
            if record.relative_path != ".":
                raise ProjectRepositoryError("工作空间子项目请使用工作空间项目接口更新")
            if (
                sum(item.workspace_id == record.workspace_id for item in self._projects.values())
                > 1
            ):
                raise ProjectRepositoryError("包含多个项目的工作空间请使用工作空间接口更新")
            if record.document_relative_path != "AGENTS.md":
                raise ProjectRepositoryError("工作空间项目请使用工作空间项目接口更新")
            try:
                current_workspace = self._workspace_repository.get_workspace(record.workspace_id)
                self._workspace_repository.update_workspace(
                    record.workspace_id,
                    name=name,
                    workspace_type=project_type or current_workspace.workspace_type,
                    root_path=derive_workspace_root_path(agents_path),
                )
            except WorkspaceRepositoryError as exc:
                raise ProjectRepositoryError(str(exc)) from exc
            record = self._get(project_id)

        target_workspace_id = workspace_id or record.workspace_id
        workspace = self._get_workspace(target_workspace_id)
        target_relative_path = (
            _resolved_relative_path(relative_path)
            if relative_path is not None
            else record.relative_path
        )
        target_document_relative_path = (
            _resolved_document_relative_path(
                document_relative_path,
                relative_path=target_relative_path,
            )
            if document_relative_path is not None
            else record.document_relative_path
        )
        resolved_agents_path = build_project_agents_path(
            workspace.root_path,
            target_document_relative_path,
        )
        self._ensure_unique_location(
            workspace_id=target_workspace_id,
            relative_path=target_relative_path,
            document_relative_path=target_document_relative_path,
            agents_path=resolved_agents_path,
            exclude_project_id=project_id,
        )
        self._projects[project_id] = replace(
            record,
            name=name,
            project_type=workspace.workspace_type,
            project_kind=_resolved_project_kind(project_kind or record.project_kind),
            workspace_id=target_workspace_id,
            relative_path=target_relative_path,
            document_relative_path=target_document_relative_path,
            agents_path=resolved_agents_path,
            updated_at=datetime.now(UTC),
            workspace_name=workspace.name,
            workspace_type=workspace.workspace_type,
            workspace_root_path=workspace.root_path,
        )

    def delete_project(self, project_id: str) -> None:
        self._get(project_id)
        del self._projects[project_id]

    def _resolve_create_workspace(
        self,
        *,
        project_id: str,
        name: str,
        project_type: str,
        agents_path: str | None,
        workspace_id: str | None,
        relative_path: str | None,
    ) -> tuple[WorkspaceRecord, str]:
        if workspace_id is not None:
            return self._get_workspace(workspace_id), _resolved_relative_path(relative_path)
        if agents_path is None:
            raise ProjectRepositoryError("工作空间或 AGENTS.md 路径不能为空")
        try:
            workspace = self._workspace_repository.get_workspace(project_id)
        except WorkspaceRepositoryError:
            try:
                self._workspace_repository.create_workspace(
                    workspace_id=project_id,
                    name=name,
                    workspace_type=project_type,
                    root_path=derive_workspace_root_path(agents_path),
                )
                workspace = self._workspace_repository.get_workspace(project_id)
            except WorkspaceRepositoryError as exc:
                raise ProjectRepositoryError(str(exc)) from exc
        return workspace, "."

    def _get_workspace(self, workspace_id: str) -> WorkspaceRecord:
        try:
            return self._workspace_repository.get_workspace(workspace_id)
        except WorkspaceRepositoryError as exc:
            raise ProjectRepositoryError(str(exc)) from exc

    def _hydrate(self, record: ProjectRecord) -> ProjectRecord:
        workspace = self._get_workspace(record.workspace_id)
        return replace(
            record,
            project_type=workspace.workspace_type,
            agents_path=build_project_agents_path(
                workspace.root_path,
                record.document_relative_path,
            ),
            workspace_name=workspace.name,
            workspace_type=workspace.workspace_type,
            workspace_root_path=workspace.root_path,
        )

    def _ensure_unique_location(
        self,
        *,
        workspace_id: str,
        relative_path: str,
        document_relative_path: str,
        agents_path: str,
        exclude_project_id: str | None = None,
    ) -> None:
        if any(
            record.id != exclude_project_id
            and (
                (record.workspace_id == workspace_id and record.relative_path == relative_path)
                or (
                    record.workspace_id == workspace_id
                    and record.document_relative_path == document_relative_path
                )
                or record.agents_path == agents_path
            )
            for record in self._projects.values()
        ):
            raise ProjectRepositoryError("这个 AGENTS.md 已经添加")

    def _get(self, project_id: str) -> ProjectRecord:
        record = self._projects.get(project_id)
        if record is None:
            raise ProjectRepositoryError("项目不存在")
        return record


class PostgresProjectRepository:
    _SELECT_FIELDS = """
        p.id, p.name, p.project_type, p.project_kind, p.workspace_id,
        p.relative_path, p.document_relative_path, p.agents_path,
        p.created_at, p.updated_at,
        w.name, w.workspace_type, w.root_path
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.strip()

    def list_projects(self, workspace_id: str | None = None) -> list[ProjectRecord]:
        where_clause = "" if workspace_id is None else "WHERE p.workspace_id = %s"
        parameters: tuple[str, ...] = () if workspace_id is None else (workspace_id,)
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    f"""
                    SELECT {self._SELECT_FIELDS}
                    FROM document_projects AS p
                    JOIN workspaces AS w ON w.id = p.workspace_id
                    {where_clause}
                    ORDER BY p.created_at, p.id
                    """,  # noqa: S608 - where_clause is a fixed internal fragment
                    parameters,
                ).fetchall()
        except psycopg.Error as exc:
            raise ProjectRepositoryError("项目配置读取失败") from exc
        return [self._record(row) for row in rows]

    def get_project(self, project_id: str) -> ProjectRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = self._fetch_project(connection, project_id)
        except psycopg.Error as exc:
            raise ProjectRepositoryError("项目配置读取失败") from exc
        if row is None:
            raise ProjectRepositoryError("项目不存在")
        return self._record(row)

    def create_project(
        self,
        *,
        project_id: str,
        name: str,
        project_type: str = DEFAULT_PROJECT_TYPE,
        project_kind: str = DEFAULT_PROJECT_KIND,
        agents_path: str | None = None,
        workspace_id: str | None = None,
        relative_path: str | None = None,
        document_relative_path: str | None = None,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                resolved_workspace_id = workspace_id
                if resolved_workspace_id is None:
                    if agents_path is None:
                        raise ProjectRepositoryError("工作空间或 AGENTS.md 路径不能为空")
                    resolved_workspace_id = project_id
                    workspace = self._fetch_workspace(connection, resolved_workspace_id)
                    if workspace is None:
                        connection.execute(
                            """
                            INSERT INTO workspaces
                                (id, name, workspace_type, root_path)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (
                                resolved_workspace_id,
                                name,
                                project_type,
                                derive_workspace_root_path(agents_path),
                            ),
                        )
                        workspace = self._fetch_workspace(connection, resolved_workspace_id)
                    resolved_relative_path = "."
                else:
                    workspace = self._fetch_workspace(connection, resolved_workspace_id)
                    resolved_relative_path = _resolved_relative_path(relative_path)
                if workspace is None:
                    raise ProjectRepositoryError("工作空间不存在")
                workspace_type = str(workspace[2])
                root_path = str(workspace[3])
                resolved_document_relative_path = _resolved_document_relative_path(
                    document_relative_path,
                    relative_path=resolved_relative_path,
                )
                resolved_agents_path = build_project_agents_path(
                    root_path,
                    resolved_document_relative_path,
                )
                connection.execute(
                    """
                    INSERT INTO document_projects
                        (
                            id, name, project_type, project_kind, workspace_id,
                            relative_path, document_relative_path, agents_path
                        )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        project_id,
                        name,
                        workspace_type,
                        _resolved_project_kind(project_kind),
                        resolved_workspace_id,
                        resolved_relative_path,
                        resolved_document_relative_path,
                        resolved_agents_path,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name == "uq_project_databases_workspace_mcp_alias":
                raise ProjectRepositoryError("目标工作空间存在相同的 MCP 数据库别名") from exc
            raise ProjectRepositoryError("这个 AGENTS.md 已经添加") from exc
        except ProjectRepositoryError:
            raise
        except psycopg.Error as exc:
            raise ProjectRepositoryError("项目配置写入失败") from exc

    def update_project(
        self,
        project_id: str,
        *,
        name: str,
        project_type: str | None = None,
        project_kind: str | None = None,
        agents_path: str | None = None,
        workspace_id: str | None = None,
        relative_path: str | None = None,
        document_relative_path: str | None = None,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                project_row = self._fetch_project(connection, project_id)
                if project_row is None:
                    raise ProjectRepositoryError("项目不存在")
                current_project_kind = str(project_row[3])
                current_workspace_id = str(project_row[4])
                current_relative_path = str(project_row[5])
                current_document_relative_path = str(project_row[6])
                legacy_update = (
                    workspace_id is None and relative_path is None and agents_path is not None
                )
                if legacy_update:
                    if current_relative_path != ".":
                        raise ProjectRepositoryError("工作空间子项目请使用工作空间项目接口更新")
                    project_count = connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM document_projects
                        WHERE workspace_id = %s
                        """,
                        (current_workspace_id,),
                    ).fetchone()
                    if project_count is None or int(project_count[0]) != 1:
                        raise ProjectRepositoryError("包含多个项目的工作空间请使用工作空间接口更新")
                    if current_document_relative_path != "AGENTS.md":
                        raise ProjectRepositoryError("工作空间项目请使用工作空间项目接口更新")
                    current_workspace = self._fetch_workspace(
                        connection,
                        current_workspace_id,
                    )
                    if current_workspace is None:
                        raise ProjectRepositoryError("工作空间不存在")
                    resolved_workspace_type = project_type or str(current_workspace[2])
                    resolved_root_path = derive_workspace_root_path(agents_path)
                    self._update_workspace_and_legacy_fields(
                        connection,
                        workspace_id=current_workspace_id,
                        name=name,
                        workspace_type=resolved_workspace_type,
                        root_path=resolved_root_path,
                    )

                target_workspace_id = workspace_id or current_workspace_id
                target_workspace = self._fetch_workspace(connection, target_workspace_id)
                if target_workspace is None:
                    raise ProjectRepositoryError("工作空间不存在")
                target_relative_path = (
                    _resolved_relative_path(relative_path)
                    if relative_path is not None
                    else current_relative_path
                )
                resolved_workspace_type = str(target_workspace[2])
                target_document_relative_path = (
                    _resolved_document_relative_path(
                        document_relative_path,
                        relative_path=target_relative_path,
                    )
                    if document_relative_path is not None
                    else current_document_relative_path
                )
                resolved_agents_path = build_project_agents_path(
                    str(target_workspace[3]),
                    target_document_relative_path,
                )
                connection.execute(
                    """
                    UPDATE document_projects
                    SET name = %s, project_type = %s, project_kind = %s,
                        workspace_id = %s, relative_path = %s,
                        document_relative_path = %s, agents_path = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        name,
                        resolved_workspace_type,
                        _resolved_project_kind(project_kind or current_project_kind),
                        target_workspace_id,
                        target_relative_path,
                        target_document_relative_path,
                        resolved_agents_path,
                        project_id,
                    ),
                )
                if target_workspace_id != current_workspace_id:
                    connection.execute(
                        """
                        UPDATE project_databases
                        SET workspace_id = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE project_id = %s
                        """,
                        (target_workspace_id, project_id),
                    )
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name == "uq_project_databases_workspace_mcp_alias":
                raise ProjectRepositoryError("目标工作空间存在相同的 MCP 数据库别名") from exc
            raise ProjectRepositoryError("这个 AGENTS.md 已经添加") from exc
        except ProjectRepositoryError:
            raise
        except psycopg.Error as exc:
            raise ProjectRepositoryError("项目配置更新失败") from exc

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

    def _fetch_project(
        self,
        connection: psycopg.Connection[tuple[object, ...]],
        project_id: str,
    ) -> tuple[object, ...] | None:
        return connection.execute(
            f"""
            SELECT {self._SELECT_FIELDS}
            FROM document_projects AS p
            JOIN workspaces AS w ON w.id = p.workspace_id
            WHERE p.id = %s
            """,  # noqa: S608 - SELECT_FIELDS is a fixed internal projection
            (project_id,),
        ).fetchone()

    @staticmethod
    def _fetch_workspace(
        connection: psycopg.Connection[tuple[object, ...]],
        workspace_id: str,
    ) -> tuple[object, ...] | None:
        return connection.execute(
            """
            SELECT id, name, workspace_type, root_path, created_at, updated_at
            FROM workspaces
            WHERE id = %s
            """,
            (workspace_id,),
        ).fetchone()

    @staticmethod
    def _update_workspace_and_legacy_fields(
        connection: psycopg.Connection[tuple[object, ...]],
        *,
        workspace_id: str,
        name: str,
        workspace_type: str,
        root_path: str,
    ) -> None:
        connection.execute(
            """
            UPDATE workspaces
            SET name = %s, workspace_type = %s, root_path = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (name, workspace_type, root_path, workspace_id),
        )
        projects = connection.execute(
            """
            SELECT id, document_relative_path
            FROM document_projects
            WHERE workspace_id = %s
            """,
            (workspace_id,),
        ).fetchall()
        for child_project_id, child_document_relative_path in projects:
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
                        str(child_document_relative_path),
                    ),
                    child_project_id,
                ),
            )

    @staticmethod
    def _record(row: tuple[object, ...]) -> ProjectRecord:
        return ProjectRecord(
            id=str(row[0]),
            name=str(row[1]),
            project_type=str(row[2]),
            project_kind=str(row[3]),
            workspace_id=str(row[4]),
            relative_path=str(row[5]),
            document_relative_path=str(row[6]),
            agents_path=str(row[7]),
            created_at=row[8],  # type: ignore[arg-type]
            updated_at=row[9],  # type: ignore[arg-type]
            workspace_name=str(row[10]),
            workspace_type=str(row[11]),
            workspace_root_path=str(row[12]),
        )
