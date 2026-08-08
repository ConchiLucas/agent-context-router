from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

import psycopg

from context_router.repositories.workspace_deploy_repository import (
    InMemoryWorkspaceDeployRepository,
    WorkspaceDeployRepositoryError,
    _replace_workspace_bundle,
)
from context_router.schemas.workspace_deploy_sync import WorkspaceDeployBundle


class WorkspaceSharedFileRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WorkspaceSharedFile:
    file_type: str
    relative_path: str
    content: str
    executable: bool = False


class WorkspaceSharedFileStore(Protocol):
    def list_files(self, workspace_id: str) -> list[WorkspaceSharedFile]: ...

    def replace_all(
        self,
        workspace_id: str,
        files: list[WorkspaceSharedFile],
        deploy_bundle: WorkspaceDeployBundle,
    ) -> None: ...


class InMemoryWorkspaceSharedFileRepository:
    def __init__(self, deploy_repository: InMemoryWorkspaceDeployRepository) -> None:
        self._deploy_repository = deploy_repository
        self._files: dict[str, list[WorkspaceSharedFile]] = {}

    def list_files(self, workspace_id: str) -> list[WorkspaceSharedFile]:
        return list(self._files.get(workspace_id, ()))

    def replace_all(
        self,
        workspace_id: str,
        files: list[WorkspaceSharedFile],
        deploy_bundle: WorkspaceDeployBundle,
    ) -> None:
        self._deploy_repository.replace_workspace_bundle(workspace_id, deploy_bundle)
        self._files[workspace_id] = list(files)


class PostgresWorkspaceSharedFileRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def list_files(self, workspace_id: str) -> list[WorkspaceSharedFile]:
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """SELECT file_type, relative_path, content, executable
                       FROM workspace_shared_files
                       WHERE workspace_id = %s
                       ORDER BY file_type, relative_path""",
                    (workspace_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise WorkspaceSharedFileRepositoryError("共享文件读取失败") from exc
        return [
            WorkspaceSharedFile(
                file_type=str(row[0]),
                relative_path=str(row[1]),
                content=str(row[2]),
                executable=bool(row[3]),
            )
            for row in rows
        ]

    def replace_all(
        self,
        workspace_id: str,
        files: list[WorkspaceSharedFile],
        deploy_bundle: WorkspaceDeployBundle,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                _replace_workspace_bundle(connection, workspace_id, deploy_bundle)
                connection.execute(
                    "DELETE FROM workspace_shared_files WHERE workspace_id = %s",
                    (workspace_id,),
                )
                for item in files:
                    connection.execute(
                        """INSERT INTO workspace_shared_files
                           (id, workspace_id, file_type, relative_path, content, executable)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (
                            uuid4().hex,
                            workspace_id,
                            item.file_type,
                            item.relative_path,
                            item.content,
                            item.executable,
                        ),
                    )
        except WorkspaceDeployRepositoryError as exc:
            raise WorkspaceSharedFileRepositoryError(str(exc)) from exc
        except psycopg.Error as exc:
            raise WorkspaceSharedFileRepositoryError("共享文件数据库覆盖失败") from exc
