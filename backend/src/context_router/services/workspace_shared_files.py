from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
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
    WorkspaceSharedFileSet,
    WorkspaceSharedFileStore,
    shared_file_set_digest,
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


SCRIPT_ROOT = Path("script")
HOST_RUNTIME_ROOT = Path("deploy/host-runtime")
STATE_FILE = Path("deploy/runtime/context-router-shared-files.json")
MAX_SHARED_FILE_BYTES = 1_000_000
MAX_SHARED_SET_BYTES = 16_000_000
IGNORED_SHARED_FILE_NAMES = {".DS_Store"}
IGNORED_SHARED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
}


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
            files.extend(self._scan_optional_root(root, SCRIPT_ROOT, "script"))
            files.extend(self._scan_optional_root(root, HOST_RUNTIME_ROOT, "host_runtime"))
            self._validate_file_set(files)
            file_set = self._files.replace_all(workspace_id, files, bundle)
            self._write_state(root, file_set)
        except (
            ProjectRepositoryError,
            WorkspaceDeploySyncError,
            WorkspaceSharedFileRepositoryError,
        ) as exc:
            raise WorkspaceSharedFilesError(str(exc)) from exc
        return self._result(workspace_id, root, file_set, "publish")

    def publish_runtime_files(self, workspace_id: str) -> WorkspaceSharedFilesResult:
        """Publish scripts while retaining the current database document/deploy snapshot."""
        root = self._main_root(workspace_id)
        try:
            current = self._files.get_file_set(workspace_id)
            if current is None:
                raise WorkspaceSharedFilesError(
                    "数据库中还没有完整工作空间版本，不能单独发布运行脚本"
                )
            files = [item for item in current.files if item.file_type in {"document", "deploy"}]
            if not any(item.file_type == "document" for item in files) or not any(
                item.file_type == "deploy" for item in files
            ):
                raise WorkspaceSharedFilesError(
                    "数据库当前版本缺少文档或部署文件，不能单独发布运行脚本"
                )
            files.extend(self._scan_optional_root(root, SCRIPT_ROOT, "script"))
            files.extend(self._scan_optional_root(root, HOST_RUNTIME_ROOT, "host_runtime"))
            self._validate_file_set(files)
            file_set = self._files.replace_all(workspace_id, files, None)
            self._write_state(root, file_set)
        except WorkspaceSharedFileRepositoryError as exc:
            raise WorkspaceSharedFilesError(str(exc)) from exc
        return self._result(workspace_id, root, file_set, "publish_runtime_files")

    def restore(self, workspace_id: str, revision: int | None = None) -> WorkspaceSharedFilesResult:
        root = self._main_root(workspace_id)
        try:
            file_set = self._files.get_file_set(workspace_id, revision)
        except WorkspaceSharedFileRepositoryError as exc:
            raise WorkspaceSharedFilesError(str(exc)) from exc
        if file_set is None:
            raise WorkspaceSharedFilesError("数据库中还没有可恢复的工作空间文件")
        files = list(file_set.files)
        self._validate_file_set(files, expected_digest=file_set.digest)
        destinations = [(item, self._destination(root, item)) for item in files]
        document_files = [item for item in files if item.file_type == "document"]
        deploy_files = [item for item in files if item.file_type == "deploy"]
        if not document_files or not deploy_files:
            raise WorkspaceSharedFilesError("数据库共享文件不完整，不能覆盖主目录")
        self._restore_atomically(workspace_id, root, file_set, destinations)
        return self._result(workspace_id, root, file_set, "restore")

    def synchronize_if_stale(self, workspace_id: str) -> WorkspaceSharedFilesResult | None:
        root = self._main_root(workspace_id)
        try:
            file_set = self._files.get_file_set(workspace_id)
        except WorkspaceSharedFileRepositoryError as exc:
            raise WorkspaceSharedFilesError(str(exc)) from exc
        if file_set is None:
            raise WorkspaceSharedFilesError("数据库中还没有可同步的工作空间文件")
        if self._is_materialized_current(root, file_set):
            return None
        return self.restore(workspace_id)

    def _is_materialized_current(self, root: Path, file_set: WorkspaceSharedFileSet) -> bool:
        if self._read_state(root) != (file_set.revision, file_set.digest):
            return False
        expected_paths: set[Path] = set()
        for item in file_set.files:
            try:
                destination = self._destination(root, item)
                metadata = destination.lstat()
                if destination.is_symlink() or not destination.is_file():
                    return False
                content_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
            except (OSError, WorkspaceSharedFilesError):
                return False
            if content_sha256 != item.content_sha256:
                return False
            if bool(metadata.st_mode & 0o111) != item.executable:
                return False
            expected_paths.add(destination)
        for managed_root in self._managed_roots(root, file_set.files):
            try:
                actual_paths = {
                    path.resolve()
                    for path in managed_root.rglob("*")
                    if path.is_file() or path.is_symlink()
                }
            except OSError:
                return False
            if any(path not in expected_paths for path in actual_paths):
                return False
        return True

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

    def _scan_optional_root(
        self, root: Path, relative_root: Path, file_type: str
    ) -> list[WorkspaceSharedFile]:
        tree_root = root / relative_root
        if not tree_root.exists():
            return []
        return self._scan_tree(root, tree_root, file_type)

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
            relative_parts = path.relative_to(tree_root).parts
            if path.name in IGNORED_SHARED_FILE_NAMES or any(
                part in IGNORED_SHARED_DIRECTORY_NAMES for part in relative_parts[:-1]
            ):
                continue
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
            content_bytes = content.encode("utf-8")
            if len(content_bytes) > MAX_SHARED_FILE_BYTES:
                raise WorkspaceSharedFilesError(f"共享文件超过 1 MB：{path}")
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
    def _validate_file_set(
        files: list[WorkspaceSharedFile], expected_digest: str | None = None
    ) -> None:
        seen: set[tuple[str, str]] = set()
        total_bytes = 0
        for item in files:
            key = (item.file_type, item.relative_path)
            if key in seen:
                raise WorkspaceSharedFilesError(f"数据库共享文件路径重复：{item.relative_path}")
            seen.add(key)
            content_bytes = item.content.encode("utf-8")
            total_bytes += len(content_bytes)
            if len(content_bytes) > MAX_SHARED_FILE_BYTES:
                raise WorkspaceSharedFilesError(f"共享文件超过 1 MB：{item.relative_path}")
            actual_sha256 = hashlib.sha256(content_bytes).hexdigest()
            if item.content_sha256 != actual_sha256:
                raise WorkspaceSharedFilesError(f"数据库共享文件哈希校验失败：{item.relative_path}")
            if item.executable and not item.content.startswith("#!"):
                raise WorkspaceSharedFilesError(f"可执行共享文件缺少 shebang：{item.relative_path}")
        if total_bytes > MAX_SHARED_SET_BYTES:
            raise WorkspaceSharedFilesError("工作空间共享文件总大小超过 16 MB")
        actual_digest = shared_file_set_digest(files)
        if expected_digest is not None and expected_digest != actual_digest:
            raise WorkspaceSharedFilesError("数据库共享文件集摘要校验失败")

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
        elif item.file_type == "script":
            if path.parts[0] != SCRIPT_ROOT.as_posix():
                raise WorkspaceSharedFilesError("数据库脚本路径必须位于 script/")
        elif item.file_type == "host_runtime":
            if path.parts[:2] != HOST_RUNTIME_ROOT.parts:
                raise WorkspaceSharedFilesError("宿主机运行文件必须位于 deploy/host-runtime/")
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

    def _restore_atomically(
        self,
        workspace_id: str,
        root: Path,
        file_set: WorkspaceSharedFileSet,
        destinations: list[tuple[WorkspaceSharedFile, Path]],
    ) -> None:
        temporary_root = Path(tempfile.mkdtemp(prefix=".context-router-restore-", dir=root))
        stage_root = temporary_root / "stage"
        backup_root = temporary_root / "backup"
        stage_root.mkdir()
        backup_root.mkdir()
        swaps: list[tuple[Path, Path, bool, bool]] = []
        try:
            for item, destination in destinations:
                staged = stage_root / destination.relative_to(root)
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_text(item.content, encoding="utf-8")
                staged.chmod(0o755 if item.executable else 0o644)

            managed_roots = self._managed_roots(root, file_set.files)
            for index, target in enumerate(managed_roots):
                if target.is_symlink():
                    raise WorkspaceSharedFilesError(f"拒绝覆盖符号链接目录：{target}")
                staged = stage_root / target.relative_to(root)
                if not staged.is_dir():
                    raise WorkspaceSharedFilesError(f"暂存共享目录不完整：{target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                backup = backup_root / str(index)
                existed = target.exists()
                preserve_inodes = target == root / HOST_RUNTIME_ROOT and existed
                if existed:
                    if preserve_inodes:
                        shutil.copytree(target, backup, copy_function=shutil.copy2)
                    else:
                        os.replace(target, backup)
                swaps.append((target, backup, existed, preserve_inodes))
                if preserve_inodes:
                    self._synchronize_tree_in_place(root, staged, target)
                else:
                    os.replace(staged, target)

            self._registry.refresh_workspace(workspace_id)
            self._write_state(root, file_set)
        except Exception as exc:
            for target, backup, existed, preserve_inodes in reversed(swaps):
                if preserve_inodes and existed and backup.exists():
                    self._synchronize_tree_in_place(root, backup, target)
                    continue
                if target.exists():
                    self._remove_tree(root, target)
                if existed and backup.exists():
                    os.replace(backup, target)
            try:
                self._registry.refresh_workspace(workspace_id)
            except ProjectRegistryError:
                pass
            if isinstance(exc, WorkspaceSharedFilesError):
                raise
            if isinstance(exc, ProjectRegistryError):
                raise WorkspaceSharedFilesError(f"文件恢复已回滚，文档映射刷新失败：{exc}") from exc
            raise WorkspaceSharedFilesError(f"文件恢复已回滚：{exc}") from exc
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)

    @staticmethod
    def _synchronize_tree_in_place(root: Path, source: Path, target: Path) -> None:
        """Synchronize a tree while preserving existing Docker bind-mount inodes."""
        try:
            target.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise WorkspaceSharedFilesError("拒绝同步主目录之外的文件") from exc
        if target.is_symlink():
            raise WorkspaceSharedFilesError(f"拒绝覆盖符号链接目录：{target}")
        target.mkdir(parents=True, exist_ok=True)

        expected: set[Path] = set()
        for source_path in sorted(source.rglob("*")):
            relative = source_path.relative_to(source)
            destination = target / relative
            expected.add(relative)
            if source_path.is_symlink():
                raise WorkspaceSharedFilesError(f"暂存共享文件不能包含符号链接：{source_path}")
            if source_path.is_dir():
                if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
                    if destination.is_dir() and not destination.is_symlink():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_symlink():
                destination.unlink()
            elif destination.exists() and not destination.is_file():
                shutil.rmtree(destination)
            if destination.exists():
                destination.write_bytes(source_path.read_bytes())
                shutil.copymode(source_path, destination)
            else:
                shutil.copy2(source_path, destination)

        for actual in sorted(
            target.rglob("*"),
            key=lambda item: len(item.relative_to(target).parts),
            reverse=True,
        ):
            if actual.relative_to(target) in expected:
                continue
            if actual.is_symlink() or actual.is_file():
                actual.unlink()
            elif actual.is_dir():
                actual.rmdir()

    @classmethod
    def _managed_roots(cls, root: Path, files: tuple[WorkspaceSharedFile, ...]) -> list[Path]:
        managed: set[Path] = set()
        for item in files:
            path = PurePosixPath(item.relative_path)
            if item.file_type == "document":
                managed.add(root / "docs")
            elif item.file_type == "script":
                managed.add(root / SCRIPT_ROOT)
            elif item.file_type == "host_runtime":
                managed.add(root / HOST_RUNTIME_ROOT)
            elif item.file_type == "deploy":
                managed.add(cls._deploy_root(root, path))
        return sorted(managed, key=lambda item: item.as_posix())

    @staticmethod
    def _read_state(root: Path) -> tuple[int, str] | None:
        path = root / STATE_FILE
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            return int(document["revision"]), str(document["digest"])
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write_state(root: Path, file_set: WorkspaceSharedFileSet) -> None:
        path = root / STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        payload = {
            "revision": file_set.revision,
            "digest": file_set.digest,
            "files": {
                item.relative_path: item.content_sha256
                for item in sorted(file_set.files, key=lambda item: item.relative_path)
            },
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o644)
        os.replace(temporary, path)

    @staticmethod
    def _result(
        workspace_id: str,
        root: Path,
        file_set: WorkspaceSharedFileSet,
        action: str,
    ) -> WorkspaceSharedFilesResult:
        files = file_set.files
        return WorkspaceSharedFilesResult(
            workspace_id=workspace_id,
            source_root=str(root),
            document_count=sum(item.file_type == "document" for item in files),
            deploy_count=sum(item.file_type == "deploy" for item in files),
            script_count=sum(item.file_type == "script" for item in files),
            host_runtime_count=sum(item.file_type == "host_runtime" for item in files),
            revision=file_set.revision,
            digest=file_set.digest,
            action=action,
        )
