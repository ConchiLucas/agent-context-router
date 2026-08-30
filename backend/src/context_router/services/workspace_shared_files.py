from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

from context_router.config import Settings
from context_router.repositories.project_repository import ProjectRepositoryError, ProjectStore
from context_router.repositories.workspace_repository import (
    WorkspaceRepositoryError,
    WorkspaceStore,
)
from context_router.repositories.workspace_shared_file_repository import (
    WorkspaceSharedFile,
    WorkspaceSharedFileRepositoryError,
    WorkspaceSharedFileStore,
)
from context_router.schemas.workspace_shared_files import WorkspaceSharedFilesResult
from context_router.services.local_workspace_mapping import (
    LocalWorkspaceMappingError,
    LocalWorkspaceMappingService,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError
from context_router.services.runtime_paths import RuntimePathError, RuntimePathResolver
from context_router.services.workspace_deploy_sync import (
    CONFIG_ROOT,
    SENSITIVE_FILENAMES,
    SENSITIVE_SUFFIXES,
    WorkspaceDeploySyncError,
    scan_workspace_deploy_bundle,
)


class WorkspaceSharedFilesError(ValueError):
    pass


class WorkspaceSharedFilesService:
    def __init__(
        self,
        *,
        settings: Settings,
        local_mapping: LocalWorkspaceMappingService,
        workspace_repository: WorkspaceStore,
        project_repository: ProjectStore,
        shared_file_repository: WorkspaceSharedFileStore,
        registry: ProjectRegistry,
    ) -> None:
        self._settings = settings
        self._paths = RuntimePathResolver(settings)
        self._mapping = local_mapping
        self._workspaces = workspace_repository
        self._projects = project_repository
        self._files = shared_file_repository
        self._registry = registry

    def publish(self, workspace_id: str) -> WorkspaceSharedFilesResult:
        root = self._main_root(workspace_id)
        try:
            projects = self._projects.list_projects(workspace_id=workspace_id)
            bundle = scan_workspace_deploy_bundle(root, projects)
            files = self._scan_documents(root)
            files.extend(self._scan_deploy(root, projects))
            self._files.replace_all(workspace_id, files, bundle)
        except (
            ProjectRepositoryError,
            WorkspaceDeploySyncError,
            WorkspaceSharedFileRepositoryError,
        ) as exc:
            raise WorkspaceSharedFilesError(str(exc)) from exc
        return self._result(workspace_id, root, files, "publish")

    def restore(self, workspace_id: str) -> WorkspaceSharedFilesResult:
        root = self._main_root(workspace_id)
        try:
            files = self._files.list_files(workspace_id)
        except WorkspaceSharedFileRepositoryError as exc:
            raise WorkspaceSharedFilesError(str(exc)) from exc
        if not files:
            raise WorkspaceSharedFilesError("数据库中还没有可恢复的文档与部署文件")
        destinations = [(item, self._destination(root, item)) for item in files]
        document_files = [item for item in files if item.file_type == "document"]
        deploy_files = [item for item in files if item.file_type == "deploy"]
        if not document_files or not deploy_files:
            raise WorkspaceSharedFilesError("数据库共享文件不完整，不能覆盖主目录")

        docs_root = root / "docs"
        deploy_roots = {
            self._deploy_root(root, PurePosixPath(item.relative_path)) for item in deploy_files
        }
        self._remove_tree(root, docs_root)
        for deploy_root in sorted(deploy_roots, key=lambda item: len(item.parts), reverse=True):
            self._remove_tree(root, deploy_root)
        for item, destination in destinations:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(item.content, encoding="utf-8")
            destination.chmod(0o755 if item.executable else 0o644)
        try:
            self._registry.refresh_workspace(workspace_id)
        except ProjectRegistryError as exc:
            raise WorkspaceSharedFilesError(f"文件已覆盖，但文档映射刷新失败：{exc}") from exc
        return self._result(workspace_id, root, files, "restore")

    def _main_root(self, workspace_id: str) -> Path:
        try:
            record = self._workspaces.get_workspace(workspace_id)
            host_path = self._mapping.main_host_path(workspace_id, record.root_path)
        except (WorkspaceRepositoryError, LocalWorkspaceMappingError) as exc:
            raise WorkspaceSharedFilesError(str(exc)) from exc
        try:
            resolved = self._paths.map_host_path(host_path)
        except RuntimePathError as exc:
            raise WorkspaceSharedFilesError(str(exc)) from exc
        if not resolved.is_dir():
            raise WorkspaceSharedFilesError(f"找不到主映射目录：{host_path}")
        return resolved

    def _scan_documents(self, root: Path) -> list[WorkspaceSharedFile]:
        docs_root = root / "docs"
        if not docs_root.is_dir() or docs_root.is_symlink():
            raise WorkspaceSharedFilesError("主映射目录缺少可读取的 docs/ 目录")
        return self._scan_tree(root, docs_root, "document")

    def _scan_deploy(self, root: Path, projects: list[object]) -> list[WorkspaceSharedFile]:
        roots = {root / CONFIG_ROOT}
        for project in projects:
            relative_path = str(project.relative_path)
            if relative_path != ".":
                roots.add(root.joinpath(*relative_path.split("/")) / CONFIG_ROOT)
        files: list[WorkspaceSharedFile] = []
        for deploy_root in sorted(roots):
            files.extend(self._scan_tree(root, deploy_root, "deploy"))
        return files

    def _scan_tree(
        self,
        workspace_root: Path,
        tree_root: Path,
        file_type: str,
    ) -> list[WorkspaceSharedFile]:
        if not tree_root.is_dir() or tree_root.is_symlink():
            raise WorkspaceSharedFilesError(f"找不到目录：{tree_root}")
        files: list[WorkspaceSharedFile] = []
        for path in sorted(tree_root.rglob("*")):
            if path.is_symlink():
                raise WorkspaceSharedFilesError(f"共享文件不能包含符号链接：{path}")
            if not path.is_file():
                continue
            if (
                path.name.casefold() in SENSITIVE_FILENAMES
                or path.suffix.casefold() in SENSITIVE_SUFFIXES
            ):
                raise WorkspaceSharedFilesError(f"共享文件不能包含敏感文件：{path.name}")
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise WorkspaceSharedFilesError(f"共享文件必须是 UTF-8 文本：{path}") from exc
            files.append(
                WorkspaceSharedFile(
                    file_type=file_type,
                    relative_path=path.relative_to(workspace_root).as_posix(),
                    content=content,
                    executable=bool(path.stat().st_mode & 0o111),
                )
            )
        if not files:
            raise WorkspaceSharedFilesError(f"目录中没有可同步文件：{tree_root}")
        return files

    @staticmethod
    def _destination(root: Path, item: WorkspaceSharedFile) -> Path:
        path = PurePosixPath(item.relative_path)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise WorkspaceSharedFilesError("数据库共享文件路径不安全")
        if item.file_type == "document":
            if path.parts[0] != "docs":
                raise WorkspaceSharedFilesError("数据库文档路径必须位于 docs/")
        elif item.file_type == "deploy":
            parts = path.parts
            if not any(
                parts[index : index + 2] == ("deploy", "context-router")
                for index in range(len(parts) - 1)
            ):
                raise WorkspaceSharedFilesError("数据库部署路径必须位于 deploy/context-router/")
        else:
            raise WorkspaceSharedFilesError("数据库共享文件类型不受支持")
        destination = root.joinpath(*path.parts).resolve()
        try:
            destination.relative_to(root.resolve())
        except ValueError as exc:
            raise WorkspaceSharedFilesError("数据库共享文件路径越出主目录") from exc
        return destination

    @staticmethod
    def _deploy_root(root: Path, path: PurePosixPath) -> Path:
        parts = path.parts
        for index in range(len(parts) - 1):
            if parts[index : index + 2] == ("deploy", "context-router"):
                return root.joinpath(*parts[: index + 2])
        raise WorkspaceSharedFilesError("数据库部署路径不正确")

    @staticmethod
    def _remove_tree(root: Path, target: Path) -> None:
        try:
            target.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise WorkspaceSharedFilesError("拒绝删除主目录之外的文件") from exc
        if target.exists() or target.is_symlink():
            if target.is_symlink():
                raise WorkspaceSharedFilesError(f"拒绝覆盖符号链接目录：{target}")
            shutil.rmtree(target)

    @staticmethod
    def _result(
        workspace_id: str,
        root: Path,
        files: list[WorkspaceSharedFile],
        action: str,
    ) -> WorkspaceSharedFilesResult:
        return WorkspaceSharedFilesResult(
            workspace_id=workspace_id,
            source_root=str(root),
            document_count=sum(item.file_type == "document" for item in files),
            deploy_count=sum(item.file_type == "deploy" for item in files),
            action=action,
        )
