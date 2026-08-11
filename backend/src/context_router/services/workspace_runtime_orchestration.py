from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from context_router.repositories.runtime_config_repository import (
    RuntimeConfigRepositoryError,
    RuntimeConfigStore,
)
from context_router.repositories.runtime_operation_repository import (
    RuntimeOperationDraft,
    RuntimeOperationRecord,
    RuntimeOperationRepositoryError,
    RuntimeOperationStepDraft,
    RuntimeOperationStepRecord,
    RuntimeOperationStore,
)
from context_router.repositories.task_repository import TaskRepositoryError, TaskStore
from context_router.repositories.workspace_runtime_repository import (
    WorkspaceRuntimeRepositoryError,
    WorkspaceRuntimeStore,
)
from context_router.schemas.workspace_runtime import (
    RuntimeOperationStepView,
    RuntimeOperationView,
)
from context_router.services.local_workspace_mapping import (
    LocalWorkspaceMappingError,
    LocalWorkspaceMappingService,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError
from context_router.services.runtime_materialization import (
    MaterializedRuntimeConfig,
    RuntimeMaterializationError,
    RuntimeMaterializationService,
)

FULL_BUILD_FILE_NAMES = {
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "go.mod",
    "go.sum",
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "requirements.txt",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}


class WorkspaceRuntimeOrchestrationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class WorkspaceRuntimeOrchestrationService:
    def __init__(
        self,
        *,
        task_repository: TaskStore,
        registry: ProjectRegistry,
        project_config_repository: RuntimeConfigStore,
        workspace_runtime_repository: WorkspaceRuntimeStore,
        operation_repository: RuntimeOperationStore,
        materialization_service: RuntimeMaterializationService,
        runner_available: Callable[[], bool] | None = None,
        local_mapping: LocalWorkspaceMappingService | None = None,
    ) -> None:
        self._task_repository = task_repository
        self._registry = registry
        self._project_configs = project_config_repository
        self._workspace_runtime = workspace_runtime_repository
        self._operations = operation_repository
        self._materialization = materialization_service
        self._runner_available = runner_available
        self._local_mapping = local_mapping

    def apply_changes(
        self,
        *,
        task_id: int,
        changed_files: list[str],
        trigger: str = "mcp",
    ) -> RuntimeOperationView:
        workspace = self._workspace_for_task(task_id)
        normalized = self._normalize_changed_files(changed_files, workspace.resolved_root_path)
        policy = self._workspace_runtime.get_policy(workspace.id)
        workspace_paths = policy.workspace_paths if policy else ()
        if any(self._is_workspace_path(item, workspace_paths) for item in normalized):
            snapshot = self._materialize_workspace(workspace.id)
            step = self._step_draft(
                snapshot,
                changed_files=tuple(normalized),
                decision_reason="工作空间级运行文件发生变化，执行全量启动",
            )
            return self._create_view(
                RuntimeOperationDraft(
                    task_id=task_id,
                    workspace_id=workspace.id,
                    kind="apply_changes",
                    trigger=trigger,
                    changed_files=tuple(normalized),
                    steps=(step,),
                )
            )

        routed: dict[str, list[str]] = defaultdict(list)
        project_by_id = {item.id: item for item in workspace.projects}
        candidates = sorted(
            workspace.projects,
            key=lambda item: (
                item.relative_path == ".",
                -len(PurePosixPath(item.relative_path).parts),
            ),
        )
        for changed_file in normalized:
            owner = next(
                (
                    item
                    for item in candidates
                    if item.relative_path == "."
                    or changed_file == item.relative_path
                    or changed_file.startswith(f"{item.relative_path.rstrip('/')}/")
                ),
                None,
            )
            if owner is None:
                raise WorkspaceRuntimeOrchestrationError(
                    "unmapped_changed_file",
                    f"变更文件没有归属已注册项目：{changed_file}",
                )
            routed[owner.id].append(changed_file)

        ordered_ids = self._ordered_project_ids(
            routed,
            project_by_id,
            policy.project_order if policy else (),
        )
        steps: list[RuntimeOperationStepDraft] = []
        for project_id in ordered_ids:
            project_files = routed[project_id]
            mode, reason = select_runtime_mode(project_files)
            try:
                files = self._project_configs.list_files(project_id, mode)
            except RuntimeConfigRepositoryError as exc:
                raise WorkspaceRuntimeOrchestrationError(
                    "runtime_config_unavailable", str(exc)
                ) from exc
            self._require_entry(files, mode)
            try:
                snapshot = self._materialization.materialize(project_id, mode, files)
            except RuntimeMaterializationError as exc:
                raise WorkspaceRuntimeOrchestrationError(
                    "materialization_failed", str(exc)
                ) from exc
            steps.append(
                self._step_draft(
                    snapshot,
                    changed_files=tuple(project_files),
                    decision_reason=reason,
                )
            )
        return self._create_view(
            RuntimeOperationDraft(
                task_id=task_id,
                workspace_id=workspace.id,
                kind="apply_changes",
                trigger=trigger,
                changed_files=tuple(normalized),
                steps=tuple(steps),
            )
        )

    def start_workspace(
        self,
        *,
        task_id: int,
        trigger: str = "mcp",
    ) -> RuntimeOperationView:
        workspace = self._workspace_for_task(task_id)
        snapshot = self._materialize_workspace(workspace.id)
        return self._create_view(
            RuntimeOperationDraft(
                task_id=task_id,
                workspace_id=workspace.id,
                kind="start_workspace",
                trigger=trigger,
                changed_files=(),
                steps=(
                    self._step_draft(
                        snapshot,
                        changed_files=(),
                        decision_reason="用户要求启动当前工作空间全部项目",
                    ),
                ),
            )
        )

    def update_project(
        self,
        *,
        project_id: str,
        mode: str,
        trigger: str = "ui",
    ) -> RuntimeOperationView:
        if mode not in {"fast", "full"}:
            raise WorkspaceRuntimeOrchestrationError("invalid_runtime_mode", "不支持的更新模式")
        try:
            project = self._registry.get_project_summary(project_id)
        except ProjectRegistryError as exc:
            raise WorkspaceRuntimeOrchestrationError("project_not_found", "项目不存在") from exc
        if project.workspace_id is None:
            raise WorkspaceRuntimeOrchestrationError(
                "project_workspace_missing", "项目没有关联工作空间"
            )
        try:
            workspace = self._registry.get_workspace_snapshot(project.workspace_id)
        except ProjectRegistryError as exc:
            raise WorkspaceRuntimeOrchestrationError(
                "workspace_not_found", "项目所属工作空间不可用"
            ) from exc
        if workspace.access_mode != "full":
            raise WorkspaceRuntimeOrchestrationError(
                "documents_only", "文档只读映射不能执行项目更新"
            )

        self._require_runner_available()
        try:
            files = self._project_configs.list_files(project_id, mode)
        except RuntimeConfigRepositoryError as exc:
            raise WorkspaceRuntimeOrchestrationError(
                "runtime_config_unavailable", str(exc)
            ) from exc
        self._require_entry(files, mode)
        try:
            snapshot = self._materialization.materialize(project_id, mode, files)
        except RuntimeMaterializationError as exc:
            raise WorkspaceRuntimeOrchestrationError("materialization_failed", str(exc)) from exc

        return self._create_view(
            RuntimeOperationDraft(
                task_id=None,
                workspace_id=project.workspace_id,
                kind="project_update",
                trigger=trigger,
                changed_files=(),
                steps=(
                    self._step_draft(
                        snapshot,
                        changed_files=(),
                        decision_reason=(
                            f"用户在容器管理界面选择 {'Fast' if mode == 'fast' else 'Full'} 更新"
                        ),
                    ),
                ),
            )
        )

    def get_operation(
        self, operation_id: str, log_characters: int = 10_000
    ) -> RuntimeOperationView:
        operation = self._operations.get_operation(operation_id)
        if operation is None:
            raise WorkspaceRuntimeOrchestrationError(
                "runtime_operation_not_found", "运行操作不存在"
            )
        return self._view(operation, log_characters=log_characters)

    def get_task_id(self, operation_id: str) -> int:
        operation = self._operations.get_operation(operation_id)
        if operation is None:
            raise WorkspaceRuntimeOrchestrationError(
                "runtime_operation_not_found", "运行操作不存在"
            )
        if operation.task_id is None:
            raise WorkspaceRuntimeOrchestrationError(
                "runtime_operation_not_bound_to_task", "运行操作不属于 MCP 任务"
            )
        return operation.task_id

    def apply_project_compat(
        self,
        *,
        task_id: int,
        project_id: str,
        changed_files: list[str],
    ) -> RuntimeOperationView:
        workspace = self._workspace_for_task(task_id)
        project = next((item for item in workspace.projects if item.id == project_id), None)
        if project is None:
            raise WorkspaceRuntimeOrchestrationError(
                "project_not_in_workspace", "项目不属于当前任务工作空间"
            )
        prefix = "" if project.relative_path == "." else f"{project.relative_path.rstrip('/')}/"
        return self.apply_changes(
            task_id=task_id,
            changed_files=[f"{prefix}{item}" for item in changed_files],
        )

    def _workspace_for_task(self, task_id: int) -> object:
        try:
            task = self._task_repository.get_task(task_id)
            if task.scope != "workspace":
                raise WorkspaceRuntimeOrchestrationError(
                    "workspace_task_required", "运行操作需要 Workspace task"
                )
            if self._local_mapping is not None and task.workspace_id is not None:
                try:
                    self._local_mapping.require_full_access(
                        cwd=task.cwd,
                        workspace_id=task.workspace_id,
                    )
                except LocalWorkspaceMappingError as exc:
                    raise WorkspaceRuntimeOrchestrationError("documents_only", str(exc)) from exc
            return self._registry.get_workspace_snapshot_for_task(
                workspace_id=task.workspace_id,
                workspace_key=task.workspace_key,
            )
        except (TaskRepositoryError, ProjectRegistryError) as exc:
            raise WorkspaceRuntimeOrchestrationError("invalid_task", str(exc)) from exc

    def _materialize_workspace(self, workspace_id: str) -> MaterializedRuntimeConfig:
        try:
            files = self._workspace_runtime.list_files(workspace_id, "start")
        except WorkspaceRuntimeRepositoryError as exc:
            raise WorkspaceRuntimeOrchestrationError(
                "runtime_config_unavailable", str(exc)
            ) from exc
        self._require_entry(files, "start")
        try:
            return self._materialization.materialize_workspace(workspace_id, files)
        except RuntimeMaterializationError as exc:
            raise WorkspaceRuntimeOrchestrationError("materialization_failed", str(exc)) from exc

    def _create_view(self, draft: RuntimeOperationDraft) -> RuntimeOperationView:
        self._require_runner_available()
        try:
            operation = self._operations.create_operation(draft)
        except RuntimeOperationRepositoryError as exc:
            raise WorkspaceRuntimeOrchestrationError(
                "runtime_operation_conflict", str(exc)
            ) from exc
        return self._view(operation)

    def _require_runner_available(self) -> None:
        if self._runner_available is not None and not self._runner_available():
            raise WorkspaceRuntimeOrchestrationError(
                "host_runner_unavailable", "宿主机 Runtime Runner 当前不可用"
            )

    def _view(
        self,
        operation: RuntimeOperationRecord,
        *,
        log_characters: int = 10_000,
    ) -> RuntimeOperationView:
        bounded = min(max(log_characters, 1), 50_000)
        steps = [
            self._step_view(item, bounded) for item in self._operations.list_steps(operation.id)
        ]
        return RuntimeOperationView(
            id=operation.id,
            task_id=operation.task_id,
            workspace_id=operation.workspace_id,
            kind=operation.kind,  # type: ignore[arg-type]
            trigger=operation.trigger,  # type: ignore[arg-type]
            status=operation.status,  # type: ignore[arg-type]
            changed_files=list(operation.changed_files),
            current_step=operation.current_step,
            runner_id=operation.runner_id,
            error_code=operation.error_code,
            error_message=operation.error_message,
            created_at=operation.created_at,
            started_at=operation.started_at,
            finished_at=operation.finished_at,
            steps=steps,
        )

    def _step_view(
        self, step: RuntimeOperationStepRecord, log_characters: int
    ) -> RuntimeOperationStepView:
        content, truncated = self._read_log(step.log_relative_path, log_characters)
        return RuntimeOperationStepView(
            id=step.id,
            sequence=step.sequence,
            owner_type=step.owner_type,  # type: ignore[arg-type]
            owner_id=step.owner_id,
            mode=step.mode,  # type: ignore[arg-type]
            status=step.status,  # type: ignore[arg-type]
            changed_files=list(step.changed_files),
            decision_reason=step.decision_reason,
            exit_code=step.exit_code,
            error_code=step.error_code,
            error_message=step.error_message,
            started_at=step.started_at,
            finished_at=step.finished_at,
            log=content,
            log_truncated=truncated,
        )

    def _read_log(self, relative_path: str, max_characters: int) -> tuple[str, bool]:
        try:
            log_path = self._materialization.runtime_root.joinpath(
                *PurePosixPath(relative_path).parts
            )
            log_path.resolve(strict=False).relative_to(self._materialization.runtime_root)
            if not log_path.is_file() or log_path.is_symlink():
                return "", False
            max_bytes = max_characters * 4
            with log_path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                truncated = size > max_bytes
                stream.seek(
                    -max_bytes if truncated else 0, os.SEEK_END if truncated else os.SEEK_SET
                )
                value = stream.read().decode("utf-8", errors="replace")
            return value[-max_characters:], truncated
        except (OSError, ValueError):
            return "", False

    @staticmethod
    def _step_draft(
        snapshot: MaterializedRuntimeConfig,
        *,
        changed_files: tuple[str, ...],
        decision_reason: str,
    ) -> RuntimeOperationStepDraft:
        return RuntimeOperationStepDraft(
            owner_type=snapshot.owner_type,
            owner_id=snapshot.owner_id,
            mode=snapshot.profile,
            snapshot_id=snapshot.snapshot_id,
            snapshot_relative_path=snapshot.snapshot_relative_path,
            changed_files=changed_files,
            decision_reason=decision_reason,
            log_relative_path=f"runs/{snapshot.snapshot_id}/execution.log",
        )

    @staticmethod
    def _require_entry(files: list[object], profile: str) -> None:
        entry = next(
            (item for item in files if getattr(item, "relative_path", None) == "deploy.sh"),
            None,
        )
        if entry is None or not getattr(entry, "executable", False):
            raise WorkspaceRuntimeOrchestrationError(
                "runtime_entry_missing",
                f"{profile} 配置必须包含可执行的 deploy.sh",
            )

    @staticmethod
    def _normalize_changed_files(values: list[str], workspace_root: Path) -> list[str]:
        if not 1 <= len(values) <= 500:
            raise WorkspaceRuntimeOrchestrationError(
                "invalid_changed_files", "changed_files 必须包含 1 至 500 个路径"
            )
        root = workspace_root.resolve()
        normalized: set[str] = set()
        for raw in values:
            value = raw.strip()
            path = PurePosixPath(value)
            if (
                not value
                or len(value) > 1000
                or value.startswith("/")
                or "\\" in value
                or "\x00" in value
                or path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise WorkspaceRuntimeOrchestrationError(
                    "invalid_changed_file", "变更文件必须是安全的 Workspace 相对路径"
                )
            canonical = path.as_posix()
            try:
                (root / canonical).resolve(strict=False).relative_to(root)
            except ValueError as exc:
                raise WorkspaceRuntimeOrchestrationError(
                    "changed_file_escape", "变更文件解析后越出 Workspace"
                ) from exc
            normalized.add(canonical)
        return sorted(normalized)

    @staticmethod
    def _is_workspace_path(path: str, configured: tuple[str, ...]) -> bool:
        if path == ".env.local":
            return True
        return any(path == item or path.startswith(f"{item.rstrip('/')}/") for item in configured)

    @staticmethod
    def _ordered_project_ids(
        routed: dict[str, list[str]],
        projects: dict[str, object],
        configured: tuple[str, ...],
    ) -> list[str]:
        configured_ids = [item for item in configured if item in routed]
        remaining = [item for item in routed if item not in configured_ids]
        remaining.sort(
            key=lambda project_id: (
                getattr(projects[project_id], "project_kind", "backend") == "frontend",
                getattr(projects[project_id], "relative_path", ".").casefold(),
                project_id,
            )
        )
        return [*configured_ids, *remaining]


def select_runtime_mode(changed_files: list[str]) -> tuple[str, str]:
    for raw_path in changed_files:
        normalized = raw_path.strip().replace("\\", "/")
        path = PurePosixPath(normalized)
        lower_name = path.name.lower()
        if (
            lower_name in FULL_BUILD_FILE_NAMES
            or lower_name.startswith("dockerfile")
            or "/.mvn/" in f"/{normalized}"
            or "/gradle/" in f"/{normalized}"
        ):
            return "full", f"依赖或构建文件发生变化：{normalized}"
    return "fast", "仅业务代码或资源文件发生变化"
