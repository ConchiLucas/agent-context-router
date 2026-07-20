from __future__ import annotations

from pathlib import Path

from context_router.repositories.task_repository import TaskRepositoryError, TaskWriter
from context_router.schemas.context import (
    ContextDocumentNode,
    PreparedProject,
    PrepareTaskContextResult,
)
from context_router.services.document_tree import CachedTreeNode, DocumentCache
from context_router.services.project_registry import (
    ProjectRegistry,
    ProjectRegistryError,
    ProjectSnapshot,
)


class ContextPreparationError(ValueError):
    pass


class ContextPreparationService:
    def __init__(self, registry: ProjectRegistry, task_repository: TaskWriter) -> None:
        self._registry = registry
        self._task_repository = task_repository

    def prepare(
        self,
        *,
        task: str,
        cwd: str,
        agent_name: str | None = None,
    ) -> PrepareTaskContextResult:
        normalized_task, normalized_agent = self._validate_input(task, agent_name)
        try:
            project = self._registry.find_project_for_cwd(cwd)
        except ProjectRegistryError as exc:
            raise ContextPreparationError(str(exc)) from exc
        return self._prepare_snapshot(
            project,
            task=normalized_task,
            cwd=cwd.strip(),
            agent_name=normalized_agent,
        )

    def prepare_for_project(self, project_id: str) -> PrepareTaskContextResult:
        try:
            project = self._registry.get_snapshot(project_id)
        except ProjectRegistryError as exc:
            raise ContextPreparationError(str(exc)) from exc

        task = f"查看项目 {project.name} 的 MCP JSON"
        cwd = str(Path(project.agents_path).expanduser().parent)
        return self._prepare_snapshot(
            project,
            task=task,
            cwd=cwd,
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
        project: ProjectSnapshot,
        *,
        task: str,
        cwd: str,
        agent_name: str | None,
    ) -> PrepareTaskContextResult:
        try:
            task_id = self._task_repository.create_task(
                project_key=project.project_key,
                project_name=project.name,
                task=task,
                cwd=cwd,
                agent_name=agent_name,
            )
        except TaskRepositoryError as exc:
            raise ContextPreparationError(str(exc)) from exc

        return PrepareTaskContextResult(
            task_id=task_id,
            project=PreparedProject(
                project_id=project.id,
                name=project.name,
                node_count=len(project.cache.documents),
            ),
            documents=self._context_node(project.cache.root, project.cache),
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
