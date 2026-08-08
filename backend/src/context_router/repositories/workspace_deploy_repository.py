from __future__ import annotations

from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from context_router.repositories.runtime_config_repository import (
    RuntimeConfigFileDraft,
    RuntimeConfigStore,
)
from context_router.repositories.workspace_runtime_repository import (
    WorkspaceRuntimeFileDraft,
    WorkspaceRuntimePolicyDraft,
    WorkspaceRuntimeStore,
)
from context_router.schemas.workspace_deploy_sync import (
    RuntimeProfileBundle,
    WorkspaceDeployBundle,
)


class WorkspaceDeployRepositoryError(RuntimeError):
    pass


class WorkspaceDeployStore(Protocol):
    def replace_workspace_bundle(
        self,
        workspace_id: str,
        bundle: WorkspaceDeployBundle,
    ) -> None: ...


class InMemoryWorkspaceDeployRepository:
    def __init__(
        self,
        *,
        workspace_runtime: WorkspaceRuntimeStore,
        project_runtime: RuntimeConfigStore,
    ) -> None:
        self._workspace_runtime = workspace_runtime
        self._project_runtime = project_runtime

    def replace_workspace_bundle(
        self,
        workspace_id: str,
        bundle: WorkspaceDeployBundle,
    ) -> None:
        _validate_bundle(bundle)
        self._workspace_runtime.replace_files(
            workspace_id,
            "start",
            _workspace_drafts(bundle.start),
        )
        self._workspace_runtime.save_policy(
            workspace_id,
            WorkspaceRuntimePolicyDraft(
                project_order=bundle.project_order,
                workspace_paths=bundle.workspace_paths,
            ),
        )
        for project in bundle.projects:
            self._project_runtime.replace_files(
                project.project_id,
                "fast",
                _project_drafts(project.fast),
            )
            self._project_runtime.replace_files(
                project.project_id,
                "full",
                _project_drafts(project.full),
            )


class PostgresWorkspaceDeployRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def replace_workspace_bundle(
        self,
        workspace_id: str,
        bundle: WorkspaceDeployBundle,
    ) -> None:
        _validate_bundle(bundle)
        try:
            with psycopg.connect(self._database_url) as connection:
                _replace_workspace_bundle(connection, workspace_id, bundle)
        except WorkspaceDeployRepositoryError:
            raise
        except psycopg.Error as exc:
            raise WorkspaceDeployRepositoryError("Workspace deploy 配置数据库同步失败") from exc


def _replace_workspace_bundle(
    connection: psycopg.Connection,
    workspace_id: str,
    bundle: WorkspaceDeployBundle,
) -> None:
    project_rows = connection.execute(
        "SELECT id FROM document_projects WHERE workspace_id = %s ORDER BY id",
        (workspace_id,),
    ).fetchall()
    registered_ids = {str(row[0]) for row in project_rows}
    if registered_ids != set(bundle.project_order):
        raise WorkspaceDeployRepositoryError("同步期间 Workspace 项目集合发生变化")

    connection.execute(
        "DELETE FROM workspace_runtime_files WHERE workspace_id = %s AND profile = %s",
        (workspace_id, "start"),
    )
    for index, item in enumerate(bundle.start.files):
        connection.execute(
            """INSERT INTO workspace_runtime_files
                           (id, workspace_id, profile, relative_path, content,
                            executable, sort_order)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                uuid4().hex,
                workspace_id,
                "start",
                item.relative_path,
                item.content,
                item.executable,
                index,
            ),
        )
    connection.execute(
        """INSERT INTO workspace_runtime_policies
                       (workspace_id, project_order, workspace_paths)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (workspace_id) DO UPDATE SET
                         project_order = EXCLUDED.project_order,
                         workspace_paths = EXCLUDED.workspace_paths,
                         updated_at = CURRENT_TIMESTAMP""",
        (
            workspace_id,
            Jsonb(list(bundle.project_order)),
            Jsonb(list(bundle.workspace_paths)),
        ),
    )

    connection.execute(
        "DELETE FROM project_runtime_files WHERE project_id = ANY(%s)",
        (list(registered_ids),),
    )
    for project in bundle.projects:
        for mode, profile in (("fast", project.fast), ("full", project.full)):
            for index, item in enumerate(profile.files):
                connection.execute(
                    """INSERT INTO project_runtime_files
                                   (id, project_id, mode, relative_path, content,
                                    executable, sort_order)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        uuid4().hex,
                        project.project_id,
                        mode,
                        item.relative_path,
                        item.content,
                        item.executable,
                        index,
                    ),
                )


def _validate_bundle(bundle: WorkspaceDeployBundle) -> None:
    project_ids = tuple(item.project_id for item in bundle.projects)
    if project_ids != bundle.project_order:
        raise WorkspaceDeployRepositoryError("项目顺序与项目配置不一致")
    _validate_profile("start", bundle.start)
    for project in bundle.projects:
        _validate_profile(f"{project.relative_path}/fast", project.fast)
        _validate_profile(f"{project.relative_path}/full", project.full)


def _validate_profile(label: str, profile: RuntimeProfileBundle) -> None:
    paths = [item.relative_path for item in profile.files]
    if len(paths) != len(set(paths)):
        raise WorkspaceDeployRepositoryError(f"{label} 配置包含重复文件路径")
    entry = next((item for item in profile.files if item.relative_path == "deploy.sh"), None)
    if entry is None or not entry.executable:
        raise WorkspaceDeployRepositoryError(f"{label} 配置缺少可执行的 deploy.sh")


def _workspace_drafts(profile: RuntimeProfileBundle) -> list[WorkspaceRuntimeFileDraft]:
    return [
        WorkspaceRuntimeFileDraft(item.relative_path, item.content, item.executable)
        for item in profile.files
    ]


def _project_drafts(profile: RuntimeProfileBundle) -> list[RuntimeConfigFileDraft]:
    return [
        RuntimeConfigFileDraft(item.relative_path, item.content, item.executable)
        for item in profile.files
    ]
