from __future__ import annotations

from dataclasses import replace

from context_router.repositories.task_repository import (
    TaskRecord,
    TaskRepositoryError,
    TaskStore,
)
from context_router.schemas.context import (
    ContextDocumentNode,
    DatabaseEnvironment,
    DatabaseEnvironmentSelection,
    PreparedDatabaseEnvironment,
    PrepareTaskContextResult,
    ReadTaskContextResult,
    TaskEnvironmentContext,
)
from context_router.services.database_access import (
    DatabaseAccessError,
    DatabaseAccessService,
)
from context_router.services.document_tree import CachedTreeNode
from context_router.services.project_registry import (
    ProjectRegistry,
    ProjectRegistryError,
    WorkspaceSnapshot,
)

PREPARE_DOCUMENT_TREE_LEVELS = 3


class ContextPreparationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        task_id: int | None = None,
        code: str = "context_preparation_failed",
    ) -> None:
        super().__init__(message)
        self.task_id = task_id
        self.code = code


class TaskContextReadError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ContextPreparationService:
    def __init__(
        self,
        registry: ProjectRegistry,
        task_repository: TaskStore,
        database_access_service: DatabaseAccessService | None = None,
    ) -> None:
        self._registry = registry
        self._task_repository = task_repository
        self._database_access_service = database_access_service

    def read_task_context(
        self,
        *,
        task_id: int,
        sections: list[str],
    ) -> ReadTaskContextResult:
        normalized_sections = list(dict.fromkeys(sections))
        if not normalized_sections or any(
            section not in {"databases", "environment"} for section in normalized_sections
        ):
            raise TaskContextReadError(
                "invalid_context_section",
                "sections 只能包含 databases 或 environment",
            )
        try:
            task = self._task_repository.get_task(task_id)
        except TaskRepositoryError as exc:
            raise TaskContextReadError("task_not_found", "任务不存在，请重新 prepare") from exc

        workspace = self._workspace_for_task(task)
        if workspace is not None:
            try:
                routed_workspace = self._registry.find_workspace_for_cwd(task.cwd)
            except ProjectRegistryError as exc:
                raise TaskContextReadError(
                    "workspace_unavailable",
                    "任务绑定的工作空间当前不可用，请重新 prepare",
                ) from exc
            if routed_workspace.id != workspace.id:
                raise TaskContextReadError(
                    "workspace_unavailable",
                    "任务绑定的工作空间已发生变化，请重新 prepare",
                )
            if routed_workspace.access_mode == "documents_only":
                raise TaskContextReadError(
                    "documents_only",
                    "当前目录只能读取文档，不能读取数据库或环境配置",
                )

        if self._database_access_service is None:
            raise TaskContextReadError(
                "database_tools_disabled",
                "数据库和环境上下文当前不可用",
            )

        databases = None
        environment_context = None
        try:
            if "databases" in normalized_sections:
                if workspace is not None:
                    databases = self._database_access_service.list_prepared_workspace_databases(
                        workspace.id,
                        database_environment=task.database_environment,
                        database_environment_revision=task.database_environment_revision,
                        database_environment_selection=task.database_environment_selection,
                    )
                else:
                    if task.project_id is None:
                        raise TaskContextReadError(
                            "project_unavailable",
                            "任务缺少项目快照，请重新 prepare",
                        )
                    databases = self._database_access_service.list_prepared_databases(
                        task.project_id
                    )

            if "environment" in normalized_sections:
                environment_context = self._environment_context(
                    task,
                    workspace.id if workspace else None,
                )
        except DatabaseAccessError as exc:
            raise TaskContextReadError(exc.code, str(exc)) from exc

        return ReadTaskContextResult(
            task_id=task_id,
            databases=databases,
            environment=environment_context,
        )

    def _workspace_for_task(self, task: TaskRecord) -> WorkspaceSnapshot | None:
        if task.scope != "workspace":
            return None
        try:
            return self._registry.get_workspace_snapshot_for_task(
                workspace_id=task.workspace_id,
                workspace_key=task.workspace_key,
            )
        except ProjectRegistryError as exc:
            raise TaskContextReadError(
                "workspace_unavailable",
                "任务绑定的工作空间当前不可用，请重新 prepare",
            ) from exc

    def _environment_context(
        self,
        task: TaskRecord,
        workspace_id: str | None,
    ) -> TaskEnvironmentContext:
        if (
            workspace_id is None
            or task.database_environment not in {"test", "uat"}
            or task.database_environment_revision is None
        ):
            return TaskEnvironmentContext(configured=False)
        selection = task.database_environment_selection or "workspace_default"
        selected = PreparedDatabaseEnvironment(
            key=task.database_environment,
            name=task.database_environment.upper(),
            revision=task.database_environment_revision,
            selection=selection,
        )
        try:
            config = self._database_access_service.get_active_environment_payload(
                workspace_id,
                environment=task.database_environment,
                revision=task.database_environment_revision,
                database_environment_selection=selection,
            )
        except DatabaseAccessError as exc:
            if exc.code == "environment_config_not_configured":
                return TaskEnvironmentContext(configured=False, selected=selected)
            raise
        return TaskEnvironmentContext(
            configured=True,
            selected=selected,
            config=config,
        )

    def prepare(
        self,
        *,
        task: str,
        cwd: str,
        agent_name: str | None = None,
        environment: DatabaseEnvironment | None = None,
    ) -> PrepareTaskContextResult:
        normalized_task, normalized_agent = self._validate_input(task, agent_name)
        normalized_environment = self._validate_environment(environment)
        try:
            workspace = self._registry.find_workspace_for_cwd(cwd)
        except ProjectRegistryError as exc:
            raise ContextPreparationError(str(exc)) from exc
        return self._prepare_snapshot(
            workspace,
            task=normalized_task,
            cwd=cwd.strip(),
            agent_name=normalized_agent,
            environment=normalized_environment,
        )

    def prepare_for_workspace(
        self,
        workspace_id: str,
        *,
        environment: DatabaseEnvironment | None = None,
    ) -> PrepareTaskContextResult:
        normalized_environment = self._validate_environment(environment)
        try:
            workspace = self._registry.get_workspace_snapshot(workspace_id)
        except ProjectRegistryError as exc:
            raise ContextPreparationError(str(exc)) from exc

        return self._prepare_snapshot(
            workspace,
            task=f"查看工作空间 {workspace.name} 的 MCP JSON",
            cwd=workspace.root_path,
            agent_name="web-preview",
            environment=normalized_environment,
        )

    def prepare_for_project(self, project_id: str) -> PrepareTaskContextResult:
        """Compatibility wrapper for callers that still hold a Project id."""
        try:
            project = self._registry.get_snapshot(project_id)
            if project.workspace_id is None:
                raise ProjectRegistryError("项目尚未归属工作空间")
            workspace = self._registry.get_workspace_snapshot(project.workspace_id)
            active_project = next(item for item in workspace.projects if item.id == project.id)
        except (ProjectRegistryError, StopIteration) as exc:
            raise ContextPreparationError(str(exc)) from exc
        return self._prepare_snapshot(
            replace(workspace, active_project=active_project),
            task=f"查看工作空间 {workspace.name} 的 MCP JSON",
            cwd=workspace.root_path,
            agent_name="web-preview",
            environment=None,
        )

    @staticmethod
    def _validate_input(task: str, agent_name: str | None) -> tuple[str, str | None]:
        normalized_task = task.strip()
        if not normalized_task:
            raise ContextPreparationError("task 不能为空")
        if len(normalized_task) > 4000:
            raise ContextPreparationError("task 不能超过 4000 个字符")

        normalized_agent = agent_name.strip() if agent_name else None
        if normalized_agent and len(normalized_agent) > 64:
            raise ContextPreparationError("agent_name 不能超过 64 个字符")
        return normalized_task, normalized_agent or None

    @staticmethod
    def _validate_environment(
        environment: DatabaseEnvironment | None,
    ) -> DatabaseEnvironment | None:
        if environment not in {None, "test", "uat"}:
            raise ContextPreparationError(
                "environment 必须是 test 或 uat",
                code="invalid_environment",
            )
        return environment

    def _prepare_snapshot(
        self,
        workspace: WorkspaceSnapshot,
        *,
        task: str,
        cwd: str,
        agent_name: str | None,
        environment: DatabaseEnvironment | None,
    ) -> PrepareTaskContextResult:
        database_environment = None
        selected_database_environment: DatabaseEnvironment | None = None
        database_environment_selection: DatabaseEnvironmentSelection | None = None
        database_environment_warning: str | None = None
        documents_only = workspace.access_mode == "documents_only"
        if documents_only:
            if environment is not None:
                raise ContextPreparationError(
                    "共享文档目录不能选择数据库环境",
                    code="documents_only",
                )
            database_environment_warning = "当前目录共享主工作空间文档；数据库和部署工具不可用"
        elif self._database_access_service is None:
            if environment is not None:
                raise ContextPreparationError(
                    "工作空间尚未配置环境选择器，不能显式选择环境",
                    code="environment_not_configured",
                )
        else:
            try:
                database_environment = (
                    self._database_access_service.get_active_workspace_environment(workspace.id)
                )
            except DatabaseAccessError as exc:
                if environment is not None:
                    raise ContextPreparationError(
                        str(exc),
                        code=exc.code,
                    ) from exc
                database_environment_warning = "工作空间环境配置暂时不可用；文档上下文不受影响"
            if database_environment is None and environment is not None:
                raise ContextPreparationError(
                    "工作空间尚未配置环境选择器，不能显式选择环境",
                    code="environment_not_configured",
                )
            if database_environment is not None:
                selected_database_environment = (
                    environment or database_environment.active_environment
                )
                database_environment_selection = (
                    "task_explicit" if environment is not None else "workspace_default"
                )

        try:
            active_project = workspace.active_project
            create_workspace_task = getattr(
                self._task_repository,
                "create_workspace_task",
                None,
            )
            if callable(create_workspace_task):
                create_values: dict[str, object] = {
                    "workspace_id": workspace.id,
                    "workspace_key": workspace.workspace_key,
                    "workspace_name": workspace.name,
                    "task": task,
                    "cwd": cwd,
                    "agent_name": agent_name,
                    "active_project_id": (
                        active_project.id if active_project is not None else None
                    ),
                    "active_project_name": (
                        active_project.name if active_project is not None else None
                    ),
                    "active_project_kind": (
                        active_project.project_kind if active_project is not None else None
                    ),
                }
                if database_environment is not None:
                    create_values.update(
                        database_environment=selected_database_environment,
                        database_environment_revision=database_environment.revision,
                        database_environment_selection=database_environment_selection,
                    )
                task_id = create_workspace_task(
                    **create_values,
                )
            else:
                fallback_project = active_project or next(
                    iter(workspace.projects),
                    None,
                )
                if fallback_project is None:
                    raise TaskRepositoryError("工作空间至少需要一个项目才能创建任务")
                task_id = self._task_repository.create_task(
                    project_id=fallback_project.id,
                    project_key=fallback_project.project_key,
                    project_name=fallback_project.name,
                    task=task,
                    cwd=cwd,
                    agent_name=agent_name,
                )
        except TaskRepositoryError as exc:
            raise ContextPreparationError(str(exc)) from exc

        try:
            warning_items = [warning for warning in (database_environment_warning,) if warning]
            document_root = self._registry.get_prepare_document_root(workspace)
            documents = self._context_node(
                document_root,
                levels_remaining=PREPARE_DOCUMENT_TREE_LEVELS,
                warning_items=warning_items,
            )

            return PrepareTaskContextResult(
                task_id=task_id,
                documents=documents,
                access=(
                    ["documents"]
                    if documents_only
                    else ["documents", "database", "environment", "middleware", "runtime"]
                ),
                warnings=warning_items or None,
            )
        except Exception as exc:
            if isinstance(exc, ContextPreparationError) and exc.task_id is not None:
                raise
            raise ContextPreparationError(
                "任务上下文准备失败",
                task_id=task_id,
            ) from exc

    def _context_node(
        self,
        node: CachedTreeNode,
        *,
        levels_remaining: int,
        warning_items: list[str],
    ) -> ContextDocumentNode:
        if node.error:
            warning_items.append(f"文档“{node.description}”不可用：{node.error}")
        return ContextDocumentNode(
            document_id=node.id,
            summary=(node.summary or node.description).strip(),
            children=(
                [
                    self._context_node(
                        child,
                        levels_remaining=levels_remaining - 1,
                        warning_items=warning_items,
                    )
                    for child in node.children
                ]
                if levels_remaining > 1
                else []
            ),
        )
