from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from context_router.repositories.task_repository import TaskRepositoryError, TaskWriter
from context_router.schemas.context import (
    ContextDocumentNode,
    PreparedProject,
    PreparedWorkspace,
    PrepareTaskContextResult,
)
from context_router.services.database_access import DatabaseAccessError, DatabaseAccessService
from context_router.services.document_tree import CachedTreeNode, DocumentCache
from context_router.services.project_registry import (
    ProjectRegistry,
    ProjectRegistryError,
    ProjectSnapshot,
    WorkspaceSnapshot,
)


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
    ) -> None:
        self._registry = registry
        self._task_repository = task_repository
        self._database_access_service = database_access_service

    def prepare(
        self,
        *,
        task: str,
        cwd: str,
        agent_name: str | None = None,
    ) -> PrepareTaskContextResult:
        normalized_task, normalized_agent = self._validate_input(task, agent_name)
        try:
            workspace = self._registry.find_workspace_for_cwd(cwd)
        except ProjectRegistryError as exc:
            raise ContextPreparationError(str(exc)) from exc
        return self._prepare_snapshot(
            workspace,
            task=normalized_task,
            cwd=cwd.strip(),
            agent_name=normalized_agent,
        )

    def prepare_for_workspace(self, workspace_id: str) -> PrepareTaskContextResult:
        try:
            workspace = self._registry.get_workspace_snapshot(workspace_id)
        except ProjectRegistryError as exc:
            raise ContextPreparationError(str(exc)) from exc

        return self._prepare_snapshot(
            workspace,
            task=f"查看工作空间 {workspace.name} 的 MCP JSON",
            cwd=workspace.root_path,
            agent_name="web-preview",
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

    def _prepare_snapshot(
        self,
        workspace: WorkspaceSnapshot,
        *,
        task: str,
        cwd: str,
        agent_name: str | None,
    ) -> PrepareTaskContextResult:
        try:
            active_project = workspace.active_project
            create_workspace_task = getattr(
                self._task_repository,
                "create_workspace_task",
                None,
            )
            if callable(create_workspace_task):
                task_id = create_workspace_task(
                    workspace_id=workspace.id,
                    workspace_key=workspace.workspace_key,
                    workspace_name=workspace.name,
                    task=task,
                    cwd=cwd,
                    agent_name=agent_name,
                    active_project_id=(active_project.id if active_project is not None else None),
                    active_project_name=(
                        active_project.name if active_project is not None else None
                    ),
                    active_project_kind=(
                        active_project.project_kind if active_project is not None else None
                    ),
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
            warnings: list[str] | None = None
            if self._database_access_service is not None:
                try:
                    databases = self._database_access_service.list_prepared_workspace_databases(
                        workspace.id
                    )
                except DatabaseAccessError:
                    warnings = ["工作空间数据库摘要暂时不可用；文档上下文不受影响"]

            projects = [self._prepared_project(project) for project in workspace.projects]
            prepared_active_project = (
                self._prepared_project(workspace.active_project)
                if workspace.active_project is not None
                else None
            )

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
                warnings=warnings,
            )
        except Exception as exc:
            if isinstance(exc, ContextPreparationError) and exc.task_id is not None:
                raise
            raise ContextPreparationError(
                "任务上下文准备失败",
                task_id=task_id,
            ) from exc

    @staticmethod
    def _prepared_project(project: ProjectSnapshot) -> PreparedProject:
        return PreparedProject(
            project_id=project.id,
            name=project.name,
            node_count=len(project.cache.documents),
            relative_path=project.relative_path,
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
