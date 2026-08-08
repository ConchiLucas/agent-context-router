from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from context_router.repositories.task_repository import (
    TaskRepositoryError,
    TaskWriter,
)
from context_router.schemas.context import (
    ContextDocumentNode,
    DatabaseEnvironment,
    DatabaseEnvironmentSelection,
    PreparedDatabaseEnvironment,
    PreparedProject,
    PreparedSystemGuide,
    PreparedSystemGuideCatalogItem,
    PreparedSystemGuides,
    PreparedWorkspace,
    PreparedWorkspaceAccess,
    PrepareTaskContextResult,
)
from context_router.services.database_access import (
    DatabaseAccessError,
    DatabaseAccessService,
)
from context_router.services.document_tree import CachedTreeNode, DocumentCache
from context_router.services.project_registry import (
    ProjectRegistry,
    ProjectRegistryError,
    ProjectSnapshot,
    WorkspaceSnapshot,
)
from context_router.services.system_guides import SystemGuideError, SystemGuideService


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


class ContextPreparationService:
    def __init__(
        self,
        registry: ProjectRegistry,
        task_repository: TaskWriter,
        database_access_service: DatabaseAccessService | None = None,
        system_guide_service: SystemGuideService | None = None,
    ) -> None:
        self._registry = registry
        self._task_repository = task_repository
        self._database_access_service = database_access_service
        self._system_guide_service = system_guide_service

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
        environment_config = None
        environment_config_warning: str | None = None
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
                    # This exact user-maintained payload may contain connection details
                    # and credentials. Return it to the local MCP caller, but never log it.
                    environment_config = (
                        self._database_access_service.get_active_environment_payload(
                            workspace.id,
                            environment=selected_database_environment,
                            revision=database_environment.revision,
                            database_environment_selection=(database_environment_selection),
                        )
                    )
                except DatabaseAccessError as exc:
                    if exc.code == "environment_changed":
                        raise ContextPreparationError(
                            str(exc),
                            code="environment_changed",
                        ) from exc
                    if exc.code != "environment_config_not_configured":
                        environment_config_warning = (
                            "工作空间环境 JSON 暂时不可用；文档上下文不受影响"
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
            databases = []
            warning_items = [
                warning
                for warning in (
                    database_environment_warning,
                    environment_config_warning,
                )
                if warning
            ]
            if (
                not documents_only
                and self._database_access_service is not None
                and database_environment_warning is None
            ):
                try:
                    databases = self._database_access_service.list_prepared_workspace_databases(
                        workspace.id,
                        database_environment=selected_database_environment,
                        database_environment_revision=(
                            database_environment.revision
                            if database_environment is not None
                            else None
                        ),
                        database_environment_selection=(database_environment_selection),
                    )
                except DatabaseAccessError as exc:
                    if exc.code in {
                        "environment_changed",
                        "environment_not_configured",
                    }:
                        raise ContextPreparationError(
                            str(exc),
                            task_id=task_id,
                            code=exc.code,
                        ) from exc
                    warning_items.append("工作空间数据库摘要暂时不可用；文档上下文不受影响")

            projects = [self._prepared_project(project) for project in workspace.projects]
            prepared_active_project = (
                self._prepared_project(workspace.active_project)
                if workspace.active_project is not None
                else None
            )
            system_guides = self._prepared_system_guides(warning_items)

            return PrepareTaskContextResult(
                task_id=task_id,
                workspace=PreparedWorkspace(
                    workspace_id=workspace.id,
                    name=workspace.name,
                ),
                projects=projects,
                active_project=prepared_active_project,
                project=prepared_active_project,
                documents=self._context_node(workspace.cache.root, workspace.cache),
                databases=databases,
                database_environment=(
                    PreparedDatabaseEnvironment(
                        key=selected_database_environment,
                        name=selected_database_environment.upper(),
                        revision=database_environment.revision,
                        selection=database_environment_selection,
                    )
                    if database_environment is not None
                    and selected_database_environment is not None
                    and database_environment_selection is not None
                    else None
                ),
                environment_config=environment_config,
                workspace_access=PreparedWorkspaceAccess(
                    mode=workspace.access_mode,
                    message=(
                        "当前目录是文档阅读目录，可以读取主目录共享文档；"
                        "不能使用数据库、部署或共享文件覆盖功能。"
                        if documents_only
                        else (
                            "当前目录是工作空间主目录，可以使用文档、数据库、"
                            "部署和共享文件覆盖功能。"
                        )
                    ),
                ),
                system_guides=system_guides,
                warnings=warning_items or None,
            )
        except Exception as exc:
            if isinstance(exc, ContextPreparationError) and exc.task_id is not None:
                raise
            raise ContextPreparationError(
                "任务上下文准备失败",
                task_id=task_id,
            ) from exc

    def _prepared_system_guides(self, warning_items: list[str]) -> PreparedSystemGuides:
        if self._system_guide_service is None:
            return PreparedSystemGuides()
        try:
            guides = self._system_guide_service.list_guides()
        except SystemGuideError:
            warning_items.append("系统使用说明暂时不可用；工作空间上下文不受影响")
            return PreparedSystemGuides()
        catalog = [
            PreparedSystemGuideCatalogItem(
                document_id=item.document_id,
                key=item.guide_key,
                title=item.title,
                summary=item.summary,
            )
            for item in guides
        ]
        required = [
            PreparedSystemGuide(
                document_id=item.document_id,
                key=item.guide_key,
                title=item.title,
                summary=item.summary,
                content=item.document,
            )
            for item in guides
            if item.include_in_prepare
        ]
        return PreparedSystemGuides(required=required, catalog=catalog)

    @staticmethod
    def _prepared_project(project: ProjectSnapshot) -> PreparedProject:
        return PreparedProject(
            project_id=project.id,
            name=project.name,
            node_count=len(project.cache.documents),
            relative_path=project.relative_path,
            document_relative_path=project.document_relative_path,
            project_kind=project.project_kind,
        )

    def _context_node(
        self,
        node: CachedTreeNode,
        cache: DocumentCache,
    ) -> ContextDocumentNode:
        return ContextDocumentNode(
            document_id=node.id,
            path=self._relative_path(node, cache),
            title=node.title,
            summary=node.summary,
            error=node.error,
            children=[self._context_node(child, cache) for child in node.children],
        )

    @staticmethod
    def _relative_path(node: CachedTreeNode, cache: DocumentCache) -> str:
        try:
            return Path(node.path).resolve().relative_to(cache.project_root).as_posix()
        except ValueError:
            if node.relative_path:
                return node.relative_path.removeprefix("./")
            return "AGENTS.md"
