from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb


class WorkspaceRuntimeRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeFileDraft:
    relative_path: str
    content: str
    executable: bool


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeFileRecord(WorkspaceRuntimeFileDraft):
    id: str
    workspace_id: str
    profile: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimePolicyDraft:
    project_order: tuple[str, ...] = ()
    workspace_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimePolicyRecord(WorkspaceRuntimePolicyDraft):
    workspace_id: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkspaceRuntimeStore(Protocol):
    def list_files(self, workspace_id: str, profile: str) -> list[WorkspaceRuntimeFileRecord]: ...
    def replace_files(
        self, workspace_id: str, profile: str, files: list[WorkspaceRuntimeFileDraft]
    ) -> list[WorkspaceRuntimeFileRecord]: ...
    def get_policy(self, workspace_id: str) -> WorkspaceRuntimePolicyRecord | None: ...
    def save_policy(
        self, workspace_id: str, policy: WorkspaceRuntimePolicyDraft
    ) -> WorkspaceRuntimePolicyRecord: ...


class InMemoryWorkspaceRuntimeRepository:
    def __init__(self) -> None:
        self._files: dict[tuple[str, str], list[WorkspaceRuntimeFileRecord]] = {}
        self._policies: dict[str, WorkspaceRuntimePolicyRecord] = {}
        self._lock = RLock()

    def list_files(self, workspace_id: str, profile: str) -> list[WorkspaceRuntimeFileRecord]:
        with self._lock:
            return list(self._files.get((workspace_id, profile), ()))

    def replace_files(
        self, workspace_id: str, profile: str, files: list[WorkspaceRuntimeFileDraft]
    ) -> list[WorkspaceRuntimeFileRecord]:
        _validate_profile(profile)
        now = datetime.now(UTC)
        records = [
            WorkspaceRuntimeFileRecord(
                id=uuid4().hex,
                workspace_id=workspace_id,
                profile=profile,
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
            self._files[(workspace_id, profile)] = records
        return list(records)

    def get_policy(self, workspace_id: str) -> WorkspaceRuntimePolicyRecord | None:
        with self._lock:
            return self._policies.get(workspace_id)

    def save_policy(
        self, workspace_id: str, policy: WorkspaceRuntimePolicyDraft
    ) -> WorkspaceRuntimePolicyRecord:
        _validate_policy(policy)
        now = datetime.now(UTC)
        with self._lock:
            current = self._policies.get(workspace_id)
            record = WorkspaceRuntimePolicyRecord(
                workspace_id=workspace_id,
                project_order=tuple(policy.project_order),
                workspace_paths=tuple(policy.workspace_paths),
                created_at=current.created_at if current else now,
                updated_at=now,
            )
            self._policies[workspace_id] = record
            return record


class PostgresWorkspaceRuntimeRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def list_files(self, workspace_id: str, profile: str) -> list[WorkspaceRuntimeFileRecord]:
        _validate_profile(profile)
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """SELECT id, workspace_id, profile, relative_path, content, executable,
                              sort_order, created_at, updated_at
                       FROM workspace_runtime_files
                       WHERE workspace_id = %s AND profile = %s
                       ORDER BY sort_order, relative_path, id""",
                    (workspace_id, profile),
                ).fetchall()
            return [self._file(row) for row in rows]
        except psycopg.Error as exc:
            raise WorkspaceRuntimeRepositoryError("工作空间运行配置数据库当前不可用") from exc

    def replace_files(
        self, workspace_id: str, profile: str, files: list[WorkspaceRuntimeFileDraft]
    ) -> list[WorkspaceRuntimeFileRecord]:
        _validate_profile(profile)
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    "DELETE FROM workspace_runtime_files WHERE workspace_id = %s AND profile = %s",
                    (workspace_id, profile),
                )
                rows = []
                for index, item in enumerate(files):
                    row = connection.execute(
                        """INSERT INTO workspace_runtime_files
                           (id, workspace_id, profile, relative_path, content,
                            executable, sort_order)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)
                           RETURNING id, workspace_id, profile, relative_path, content, executable,
                                     sort_order, created_at, updated_at""",
                        (
                            uuid4().hex,
                            workspace_id,
                            profile,
                            item.relative_path,
                            item.content,
                            item.executable,
                            index,
                        ),
                    ).fetchone()
                    if row is not None:
                        rows.append(row)
            return [self._file(row) for row in rows]
        except psycopg.Error as exc:
            raise WorkspaceRuntimeRepositoryError("工作空间运行配置数据库当前不可用") from exc

    def get_policy(self, workspace_id: str) -> WorkspaceRuntimePolicyRecord | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """SELECT workspace_id, project_order, workspace_paths, created_at, updated_at
                       FROM workspace_runtime_policies WHERE workspace_id = %s""",
                    (workspace_id,),
                ).fetchone()
            return self._policy(row) if row else None
        except psycopg.Error as exc:
            raise WorkspaceRuntimeRepositoryError("工作空间运行策略数据库当前不可用") from exc

    def save_policy(
        self, workspace_id: str, policy: WorkspaceRuntimePolicyDraft
    ) -> WorkspaceRuntimePolicyRecord:
        _validate_policy(policy)
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """INSERT INTO workspace_runtime_policies
                       (workspace_id, project_order, workspace_paths)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (workspace_id) DO UPDATE SET
                         project_order = EXCLUDED.project_order,
                         workspace_paths = EXCLUDED.workspace_paths,
                         updated_at = CURRENT_TIMESTAMP
                       RETURNING workspace_id, project_order, workspace_paths,
                                 created_at, updated_at""",
                    (
                        workspace_id,
                        Jsonb(list(policy.project_order)),
                        Jsonb(list(policy.workspace_paths)),
                    ),
                ).fetchone()
            if row is None:
                raise WorkspaceRuntimeRepositoryError("工作空间运行策略保存失败")
            return self._policy(row)
        except psycopg.Error as exc:
            raise WorkspaceRuntimeRepositoryError("工作空间运行策略数据库当前不可用") from exc

    @staticmethod
    def _file(row: tuple[object, ...]) -> WorkspaceRuntimeFileRecord:
        return WorkspaceRuntimeFileRecord(
            id=str(row[0]),
            workspace_id=str(row[1]),
            profile=str(row[2]),
            relative_path=str(row[3]),
            content=str(row[4]),
            executable=bool(row[5]),
            sort_order=int(row[6]),
            created_at=row[7],
            updated_at=row[8],  # type: ignore[arg-type]
        )

    @staticmethod
    def _policy(row: tuple[object, ...]) -> WorkspaceRuntimePolicyRecord:
        return WorkspaceRuntimePolicyRecord(
            workspace_id=str(row[0]),
            project_order=tuple(row[1]),
            workspace_paths=tuple(row[2]),
            created_at=row[3],
            updated_at=row[4],  # type: ignore[arg-type]
        )


def _validate_profile(profile: str) -> None:
    if profile != "start":
        raise WorkspaceRuntimeRepositoryError("工作空间运行配置只支持 start")


def _validate_policy(policy: WorkspaceRuntimePolicyDraft) -> None:
    if len(set(policy.project_order)) != len(policy.project_order):
        raise WorkspaceRuntimeRepositoryError("项目更新顺序不能重复")
    if len(set(policy.workspace_paths)) != len(policy.workspace_paths):
        raise WorkspaceRuntimeRepositoryError("工作空间运行路径不能重复")
    if ".env.local" in policy.workspace_paths:
        raise WorkspaceRuntimeRepositoryError("工作空间策略不能登记 .env.local")
