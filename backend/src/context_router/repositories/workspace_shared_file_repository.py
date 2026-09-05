from __future__ import annotations

import hashlib
import json
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
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.content_sha256 is None:
            object.__setattr__(
                self,
                "content_sha256",
                hashlib.sha256(self.content.encode("utf-8")).hexdigest(),
            )


@dataclass(frozen=True, slots=True)
class WorkspaceSharedFileSet:
    revision: int
    digest: str
    files: tuple[WorkspaceSharedFile, ...]


def shared_file_set_digest(
    files: list[WorkspaceSharedFile] | tuple[WorkspaceSharedFile, ...],
) -> str:
    payload = [
        {
            "content_sha256": item.content_sha256,
            "executable": item.executable,
            "file_type": item.file_type,
            "relative_path": item.relative_path,
        }
        for item in sorted(files, key=lambda item: (item.file_type, item.relative_path))
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class WorkspaceSharedFileStore(Protocol):
    def get_file_set(
        self, workspace_id: str, revision: int | None = None
    ) -> WorkspaceSharedFileSet | None: ...

    def replace_all(
        self,
        workspace_id: str,
        files: list[WorkspaceSharedFile],
        deploy_bundle: WorkspaceDeployBundle | None,
    ) -> WorkspaceSharedFileSet: ...


class InMemoryWorkspaceSharedFileRepository:
    def __init__(self, deploy_repository: InMemoryWorkspaceDeployRepository) -> None:
        self._deploy_repository = deploy_repository
        self._sets: dict[str, list[WorkspaceSharedFileSet]] = {}

    def get_file_set(
        self, workspace_id: str, revision: int | None = None
    ) -> WorkspaceSharedFileSet | None:
        sets = self._sets.get(workspace_id, ())
        if not sets:
            return None
        if revision is None:
            return sets[-1]
        return next((item for item in sets if item.revision == revision), None)

    def replace_all(
        self,
        workspace_id: str,
        files: list[WorkspaceSharedFile],
        deploy_bundle: WorkspaceDeployBundle | None,
    ) -> WorkspaceSharedFileSet:
        if deploy_bundle is not None:
            self._deploy_repository.replace_workspace_bundle(workspace_id, deploy_bundle)
        sets = self._sets.setdefault(workspace_id, [])
        revision = sets[-1].revision + 1 if sets else 1
        file_set = WorkspaceSharedFileSet(
            revision=revision,
            digest=shared_file_set_digest(files),
            files=tuple(files),
        )
        sets.append(file_set)
        del sets[:-5]
        return file_set


class PostgresWorkspaceSharedFileRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def get_file_set(
        self, workspace_id: str, revision: int | None = None
    ) -> WorkspaceSharedFileSet | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                set_row = connection.execute(
                    """SELECT revision, digest
                       FROM workspace_shared_file_sets
                       WHERE workspace_id = %s
                         AND (%s::bigint IS NULL OR revision = %s)
                         AND (%s::bigint IS NOT NULL OR is_current)
                       ORDER BY revision DESC
                       LIMIT 1""",
                    (workspace_id, revision, revision, revision),
                ).fetchone()
                if set_row is None:
                    return None
                rows = connection.execute(
                    """SELECT file_type, relative_path, content, executable, content_sha256
                       FROM workspace_shared_files
                       WHERE workspace_id = %s AND revision = %s
                       ORDER BY file_type, relative_path""",
                    (workspace_id, int(set_row[0])),
                ).fetchall()
        except psycopg.Error as exc:
            raise WorkspaceSharedFileRepositoryError("共享文件读取失败") from exc
        files = tuple(
            WorkspaceSharedFile(
                file_type=str(row[0]),
                relative_path=str(row[1]),
                content=str(row[2]),
                executable=bool(row[3]),
                content_sha256=str(row[4]) if row[4] else None,
            )
            for row in rows
        )
        digest = str(set_row[1]) if set_row[1] else shared_file_set_digest(files)
        return WorkspaceSharedFileSet(revision=int(set_row[0]), digest=digest, files=files)

    def replace_all(
        self,
        workspace_id: str,
        files: list[WorkspaceSharedFile],
        deploy_bundle: WorkspaceDeployBundle | None,
    ) -> WorkspaceSharedFileSet:
        digest = shared_file_set_digest(files)
        try:
            with psycopg.connect(self._database_url) as connection:
                locked = connection.execute(
                    "SELECT id FROM workspaces WHERE id = %s FOR UPDATE",
                    (workspace_id,),
                ).fetchone()
                if locked is None:
                    raise WorkspaceSharedFileRepositoryError("工作空间不存在")
                if deploy_bundle is not None:
                    _replace_workspace_bundle(connection, workspace_id, deploy_bundle)
                current_row = connection.execute(
                    """SELECT revision FROM workspace_shared_file_sets
                       WHERE workspace_id = %s AND is_current
                       FOR UPDATE""",
                    (workspace_id,),
                ).fetchone()
                revision = int(current_row[0]) + 1 if current_row else 1
                connection.execute(
                    """UPDATE workspace_shared_file_sets
                       SET is_current = false WHERE workspace_id = %s""",
                    (workspace_id,),
                )
                connection.execute(
                    """INSERT INTO workspace_shared_file_sets
                       (workspace_id, revision, digest, is_current)
                       VALUES (%s, %s, %s, true)""",
                    (workspace_id, revision, digest),
                )
                for item in files:
                    connection.execute(
                        """INSERT INTO workspace_shared_files
                           (id, workspace_id, revision, file_type, relative_path, content,
                            executable, content_sha256)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            uuid4().hex,
                            workspace_id,
                            revision,
                            item.file_type,
                            item.relative_path,
                            item.content,
                            item.executable,
                            item.content_sha256,
                        ),
                    )
                connection.execute(
                    """DELETE FROM workspace_shared_files
                       WHERE workspace_id = %s AND revision NOT IN (
                           SELECT revision FROM workspace_shared_file_sets
                           WHERE workspace_id = %s ORDER BY revision DESC LIMIT 5
                       )""",
                    (workspace_id, workspace_id),
                )
                connection.execute(
                    """DELETE FROM workspace_shared_file_sets
                       WHERE workspace_id = %s AND revision NOT IN (
                           SELECT revision FROM workspace_shared_file_sets
                           WHERE workspace_id = %s ORDER BY revision DESC LIMIT 5
                       )""",
                    (workspace_id, workspace_id),
                )
        except WorkspaceDeployRepositoryError as exc:
            raise WorkspaceSharedFileRepositoryError(str(exc)) from exc
        except psycopg.Error as exc:
            raise WorkspaceSharedFileRepositoryError("共享文件数据库覆盖失败") from exc
        return WorkspaceSharedFileSet(revision=revision, digest=digest, files=tuple(files))
