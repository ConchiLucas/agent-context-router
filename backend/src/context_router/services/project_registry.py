from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from context_router.config import Settings
from context_router.repositories.project_repository import (
    ProjectRepositoryError,
    ProjectStore,
)
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
    enabled: bool = True
    cache: DocumentCache | None = None
    refreshed_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    id: str
    project_key: str
    name: str
    agents_path: str
    resolved_agents_path: Path
    cache: DocumentCache


class ProjectRegistry:
    def __init__(
        self,
        settings: Settings,
        project_repository: ProjectStore | None = None,
    ) -> None:
        self._settings = settings
        self._project_repository = project_repository
        self._projects: dict[str, ProjectState] = {}
        self._lock = RLock()

    def _map_agents_path(self, agents_path: str) -> Path:
        source = Path(agents_path).expanduser()
        if not source.is_absolute():
            raise ProjectRegistryError("AGENTS.md 必须填写绝对路径")
        if source.name != "AGENTS.md":
            raise ProjectRegistryError("入口文件必须命名为 AGENTS.md")

        host_root = self._settings.workspace_host_root
        container_root = self._settings.workspace_container_root
        try:
            relative = source.relative_to(host_root)
        except ValueError:
            resolved = source.resolve()
        else:
            resolved = (container_root / relative).resolve()

        return resolved

    def _resolve_agents_path(self, agents_path: str) -> Path:
        resolved = self._map_agents_path(agents_path)
        if not resolved.is_file():
            raise ProjectRegistryError(f"找不到入口文件：{agents_path}")
        return resolved

    def _resolve_cwd(self, cwd: str) -> Path:
        source = Path(cwd.strip()).expanduser()
        if not source.is_absolute():
            raise ProjectRegistryError("cwd 必须是绝对路径")

        try:
            relative = source.relative_to(self._settings.workspace_host_root)
        except ValueError:
            return source.resolve()
        return (self._settings.workspace_container_root / relative).resolve()

    @staticmethod
    def _project_key(agents_path: str) -> str:
        normalized_path = str(Path(agents_path).expanduser())
        return hashlib.sha256(normalized_path.encode()).hexdigest()

    @classmethod
    def _snapshot(cls, project: ProjectState) -> ProjectSnapshot:
        if not project.enabled:
            raise ProjectRegistryError("项目已停用")
        if project.cache is None:
            if project.error:
                raise ProjectRegistryError(f"项目映射不可用：{project.error}")
            raise ProjectRegistryError("项目尚未刷新映射")
        return ProjectSnapshot(
            id=project.id,
            project_key=cls._project_key(project.agents_path),
            name=project.name,
            agents_path=project.agents_path,
            resolved_agents_path=project.resolved_agents_path,
            cache=project.cache,
        )

    @staticmethod
    def _summary(project: ProjectState) -> ProjectSummary:
        return ProjectSummary(
            id=project.id,
            name=project.name,
            agents_path=project.agents_path,
            enabled=project.enabled,
            node_count=len(project.cache.documents) if project.cache else 0,
            refreshed_at=project.refreshed_at,
            error=project.error,
        )

    def list_projects(self) -> list[ProjectSummary]:
        with self._lock:
            return [self._summary(project) for project in self._projects.values()]

    def load_persisted_projects(self) -> list[ProjectSummary]:
        if self._project_repository is None:
            return self.list_projects()
        try:
            records = self._project_repository.list_projects()
        except ProjectRepositoryError as exc:
            raise ProjectRegistryError(str(exc)) from exc

        restored: dict[str, ProjectState] = {}
        for record in records:
            cache: DocumentCache | None = None
            refreshed_at: datetime | None = None
            error: str | None = None
            try:
                resolved_path = self._map_agents_path(record.agents_path)
                if record.enabled:
                    if not resolved_path.is_file():
                        raise ProjectRegistryError(f"找不到入口文件：{record.agents_path}")
                    cache = build_document_cache(resolved_path)
                    refreshed_at = datetime.now(UTC)
            except (ProjectRegistryError, DocumentTreeError) as exc:
                resolved_path = Path(record.agents_path).expanduser()
                error = str(exc)

            restored[record.id] = ProjectState(
                id=record.id,
                name=record.name,
                agents_path=record.agents_path,
                resolved_agents_path=resolved_path,
                enabled=record.enabled,
                cache=cache,
                refreshed_at=refreshed_at,
                error=error,
            )

        with self._lock:
            self._projects = restored
            return [self._summary(project) for project in self._projects.values()]

    def has_agents_path(self, agents_path: str) -> bool:
        normalized = str(Path(agents_path).expanduser())
        with self._lock:
            return any(
                str(Path(project.agents_path).expanduser()) == normalized
                for project in self._projects.values()
            )

    def add_project(
        self,
        *,
        name: str,
        agents_path: str,
        persist: bool = True,
    ) -> ProjectSummary:
        normalized_name = name.strip()
        normalized_path = agents_path.strip()
        if not normalized_name:
            raise ProjectRegistryError("项目名称不能为空")

        resolved_path = self._resolve_agents_path(normalized_path)
        try:
            new_cache = build_document_cache(resolved_path)
        except DocumentTreeError as exc:
            raise ProjectRegistryError(str(exc)) from exc

        project_id = uuid4().hex
        with self._lock:
            if any(
                project.resolved_agents_path == resolved_path for project in self._projects.values()
            ):
                raise ProjectRegistryError("这个 AGENTS.md 已经添加")

        if persist and self._project_repository is not None:
            try:
                self._project_repository.create_project(
                    project_id=project_id,
                    name=normalized_name,
                    agents_path=normalized_path,
                    enabled=True,
                )
            except ProjectRepositoryError as exc:
                raise ProjectRegistryError(str(exc)) from exc

        with self._lock:
            project = ProjectState(
                id=project_id,
                name=normalized_name,
                agents_path=normalized_path,
                resolved_agents_path=resolved_path,
                cache=new_cache,
                refreshed_at=datetime.now(UTC),
            )
            self._projects[project.id] = project
            return self._summary(project)

    def update_project(
        self,
        project_id: str,
        *,
        name: str,
        agents_path: str,
    ) -> ProjectSummary:
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
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            if any(
                item.id != project_id and item.resolved_agents_path == resolved_path
                for item in self._projects.values()
            ):
                raise ProjectRegistryError("这个 AGENTS.md 已经添加")

        if self._project_repository is not None:
            try:
                self._project_repository.update_project(
                    project_id,
                    name=normalized_name,
                    agents_path=normalized_path,
                )
            except ProjectRepositoryError as exc:
                raise ProjectRegistryError(str(exc)) from exc

        with self._lock:
            project.name = normalized_name
            project.agents_path = normalized_path
            project.resolved_agents_path = resolved_path
            project.cache = new_cache if project.enabled else None
            project.refreshed_at = datetime.now(UTC) if project.enabled else None
            project.error = None
            return self._summary(project)

    def set_project_enabled(self, project_id: str, *, enabled: bool) -> ProjectSummary:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            if project.enabled == enabled:
                return self._summary(project)
            agents_path = project.agents_path

        new_cache: DocumentCache | None = None
        resolved_path = project.resolved_agents_path
        if enabled:
            resolved_path = self._resolve_agents_path(agents_path)
            try:
                new_cache = build_document_cache(resolved_path)
            except DocumentTreeError as exc:
                raise ProjectRegistryError(str(exc)) from exc

        if self._project_repository is not None:
            try:
                self._project_repository.set_project_enabled(
                    project_id,
                    enabled=enabled,
                )
            except ProjectRepositoryError as exc:
                raise ProjectRegistryError(str(exc)) from exc

        with self._lock:
            project.enabled = enabled
            project.resolved_agents_path = resolved_path
            project.cache = new_cache
            project.refreshed_at = datetime.now(UTC) if enabled else None
            project.error = None
            return self._summary(project)

    def delete_project(self, project_id: str) -> None:
        with self._lock:
            if project_id not in self._projects:
                raise ProjectRegistryError("项目不存在")
        if self._project_repository is not None:
            try:
                self._project_repository.delete_project(project_id)
            except ProjectRepositoryError as exc:
                raise ProjectRegistryError(str(exc)) from exc
        with self._lock:
            self._projects.pop(project_id, None)

    def refresh_project(self, project_id: str) -> ProjectSummary:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            if not project.enabled:
                raise ProjectRegistryError("项目已停用")
            resolved_path = project.resolved_agents_path

        try:
            resolved_path = self._resolve_agents_path(project.agents_path)
            new_cache = build_document_cache(resolved_path)
        except (ProjectRegistryError, DocumentTreeError) as exc:
            with self._lock:
                project.error = str(exc)
            raise ProjectRegistryError(str(exc)) from exc

        with self._lock:
            project.cache = new_cache
            project.resolved_agents_path = resolved_path
            project.refreshed_at = datetime.now(UTC)
            project.error = None
            return self._summary(project)

    def get_tree(self, project_id: str) -> DocumentTreeNode:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            if not project.enabled:
                raise ProjectRegistryError("项目已停用")
            if project.cache is None:
                if project.error:
                    raise ProjectRegistryError(f"项目映射不可用：{project.error}")
                raise ProjectRegistryError("项目尚未刷新映射")
            return project.cache.root.to_schema()

    def get_snapshot(self, project_id: str) -> ProjectSnapshot:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            return self._snapshot(project)

    def find_project_for_cwd(self, cwd: str) -> ProjectSnapshot:
        resolved_cwd = self._resolve_cwd(cwd)
        with self._lock:
            candidates = [
                project
                for project in self._projects.values()
                if project.enabled
                and project.cache is not None
                and (
                    resolved_cwd == project.resolved_agents_path.parent
                    or project.resolved_agents_path.parent in resolved_cwd.parents
                )
            ]
            if not candidates:
                raise ProjectRegistryError("cwd 没有匹配已注册项目")
            project = max(
                candidates,
                key=lambda item: len(item.resolved_agents_path.parent.parts),
            )
            return self._snapshot(project)

    def get_snapshot_by_project_key(self, project_key: str) -> ProjectSnapshot:
        with self._lock:
            for project in self._projects.values():
                if self._project_key(project.agents_path) == project_key:
                    return self._snapshot(project)
        raise ProjectRegistryError("任务绑定的项目不存在")

    def get_document(self, project_id: str, document_id: str) -> DocumentDetail:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            if not project.enabled:
                raise ProjectRegistryError("项目已停用")
            if project.cache is None:
                if project.error:
                    raise ProjectRegistryError(f"项目映射不可用：{project.error}")
                raise ProjectRegistryError("项目尚未刷新映射")

            document = project.cache.documents.get(document_id)
            if document is None:
                raise ProjectRegistryError("文档不在当前内存映射中")
            return document.to_detail()
