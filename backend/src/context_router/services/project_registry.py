from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from context_router.config import Settings
from context_router.schemas.projects import (
    DocumentDetail,
    DocumentTreeNode,
    ProjectSummary,
)
from context_router.services.document_tree import (
    DocumentCache,
    DocumentTreeError,
    build_document_cache,
)


class ProjectRegistryError(ValueError):
    pass


@dataclass(slots=True)
class ProjectState:
    id: str
    name: str
    agents_path: str
    resolved_agents_path: Path
    cache: DocumentCache | None = None
    refreshed_at: datetime | None = None
    error: str | None = None


class ProjectRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._projects: dict[str, ProjectState] = {}
        self._lock = RLock()

    def _resolve_agents_path(self, agents_path: str) -> Path:
        source = Path(agents_path).expanduser()
        if not source.is_absolute():
            raise ProjectRegistryError("AGENTS.md 必须填写绝对路径")

        host_root = self._settings.workspace_host_root
        container_root = self._settings.workspace_container_root
        try:
            relative = source.relative_to(host_root)
        except ValueError:
            resolved = source.resolve()
        else:
            resolved = (container_root / relative).resolve()

        if resolved.name != "AGENTS.md":
            raise ProjectRegistryError("入口文件必须命名为 AGENTS.md")
        if not resolved.is_file():
            raise ProjectRegistryError(f"找不到入口文件：{agents_path}")
        return resolved

    @staticmethod
    def _summary(project: ProjectState) -> ProjectSummary:
        return ProjectSummary(
            id=project.id,
            name=project.name,
            agents_path=project.agents_path,
            node_count=len(project.cache.documents) if project.cache else 0,
            refreshed_at=project.refreshed_at,
            error=project.error,
        )

    def list_projects(self) -> list[ProjectSummary]:
        with self._lock:
            return [self._summary(project) for project in self._projects.values()]

    def add_project(self, *, name: str, agents_path: str) -> ProjectSummary:
        normalized_name = name.strip()
        normalized_path = agents_path.strip()
        if not normalized_name:
            raise ProjectRegistryError("项目名称不能为空")

        resolved_path = self._resolve_agents_path(normalized_path)
        try:
            new_cache = build_document_cache(resolved_path)
        except DocumentTreeError as exc:
            raise ProjectRegistryError(str(exc)) from exc

        with self._lock:
            if any(
                project.resolved_agents_path == resolved_path for project in self._projects.values()
            ):
                raise ProjectRegistryError("这个 AGENTS.md 已经添加")

            project = ProjectState(
                id=uuid4().hex,
                name=normalized_name,
                agents_path=normalized_path,
                resolved_agents_path=resolved_path,
                cache=new_cache,
                refreshed_at=datetime.now(UTC),
            )
            self._projects[project.id] = project
            return self._summary(project)

    def refresh_project(self, project_id: str) -> ProjectSummary:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            resolved_path = project.resolved_agents_path

        try:
            new_cache = build_document_cache(resolved_path)
        except DocumentTreeError as exc:
            with self._lock:
                project.error = str(exc)
            raise ProjectRegistryError(str(exc)) from exc

        with self._lock:
            project.cache = new_cache
            project.refreshed_at = datetime.now(UTC)
            project.error = None
            return self._summary(project)

    def get_tree(self, project_id: str) -> DocumentTreeNode:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            if project.cache is None:
                raise ProjectRegistryError("项目尚未刷新映射")
            return project.cache.root.to_schema()

    def get_document(self, project_id: str, document_id: str) -> DocumentDetail:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            if project.cache is None:
                raise ProjectRegistryError("项目尚未刷新映射")

            document = project.cache.documents.get(document_id)
            if document is None:
                raise ProjectRegistryError("文档不在当前内存映射中")
            return document.to_detail()
