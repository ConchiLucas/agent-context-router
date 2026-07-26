from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from context_router.config import Settings
from context_router.repositories.project_repository import (
    DEFAULT_PROJECT_TYPE,
    ProjectRepositoryError,
    ProjectStore,
)
from context_router.repositories.workspace_repository import WorkspaceRecord
from context_router.schemas.projects import (
    DocumentDetail,
    DocumentTreeNode,
    ProjectSummary,
)
from context_router.services.document_search_index import (
    DocumentSearchIndexer,
    DocumentSearchIndexError,
)
from context_router.services.document_tree import (
    CachedDocument,
    CachedTreeNode,
    DocumentCache,
    DocumentTreeError,
    build_document_cache,
    build_workspace_document_cache,
)
from context_router.services.workspace_paths import (
    WorkspacePathError,
    derive_agents_path,
    normalize_project_relative_path,
)

logger = logging.getLogger(__name__)


class ProjectRegistryError(ValueError):
    pass


@dataclass(slots=True)
class ProjectState:
    id: str
    name: str
    project_type: str
    agents_path: str
    resolved_agents_path: Path
    workspace_id: str | None = None
    workspace_name: str | None = None
    workspace_root_path: str | None = None
    workspace_enabled: bool = True
    relative_path: str = "."
    project_kind: str = "backend"
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
    workspace_id: str | None = None
    workspace_name: str | None = None
    relative_path: str = "."
    project_kind: str = "backend"


@dataclass(slots=True)
class WorkspaceState:
    id: str
    name: str
    workspace_type: str
    root_path: str
    resolved_root_path: Path
    enabled: bool
    document_entry_path: Path | None = None
    document_cache: DocumentCache | None = None
    document_error: str | None = None
    document_entry_checked: bool = False
    refreshed_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    id: str
    workspace_key: str
    name: str
    workspace_type: str
    root_path: str
    resolved_root_path: Path
    enabled: bool
    cache: DocumentCache
    document_cache: DocumentCache | None
    projects: tuple[ProjectSnapshot, ...]
    active_project: ProjectSnapshot | None = None


class ProjectRegistry:
    def __init__(
        self,
        settings: Settings,
        project_repository: ProjectStore | None = None,
        document_search_indexer: DocumentSearchIndexer | None = None,
    ) -> None:
        self._settings = settings
        self._project_repository = project_repository
        self._document_search_indexer = document_search_indexer
        self._projects: dict[str, ProjectState] = {}
        self._workspaces: dict[str, WorkspaceState] = {}
        self._lock = RLock()

    def _ensure_search_index(
        self,
        project_id: str,
        cache: DocumentCache,
        *,
        force: bool = False,
    ) -> None:
        if self._document_search_indexer is None:
            return
        try:
            if force:
                self._document_search_indexer.rebuild_project_index(
                    project_id=project_id,
                    cache=cache,
                )
            else:
                self._document_search_indexer.ensure_project_index(
                    project_id=project_id,
                    cache=cache,
                )
        except DocumentSearchIndexError as exc:
            # The document tree and direct reads remain available. The search
            # service rejects a missing/stale index by comparing cache versions.
            logger.warning(
                "Unable to refresh document search index for project %s: %s",
                project_id,
                exc,
            )

    def _ensure_workspace_search_index(
        self,
        workspace_id: str,
        cache: DocumentCache,
        *,
        force: bool = False,
    ) -> None:
        if self._document_search_indexer is None:
            return
        try:
            if force:
                self._document_search_indexer.rebuild_workspace_index(
                    workspace_id=workspace_id,
                    cache=cache,
                )
            else:
                self._document_search_indexer.ensure_workspace_index(
                    workspace_id=workspace_id,
                    cache=cache,
                )
        except DocumentSearchIndexError as exc:
            logger.warning(
                "Unable to refresh document search index for workspace %s: %s",
                workspace_id,
                exc,
            )

    def _clear_workspace_search_index(self, workspace_id: str) -> None:
        if self._document_search_indexer is None:
            return
        try:
            self._document_search_indexer.delete_workspace_index(workspace_id)
        except DocumentSearchIndexError as exc:
            logger.warning(
                "Unable to clear document search index for workspace %s: %s",
                workspace_id,
                exc,
            )

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

    def _build_optional_workspace_document_cache(
        self,
        resolved_workspace_root: Path,
    ) -> tuple[Path | None, DocumentCache | None]:
        declared_entry = resolved_workspace_root / "AGENTS.md"
        if not declared_entry.exists() and not declared_entry.is_symlink():
            return None, None

        resolved_entry = declared_entry.resolve()
        try:
            resolved_entry.relative_to(resolved_workspace_root)
        except ValueError as exc:
            raise ProjectRegistryError("工作空间文档入口不能越出工作空间") from exc
        if not resolved_entry.is_file():
            raise ProjectRegistryError("工作空间文档入口 AGENTS.md 不可读取")
        try:
            cache = build_workspace_document_cache(resolved_entry)
        except DocumentTreeError as exc:
            raise ProjectRegistryError(str(exc)) from exc
        return resolved_entry, cache

    def validate_workspace_document_entry(self, root_path: str) -> None:
        resolved_root = self._resolve_cwd(root_path)
        self._build_optional_workspace_document_cache(resolved_root)

    @staticmethod
    def _project_key(agents_path: str) -> str:
        normalized_path = str(Path(agents_path).expanduser())
        return hashlib.sha256(normalized_path.encode()).hexdigest()

    @staticmethod
    def _workspace_key(root_path: str) -> str:
        normalized_path = str(Path(root_path).expanduser())
        return hashlib.sha256(normalized_path.encode()).hexdigest()

    @classmethod
    def _snapshot(cls, project: ProjectState) -> ProjectSnapshot:
        if not project.workspace_enabled:
            raise ProjectRegistryError("工作空间已停用")
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
            workspace_id=project.workspace_id,
            workspace_name=project.workspace_name,
            relative_path=project.relative_path,
            project_kind=project.project_kind,
        )

    @staticmethod
    def _summary(project: ProjectState) -> ProjectSummary:
        return ProjectSummary(
            id=project.id,
            name=project.name,
            project_type=project.project_type,
            project_kind=project.project_kind,
            agents_path=project.agents_path,
            node_count=len(project.cache.documents) if project.cache else 0,
            refreshed_at=project.refreshed_at,
            error=project.error,
            workspace_id=project.workspace_id,
            workspace_name=project.workspace_name,
            workspace_enabled=project.workspace_enabled,
            relative_path=project.relative_path,
        )

    def _workspace_snapshot(
        self,
        workspace: WorkspaceState,
        *,
        active_project: ProjectState | None = None,
    ) -> WorkspaceSnapshot:
        if not workspace.enabled:
            raise ProjectRegistryError("工作空间已停用")
        if workspace.document_error:
            raise ProjectRegistryError(
                f"工作空间映射不可用：工作空间文档入口：{workspace.document_error}"
            )

        project_states = sorted(
            (
                project
                for project in self._projects.values()
                if project.workspace_id == workspace.id
            ),
            key=lambda item: (
                item.relative_path != ".",
                item.relative_path.casefold(),
                item.id,
            ),
        )
        unavailable = [project for project in project_states if project.cache is None]
        if unavailable:
            first = unavailable[0]
            detail = first.error or "项目尚未刷新映射"
            raise ProjectRegistryError(f"工作空间映射不可用：{first.name}：{detail}")

        project_snapshots = tuple(self._snapshot(project) for project in project_states)
        cache = self._build_workspace_cache(workspace, project_snapshots)
        active_snapshot = (
            next(
                (item for item in project_snapshots if item.id == active_project.id),
                None,
            )
            if active_project is not None
            else None
        )
        return WorkspaceSnapshot(
            id=workspace.id,
            workspace_key=self._workspace_key(workspace.root_path),
            name=workspace.name,
            workspace_type=workspace.workspace_type,
            root_path=workspace.root_path,
            resolved_root_path=workspace.resolved_root_path,
            enabled=workspace.enabled,
            cache=cache,
            document_cache=workspace.document_cache,
            projects=project_snapshots,
            active_project=active_snapshot,
        )

    @staticmethod
    def _build_workspace_cache(
        workspace: WorkspaceState,
        projects: tuple[ProjectSnapshot, ...],
    ) -> DocumentCache:
        workspace_document_ids = (
            set(workspace.document_cache.documents)
            if workspace.document_cache is not None
            else set()
        )
        documents: dict[str, CachedDocument]
        if workspace.document_cache is not None:
            documents = dict(workspace.document_cache.documents)
            root = CachedTreeNode(
                id=workspace.document_cache.root.id,
                description=workspace.document_cache.root.description,
                path=workspace.document_cache.root.path,
                relative_path=workspace.document_cache.root.relative_path,
                title=workspace.document_cache.root.title,
                summary=workspace.document_cache.root.summary,
                error=workspace.document_cache.root.error,
                children=list(workspace.document_cache.root.children),
            )
        else:
            root_id = hashlib.sha256(f"workspace:{workspace.id}".encode()).hexdigest()[:20]
            project_lines = [
                f"- `{project.relative_path}`：{project.name}（{project.project_kind}）"
                for project in projects
            ]
            content = "\n".join(
                [
                    f"# {workspace.name}",
                    "",
                    "这是工作空间级上下文入口，下面汇总了工作空间内配置的项目文档树。",
                    "",
                    "## 项目",
                    "",
                    *(project_lines or ["- 暂无项目"]),
                    "",
                ]
            )
            documents = {
                root_id: CachedDocument(
                    id=root_id,
                    description="工作空间文档入口",
                    path=str(workspace.resolved_root_path),
                    relative_path=None,
                    content=content,
                    title=workspace.name,
                    summary="工作空间内全部项目的文档入口。",
                )
            }
            root = CachedTreeNode(
                id=root_id,
                description="工作空间文档入口",
                path=str(workspace.resolved_root_path),
                relative_path=None,
                title=workspace.name,
                summary="工作空间内全部项目的文档入口。",
            )

        owner_by_document_id: dict[str, str] = {}
        for project in projects:
            for document_id, document in project.cache.documents.items():
                if document_id in workspace_document_ids:
                    continue
                document_path = Path(document.path).resolve()
                candidates = [
                    candidate
                    for candidate in projects
                    if (
                        document_path == candidate.cache.project_root
                        or candidate.cache.project_root in document_path.parents
                    )
                ]
                owner = max(
                    candidates or [project],
                    key=lambda item: len(item.cache.project_root.parts),
                )
                owner_by_document_id[document_id] = owner.id

        def owned_tree(
            node: CachedTreeNode,
            *,
            project_id: str,
        ) -> CachedTreeNode | None:
            if node.id in workspace_document_ids:
                return None
            if owner_by_document_id.get(node.id, project_id) != project_id:
                return None
            return CachedTreeNode(
                id=node.id,
                description=node.description,
                path=node.path,
                relative_path=node.relative_path,
                title=node.title,
                summary=node.summary,
                error=node.error,
                children=[
                    owned
                    for child in node.children
                    if (owned := owned_tree(child, project_id=project_id)) is not None
                ],
            )

        version_hasher = hashlib.sha256()
        version_hasher.update(b"workspace-document-cache-v2\0")
        version_hasher.update(workspace.id.encode())
        if workspace.document_cache is not None:
            version_hasher.update(workspace.document_cache.version.encode())
        version_hasher.update(b"\0")
        for project in projects:
            version_hasher.update(project.id.encode())
            version_hasher.update(b"\0")
            version_hasher.update(project.cache.version.encode())
            version_hasher.update(b"\0")
            if workspace.document_cache is None:
                project_root = owned_tree(project.cache.root, project_id=project.id)
                if project_root is not None:
                    root.children.append(project_root)
            for document_id, document in project.cache.documents.items():
                if owner_by_document_id.get(document_id) == project.id:
                    documents[document_id] = document

        return DocumentCache(
            root=root,
            documents=documents,
            project_root=workspace.resolved_root_path,
            version=version_hasher.hexdigest(),
        )

    def list_projects(self) -> list[ProjectSummary]:
        with self._lock:
            return [self._summary(project) for project in self._projects.values()]

    def list_workspace_projects(self, workspace_id: str) -> list[ProjectSummary]:
        with self._lock:
            projects = [
                self._summary(project)
                for project in self._projects.values()
                if project.workspace_id == workspace_id
            ]
        return sorted(
            projects,
            key=lambda item: (
                item.relative_path != ".",
                item.relative_path.casefold(),
                item.id,
            ),
        )

    def get_project_summary(self, project_id: str) -> ProjectSummary:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            return self._summary(project)

    def register_workspace(self, workspace: WorkspaceRecord) -> None:
        resolved_root = self._resolve_cwd(workspace.root_path)
        with self._lock:
            current = self._workspaces.get(workspace.id)
            should_load_document = (
                current is None
                or current.resolved_root_path != resolved_root
                or not current.document_entry_checked
            )
        document_entry_path: Path | None = None
        document_cache: DocumentCache | None = None
        document_error: str | None = None
        if should_load_document:
            try:
                document_entry_path, document_cache = self._build_optional_workspace_document_cache(
                    resolved_root
                )
            except ProjectRegistryError as exc:
                document_error = str(exc)
            if document_cache is not None:
                self._ensure_workspace_search_index(workspace.id, document_cache)
            elif document_error is None:
                self._clear_workspace_search_index(workspace.id)

        with self._lock:
            state = self._upsert_workspace_state_unlocked(
                workspace,
                resolved_root=resolved_root,
            )
            if should_load_document:
                state.document_entry_path = document_entry_path
                state.document_cache = document_cache
                state.document_error = document_error
                state.document_entry_checked = True
                state.error = document_error

    def _upsert_workspace_state_unlocked(
        self,
        workspace: WorkspaceRecord,
        *,
        resolved_root: Path | None = None,
    ) -> WorkspaceState:
        current = self._workspaces.get(workspace.id)
        state = WorkspaceState(
            id=workspace.id,
            name=workspace.name,
            workspace_type=workspace.workspace_type,
            root_path=workspace.root_path,
            resolved_root_path=resolved_root or self._resolve_cwd(workspace.root_path),
            enabled=workspace.enabled,
            document_entry_path=(current.document_entry_path if current is not None else None),
            document_cache=current.document_cache if current is not None else None,
            document_error=current.document_error if current is not None else None,
            document_entry_checked=(
                current.document_entry_checked if current is not None else False
            ),
            refreshed_at=current.refreshed_at if current is not None else None,
            error=current.error if current is not None else None,
        )
        self._workspaces[workspace.id] = state
        return state

    def list_workspace_ids(self) -> list[str]:
        with self._lock:
            return list(self._workspaces)

    def get_workspace_key(self, workspace_id: str) -> str:
        with self._lock:
            workspace = self._workspaces.get(workspace_id)
            if workspace is None:
                raise ProjectRegistryError("工作空间不存在")
            return self._workspace_key(workspace.root_path)

    def _resolve_workspace_project(
        self,
        workspace: WorkspaceRecord,
        relative_path: str,
    ) -> tuple[str, str, Path]:
        try:
            normalized_relative = normalize_project_relative_path(relative_path)
            agents_path = derive_agents_path(workspace.root_path, normalized_relative)
        except WorkspacePathError as exc:
            raise ProjectRegistryError(str(exc)) from exc
        resolved_agents_path = self._resolve_agents_path(agents_path)
        resolved_workspace_root = self._resolve_cwd(workspace.root_path)
        try:
            resolved_agents_path.parent.relative_to(resolved_workspace_root)
        except ValueError as exc:
            raise ProjectRegistryError("项目路径不能越出工作空间") from exc
        return normalized_relative, agents_path, resolved_agents_path

    def add_workspace_project(
        self,
        workspace: WorkspaceRecord,
        *,
        name: str,
        relative_path: str,
        project_kind: str = "backend",
    ) -> ProjectSummary:
        normalized_name = name.strip()
        normalized_kind = project_kind.strip().lower()
        if not normalized_name:
            raise ProjectRegistryError("项目名称不能为空")
        if normalized_kind not in {"frontend", "backend"}:
            raise ProjectRegistryError("项目类型必须是 frontend 或 backend")
        normalized_relative, agents_path, resolved_path = self._resolve_workspace_project(
            workspace,
            relative_path,
        )
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

        if self._project_repository is not None:
            try:
                self._project_repository.create_project(
                    project_id=project_id,
                    name=normalized_name,
                    project_type=workspace.workspace_type,
                    agents_path=agents_path,
                    workspace_id=workspace.id,
                    relative_path=normalized_relative,
                    project_kind=normalized_kind,
                )
            except ProjectRepositoryError as exc:
                raise ProjectRegistryError(str(exc)) from exc

        self._ensure_search_index(project_id, new_cache, force=True)
        with self._lock:
            project = ProjectState(
                id=project_id,
                name=normalized_name,
                project_type=workspace.workspace_type,
                agents_path=agents_path,
                resolved_agents_path=resolved_path,
                workspace_id=workspace.id,
                workspace_name=workspace.name,
                workspace_root_path=workspace.root_path,
                workspace_enabled=workspace.enabled,
                relative_path=normalized_relative,
                project_kind=normalized_kind,
                cache=new_cache,
                refreshed_at=datetime.now(UTC),
            )
            self._projects[project_id] = project
            self._upsert_workspace_state_unlocked(workspace)
            return self._summary(project)

    def update_workspace_project(
        self,
        workspace: WorkspaceRecord,
        project_id: str,
        *,
        name: str,
        relative_path: str,
        project_kind: str | None,
    ) -> ProjectSummary:
        normalized_name = name.strip()
        if not normalized_name:
            raise ProjectRegistryError("项目名称不能为空")
        normalized_relative, agents_path, resolved_path = self._resolve_workspace_project(
            workspace,
            relative_path,
        )
        try:
            new_cache = build_document_cache(resolved_path)
        except DocumentTreeError as exc:
            raise ProjectRegistryError(str(exc)) from exc
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.workspace_id != workspace.id:
                raise ProjectRegistryError("项目不存在")
            normalized_kind = (
                project.project_kind if project_kind is None else project_kind.strip().lower()
            )
            if normalized_kind not in {"frontend", "backend"}:
                raise ProjectRegistryError("项目类型必须是 frontend 或 backend")
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
                    workspace_id=workspace.id,
                    relative_path=normalized_relative,
                    project_kind=normalized_kind,
                )
            except ProjectRepositoryError as exc:
                raise ProjectRegistryError(str(exc)) from exc

        self._ensure_search_index(project_id, new_cache, force=True)
        with self._lock:
            project.name = normalized_name
            project.project_type = workspace.workspace_type
            project.agents_path = agents_path
            project.resolved_agents_path = resolved_path
            project.workspace_name = workspace.name
            project.workspace_root_path = workspace.root_path
            project.workspace_enabled = workspace.enabled
            project.relative_path = normalized_relative
            project.project_kind = normalized_kind
            project.cache = new_cache
            project.refreshed_at = datetime.now(UTC)
            project.error = None
            self._upsert_workspace_state_unlocked(workspace)
            return self._summary(project)

    def validate_workspace_root(self, workspace_id: str, root_path: str) -> None:
        self.validate_workspace_document_entry(root_path)
        with self._lock:
            projects = [
                project
                for project in self._projects.values()
                if project.workspace_id == workspace_id
            ]
        for project in projects:
            candidate_workspace = WorkspaceRecord(
                id=workspace_id,
                name=project.workspace_name or "",
                workspace_type=project.project_type,
                root_path=root_path,
                enabled=project.workspace_enabled,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            _, _, resolved_path = self._resolve_workspace_project(
                candidate_workspace,
                project.relative_path,
            )
            try:
                build_document_cache(resolved_path)
            except DocumentTreeError as exc:
                raise ProjectRegistryError(str(exc)) from exc

    def apply_workspace_record(self, workspace: WorkspaceRecord) -> None:
        with self._lock:
            projects = [
                project
                for project in self._projects.values()
                if project.workspace_id == workspace.id
            ]
        prepared: dict[str, tuple[str, str, Path, DocumentCache]] = {}
        failures: dict[str, str] = {}
        resolved_workspace_root = self._resolve_cwd(workspace.root_path)
        workspace_document_path: Path | None = None
        workspace_document_cache: DocumentCache | None = None
        workspace_document_error: str | None = None
        try:
            workspace_document_path, workspace_document_cache = (
                self._build_optional_workspace_document_cache(
                    resolved_workspace_root,
                )
            )
        except ProjectRegistryError as exc:
            workspace_document_error = str(exc)
            failures["__workspace_document__"] = workspace_document_error

        for project in projects:
            try:
                relative_path, agents_path, resolved_path = self._resolve_workspace_project(
                    workspace,
                    project.relative_path,
                )
                cache = build_document_cache(resolved_path)
                prepared[project.id] = (
                    relative_path,
                    agents_path,
                    resolved_path,
                    cache,
                )
            except (ProjectRegistryError, DocumentTreeError) as exc:
                failures[project.id] = str(exc)

        if not failures:
            if workspace_document_cache is not None:
                self._ensure_workspace_search_index(
                    workspace.id,
                    workspace_document_cache,
                    force=True,
                )
            else:
                self._clear_workspace_search_index(workspace.id)
            for project in projects:
                self._ensure_search_index(
                    project.id,
                    prepared[project.id][3],
                    force=True,
                )

        now = datetime.now(UTC)
        with self._lock:
            workspace_state = self._upsert_workspace_state_unlocked(
                workspace,
                resolved_root=resolved_workspace_root,
            )
            workspace_state.error = next(iter(failures.values()), None)
            if not failures:
                workspace_state.document_entry_path = workspace_document_path
                workspace_state.document_cache = workspace_document_cache
                workspace_state.document_error = None
                workspace_state.document_entry_checked = True
                workspace_state.refreshed_at = now
            elif workspace_document_error is not None:
                workspace_state.document_error = workspace_document_error

            for project in projects:
                project.workspace_name = workspace.name
                project.project_type = workspace.workspace_type
                project.workspace_root_path = workspace.root_path
                project.workspace_enabled = workspace.enabled
                if failures:
                    project.error = failures.get(project.id)
                    continue
                relative_path, agents_path, resolved_path, cache = prepared[project.id]
                project.relative_path = relative_path
                project.agents_path = agents_path
                project.resolved_agents_path = resolved_path
                project.cache = cache
                project.refreshed_at = now
                project.error = None

    def remove_workspace_projects(self, workspace_id: str) -> None:
        self._clear_workspace_search_index(workspace_id)
        with self._lock:
            self._projects = {
                project_id: project
                for project_id, project in self._projects.items()
                if project.workspace_id != workspace_id
            }
            self._workspaces.pop(workspace_id, None)

    def load_persisted_projects(self) -> list[ProjectSummary]:
        if self._project_repository is None:
            return self.list_projects()
        try:
            records = self._project_repository.list_projects()
        except ProjectRepositoryError as exc:
            raise ProjectRegistryError(str(exc)) from exc

        restored: dict[str, ProjectState] = {}
        restored_workspaces: dict[str, WorkspaceState] = {}
        for record in records:
            cache: DocumentCache | None = None
            refreshed_at: datetime | None = None
            error: str | None = None
            resolved_path = Path(record.agents_path).expanduser()
            try:
                resolved_path = self._map_agents_path(record.agents_path)
                if not resolved_path.is_file():
                    raise ProjectRegistryError(f"找不到入口文件：{record.agents_path}")
                cache = build_document_cache(resolved_path)
                self._ensure_search_index(record.id, cache)
                refreshed_at = datetime.now(UTC)
            except (ProjectRegistryError, DocumentTreeError) as exc:
                error = str(exc)

            restored[record.id] = ProjectState(
                id=record.id,
                name=record.name,
                project_type=record.project_type,
                agents_path=record.agents_path,
                resolved_agents_path=resolved_path,
                workspace_id=getattr(record, "workspace_id", None),
                workspace_name=getattr(record, "workspace_name", None),
                workspace_root_path=getattr(record, "workspace_root_path", None),
                workspace_enabled=getattr(record, "workspace_enabled", True),
                relative_path=getattr(record, "relative_path", "."),
                project_kind=getattr(record, "project_kind", "backend"),
                cache=cache,
                refreshed_at=refreshed_at,
                error=error,
            )
            workspace_id = getattr(record, "workspace_id", None)
            workspace_root_path = getattr(record, "workspace_root_path", None)
            if workspace_id is not None and workspace_root_path:
                restored_workspaces.setdefault(
                    workspace_id,
                    WorkspaceState(
                        id=workspace_id,
                        name=getattr(record, "workspace_name", None) or record.name,
                        workspace_type=(
                            getattr(record, "workspace_type", None)
                            or getattr(record, "project_type", DEFAULT_PROJECT_TYPE)
                        ),
                        root_path=workspace_root_path,
                        resolved_root_path=self._resolve_cwd(workspace_root_path),
                        enabled=getattr(record, "workspace_enabled", True),
                        refreshed_at=refreshed_at,
                        error=error,
                    ),
                )

        with self._lock:
            self._projects = restored
            self._workspaces.update(restored_workspaces)
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
        project_type: str = DEFAULT_PROJECT_TYPE,
        project_kind: str = "backend",
        agents_path: str,
        persist: bool = True,
    ) -> ProjectSummary:
        normalized_name = name.strip()
        normalized_type = project_type.strip()
        normalized_kind = project_kind.strip().lower()
        normalized_path = agents_path.strip()
        if not normalized_name:
            raise ProjectRegistryError("项目名称不能为空")
        if not normalized_type:
            raise ProjectRegistryError("项目类型不能为空")
        if normalized_kind not in {"frontend", "backend"}:
            raise ProjectRegistryError("项目类型必须是 frontend 或 backend")

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
                    project_type=normalized_type,
                    agents_path=normalized_path,
                    project_kind=normalized_kind,
                )
            except ProjectRepositoryError as exc:
                raise ProjectRegistryError(str(exc)) from exc

        persisted_record = None
        if persist and self._project_repository is not None:
            try:
                persisted_record = self._project_repository.get_project(project_id)
            except (AttributeError, ProjectRepositoryError):
                persisted_record = None

        resolved_workspace_id = (
            persisted_record.workspace_id if persisted_record is not None else project_id
        )
        resolved_workspace_name = (
            persisted_record.workspace_name if persisted_record is not None else normalized_name
        )
        resolved_workspace_root = (
            persisted_record.workspace_root_path
            if persisted_record is not None
            else str(Path(normalized_path).expanduser().parent)
        )
        resolved_workspace_document = build_workspace_document_cache(resolved_path)
        self._ensure_search_index(project_id, new_cache, force=True)
        self._ensure_workspace_search_index(
            resolved_workspace_id,
            resolved_workspace_document,
            force=True,
        )
        with self._lock:
            project = ProjectState(
                id=project_id,
                name=normalized_name,
                project_type=normalized_type,
                agents_path=normalized_path,
                resolved_agents_path=resolved_path,
                workspace_id=resolved_workspace_id,
                workspace_name=resolved_workspace_name,
                workspace_root_path=resolved_workspace_root,
                workspace_enabled=(
                    persisted_record.workspace_enabled if persisted_record is not None else True
                ),
                relative_path=(
                    persisted_record.relative_path if persisted_record is not None else "."
                ),
                project_kind=getattr(persisted_record, "project_kind", normalized_kind),
                cache=new_cache,
                refreshed_at=datetime.now(UTC),
            )
            self._projects[project.id] = project
            self._workspaces[resolved_workspace_id] = WorkspaceState(
                id=resolved_workspace_id,
                name=resolved_workspace_name or normalized_name,
                workspace_type=project.project_type,
                root_path=resolved_workspace_root,
                resolved_root_path=self._resolve_cwd(resolved_workspace_root),
                enabled=project.workspace_enabled,
                document_entry_path=resolved_path,
                document_cache=resolved_workspace_document,
                document_entry_checked=True,
                refreshed_at=project.refreshed_at,
            )
            return self._summary(project)

    def update_project(
        self,
        project_id: str,
        *,
        name: str,
        project_type: str | None = None,
        project_kind: str | None = None,
        agents_path: str,
    ) -> ProjectSummary:
        normalized_name = name.strip()
        normalized_type = project_type.strip() if project_type is not None else None
        normalized_path = agents_path.strip()
        if not normalized_name:
            raise ProjectRegistryError("项目名称不能为空")
        if normalized_type == "":
            raise ProjectRegistryError("项目类型不能为空")
        with self._lock:
            current_project = self._projects.get(project_id)
            if current_project is None:
                raise ProjectRegistryError("项目不存在")
            normalized_kind = (
                current_project.project_kind
                if project_kind is None
                else project_kind.strip().lower()
            )
            if normalized_kind not in {"frontend", "backend"}:
                raise ProjectRegistryError("项目类型必须是 frontend 或 backend")
            if current_project.workspace_id is not None and current_project.relative_path != ".":
                raise ProjectRegistryError("工作空间子项目请使用工作空间项目接口更新")
            if (
                current_project.workspace_id is not None
                and sum(
                    item.workspace_id == current_project.workspace_id
                    for item in self._projects.values()
                )
                > 1
            ):
                raise ProjectRegistryError("包含多个项目的工作空间请使用工作空间接口更新")
        resolved_path = self._resolve_agents_path(normalized_path)
        try:
            new_cache = build_document_cache(resolved_path)
        except DocumentTreeError as exc:
            raise ProjectRegistryError(str(exc)) from exc

        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            resolved_type = normalized_type or project.project_type
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
                    project_type=resolved_type,
                    project_kind=normalized_kind,
                    agents_path=normalized_path,
                )
            except ProjectRepositoryError as exc:
                raise ProjectRegistryError(str(exc)) from exc

        persisted_record = None
        if self._project_repository is not None:
            try:
                persisted_record = self._project_repository.get_project(project_id)
            except (AttributeError, ProjectRepositoryError):
                persisted_record = None

        self._ensure_search_index(project_id, new_cache, force=True)
        with self._lock:
            project.name = normalized_name
            project.project_type = (
                persisted_record.project_type if persisted_record is not None else resolved_type
            )
            project.project_kind = getattr(
                persisted_record,
                "project_kind",
                normalized_kind,
            )
            project.agents_path = (
                persisted_record.agents_path if persisted_record is not None else normalized_path
            )
            project.resolved_agents_path = resolved_path
            if persisted_record is not None:
                project.workspace_id = persisted_record.workspace_id
                project.workspace_name = persisted_record.workspace_name
                project.workspace_root_path = persisted_record.workspace_root_path
                project.workspace_enabled = persisted_record.workspace_enabled
                project.relative_path = persisted_record.relative_path
            project.cache = new_cache
            project.refreshed_at = datetime.now(UTC)
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
            resolved_path = project.resolved_agents_path

        try:
            resolved_path = self._resolve_agents_path(project.agents_path)
            new_cache = build_document_cache(resolved_path)
        except (ProjectRegistryError, DocumentTreeError) as exc:
            with self._lock:
                project.error = str(exc)
            raise ProjectRegistryError(str(exc)) from exc

        self._ensure_search_index(project_id, new_cache, force=True)
        with self._lock:
            project.cache = new_cache
            project.resolved_agents_path = resolved_path
            project.refreshed_at = datetime.now(UTC)
            project.error = None
            return self._summary(project)

    def refresh_workspace(self, workspace_id: str) -> WorkspaceSnapshot:
        with self._lock:
            workspace = self._workspaces.get(workspace_id)
            if workspace is None:
                raise ProjectRegistryError("工作空间不存在")
            if not workspace.enabled:
                raise ProjectRegistryError("工作空间已停用")
            projects = [
                project
                for project in self._projects.values()
                if project.workspace_id == workspace_id
            ]

        try:
            workspace_document_path, workspace_document_cache = (
                self._build_optional_workspace_document_cache(
                    workspace.resolved_root_path,
                )
            )
        except ProjectRegistryError as exc:
            with self._lock:
                current_workspace = self._workspaces.get(workspace_id)
                if current_workspace is not None:
                    current_workspace.error = str(exc)
                    current_workspace.document_error = str(exc)
            raise ProjectRegistryError(
                f"工作空间刷新失败，已保留上一版映射：工作空间文档入口：{exc}"
            ) from exc

        prepared: dict[str, tuple[Path, DocumentCache]] = {}
        for project in projects:
            try:
                resolved_path = self._resolve_agents_path(project.agents_path)
                prepared[project.id] = (
                    resolved_path,
                    build_document_cache(resolved_path),
                )
            except (ProjectRegistryError, DocumentTreeError) as exc:
                with self._lock:
                    current_workspace = self._workspaces.get(workspace_id)
                    if current_workspace is not None:
                        current_workspace.error = str(exc)
                    current_project = self._projects.get(project.id)
                    if current_project is not None:
                        current_project.error = str(exc)
                raise ProjectRegistryError(
                    f"工作空间刷新失败，已保留上一版映射：{project.name}：{exc}"
                ) from exc

        if workspace_document_cache is not None:
            self._ensure_workspace_search_index(
                workspace_id,
                workspace_document_cache,
                force=True,
            )
        else:
            self._clear_workspace_search_index(workspace_id)
        for project in projects:
            self._ensure_search_index(
                project.id,
                prepared[project.id][1],
                force=True,
            )

        now = datetime.now(UTC)
        with self._lock:
            current_workspace = self._workspaces.get(workspace_id)
            if current_workspace is None:
                raise ProjectRegistryError("工作空间不存在")
            current_workspace.document_entry_path = workspace_document_path
            current_workspace.document_cache = workspace_document_cache
            current_workspace.document_error = None
            current_workspace.document_entry_checked = True
            for project in projects:
                current_project = self._projects.get(project.id)
                if current_project is None:
                    raise ProjectRegistryError("工作空间项目配置在刷新期间发生变化")
                resolved_path, cache = prepared[project.id]
                current_project.resolved_agents_path = resolved_path
                current_project.cache = cache
                current_project.refreshed_at = now
                current_project.error = None
            current_workspace.refreshed_at = now
            current_workspace.error = None
            return self._workspace_snapshot(current_workspace)

    def get_tree(self, project_id: str) -> DocumentTreeNode:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            if project.cache is None:
                if project.error:
                    raise ProjectRegistryError(f"项目映射不可用：{project.error}")
                raise ProjectRegistryError("项目尚未刷新映射")
            return project.cache.root.to_schema()

    def get_workspace_tree(self, workspace_id: str) -> DocumentTreeNode:
        return self.get_workspace_snapshot(workspace_id).cache.root.to_schema()

    def get_snapshot(self, project_id: str) -> ProjectSnapshot:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            return self._snapshot(project)

    def get_workspace_snapshot(self, workspace_id: str) -> WorkspaceSnapshot:
        with self._lock:
            workspace = self._workspaces.get(workspace_id)
            if workspace is None:
                raise ProjectRegistryError("工作空间不存在")
            return self._workspace_snapshot(workspace)

    def get_project_key(self, project_id: str) -> str:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            return self._project_key(project.agents_path)

    def find_project_id_by_key(self, project_key: str) -> str | None:
        with self._lock:
            for project in self._projects.values():
                if self._project_key(project.agents_path) == project_key:
                    return project.id
        return None

    def find_project_for_cwd(self, cwd: str) -> ProjectSnapshot:
        resolved_cwd = self._resolve_cwd(cwd)
        with self._lock:
            candidates = [
                project
                for project in self._projects.values()
                if (
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
            # Ownership is selected before availability is checked. A disabled or
            # broken nested project must not fall back to an enabled parent project,
            # because the parent can have different document and database grants.
            return self._snapshot(project)

    def find_workspace_for_cwd(self, cwd: str) -> WorkspaceSnapshot:
        resolved_cwd = self._resolve_cwd(cwd)
        with self._lock:
            candidates = [
                workspace
                for workspace in self._workspaces.values()
                if (
                    resolved_cwd == workspace.resolved_root_path
                    or workspace.resolved_root_path in resolved_cwd.parents
                )
            ]
            if not candidates:
                raise ProjectRegistryError("cwd 没有匹配已注册工作空间")
            workspace = max(
                candidates,
                key=lambda item: len(item.resolved_root_path.parts),
            )
            project_candidates = [
                project
                for project in self._projects.values()
                if (
                    project.workspace_id == workspace.id
                    and (
                        resolved_cwd == project.resolved_agents_path.parent
                        or project.resolved_agents_path.parent in resolved_cwd.parents
                    )
                )
            ]
            active_project = (
                max(
                    project_candidates,
                    key=lambda item: len(item.resolved_agents_path.parent.parts),
                )
                if project_candidates
                else None
            )
            return self._workspace_snapshot(
                workspace,
                active_project=active_project,
            )

    def get_snapshot_by_project_key(self, project_key: str) -> ProjectSnapshot:
        with self._lock:
            for project in self._projects.values():
                if self._project_key(project.agents_path) == project_key:
                    return self._snapshot(project)
        raise ProjectRegistryError("任务绑定的项目不存在")

    def get_snapshot_for_task(
        self,
        *,
        project_id: str | None,
        project_key: str,
    ) -> ProjectSnapshot:
        if project_id is not None:
            return self.get_snapshot(project_id)
        return self.get_snapshot_by_project_key(project_key)

    def get_workspace_snapshot_for_task(
        self,
        *,
        workspace_id: str | None,
        workspace_key: str | None,
    ) -> WorkspaceSnapshot:
        if workspace_id is not None:
            snapshot = self.get_workspace_snapshot(workspace_id)
            if workspace_key and snapshot.workspace_key != workspace_key:
                raise ProjectRegistryError("任务绑定的工作空间已发生变化")
            return snapshot
        if workspace_key:
            with self._lock:
                for workspace in self._workspaces.values():
                    if self._workspace_key(workspace.root_path) == workspace_key:
                        return self._workspace_snapshot(workspace)
        raise ProjectRegistryError("任务绑定的工作空间不存在")

    @staticmethod
    def workspace_document_owner(
        workspace: WorkspaceSnapshot,
        document_id: str,
    ) -> ProjectSnapshot | None:
        if (
            workspace.document_cache is not None
            and document_id in workspace.document_cache.documents
        ):
            return None
        candidates = [
            project for project in workspace.projects if document_id in project.cache.documents
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: len(item.cache.project_root.parts))

    def get_document(self, project_id: str, document_id: str) -> DocumentDetail:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectRegistryError("项目不存在")
            if project.cache is None:
                if project.error:
                    raise ProjectRegistryError(f"项目映射不可用：{project.error}")
                raise ProjectRegistryError("项目尚未刷新映射")

            document = project.cache.documents.get(document_id)
            if document is None:
                raise ProjectRegistryError("文档不在当前内存映射中")
            return document.to_detail()

    def get_workspace_document(
        self,
        workspace_id: str,
        document_id: str,
    ) -> DocumentDetail:
        snapshot = self.get_workspace_snapshot(workspace_id)
        document = snapshot.cache.documents.get(document_id)
        if document is None:
            raise ProjectRegistryError("文档不在当前工作空间映射中")
        return document.to_detail()
