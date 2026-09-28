from __future__ import annotations

import os
import plistlib
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from context_router.config import Settings
from context_router.repositories.managed_script_repository import (
    ManagedScriptRecord,
    ManagedScriptRepositoryError,
    ManagedScriptStore,
    new_managed_script_id,
)
from context_router.repositories.workspace_repository import WorkspaceStore
from context_router.schemas.managed_scripts import (
    ManagedScript,
    ManagedScriptList,
    ManagedScriptRunResult,
    ManagedScriptWorkspace,
)
from context_router.services.local_workspace_mapping import (
    LocalWorkspaceMappingError,
    LocalWorkspaceMappingService,
)
from context_router.services.workspace_shared_files import (
    WorkspaceSharedFilesError,
    WorkspaceSharedFilesService,
)


class ManagedScriptsError(ValueError):
    pass


REPO_ROOT = Path(__file__).resolve().parents[4]
LAUNCHD_LABEL_PREFIX = "com.conchi.context-router.script."

ACTION_HOST_RUNTIME = "host_runtime_ensure"
ACTION_SHARED_CONFIG = "shared_config_ensure"
ACTION_PERSONAL_UTILS = "personal_utils_ensure"
ACTION_SYNC_SCRIPTS = "sync_scripts"
ACTION_SYNC_DOCUMENTS = "sync_documents"
ACTION_SYNC_DEPLOY = "sync_deploy"
AUTOSTART_ACTIONS = {ACTION_HOST_RUNTIME, ACTION_SHARED_CONFIG, ACTION_PERSONAL_UTILS}
COMPANION_FOLLOW_FLAGS = {
    ACTION_SHARED_CONFIG: "shared-config-center.follow",
    ACTION_PERSONAL_UTILS: "personal-utils.follow",
}
SHARED_CONFIG_FOLLOW_FLAG = COMPANION_FOLLOW_FLAGS[ACTION_SHARED_CONFIG]
PERSONAL_UTILS_FOLLOW_FLAG = COMPANION_FOLLOW_FLAGS[ACTION_PERSONAL_UTILS]
GLOBAL_ACTIONS = {ACTION_SYNC_SCRIPTS, ACTION_SYNC_DOCUMENTS, ACTION_SYNC_DEPLOY}
RETIRED_SLUGS = ("context-router-native-stack", "sync-workspace-files")


@dataclass(frozen=True, slots=True)
class CatalogSpec:
    slug: str
    name: str
    description: str
    kind: str
    action_key: str
    sort_order: int
    bind_panzhihua: bool = False
    default_autostart: bool = False


CATALOG: tuple[CatalogSpec, ...] = (
    CatalogSpec(
        slug="shared-config-center",
        name="共享配置中心",
        description=(
            "配置管理依赖的 API/Web 容器没起来时拉起，不重建镜像，也不随电脑开机。"
        ),
        kind="autostart",
        action_key=ACTION_SHARED_CONFIG,
        sort_order=10,
        default_autostart=True,
    ),
    CatalogSpec(
        slug="personal-utils",
        name="Personal Utils Hub",
        description=(
            "本机容器与开发者工具箱。前端 39889、后端 39888 没起来时用项目 start.sh 拉起，"
            "不随电脑开机。"
        ),
        kind="autostart",
        action_key=ACTION_PERSONAL_UTILS,
        sort_order=15,
        default_autostart=True,
    ),
    CatalogSpec(
        slug="panzhihua-host-runtime",
        name="攀枝花 Host Runtime",
        description=(
            "启动 Context Router 时保障攀枝花共享网络、已有容器、数据库代理和本地网关，"
            "不重建镜像，也不随电脑开机。"
        ),
        kind="autostart",
        action_key=ACTION_HOST_RUNTIME,
        sort_order=20,
        bind_panzhihua=True,
    ),
    CatalogSpec(
        slug="sync-workspace-scripts",
        name="同步脚本到 script/",
        description=(
            "只把数据库当前版本的 script/ 写到所选工作空间主目录，"
            "不会回写数据库，也不改 docs/ 和 deploy/。"
        ),
        kind="global",
        action_key=ACTION_SYNC_SCRIPTS,
        sort_order=30,
    ),
    CatalogSpec(
        slug="sync-workspace-deploy",
        name="同步部署配置到 deploy/",
        description=(
            "只把数据库当前版本的 deploy/context-router/ 和 deploy/host-runtime/ "
            "写到所选工作空间主目录，不会回写数据库。"
        ),
        kind="global",
        action_key=ACTION_SYNC_DEPLOY,
        sort_order=40,
    ),
    CatalogSpec(
        slug="sync-workspace-docs",
        name="同步文档到 docs/",
        description=(
            "只把数据库当前版本的 docs/ 写到所选工作空间主目录，"
            "不会回写数据库，也不改 script/ 和 deploy/。"
        ),
        kind="global",
        action_key=ACTION_SYNC_DOCUMENTS,
        sort_order=50,
    ),
)


class LaunchAgentStore(Protocol):
    def is_installed(self, slug: str) -> bool: ...

    def install(
        self,
        slug: str,
        program_arguments: list[str],
        working_directory: str,
    ) -> None: ...

    def uninstall(self, slug: str) -> None: ...


class InMemoryLaunchAgentStore:
    def __init__(self) -> None:
        self.installed: dict[str, tuple[str, ...]] = {}

    def is_installed(self, slug: str) -> bool:
        return slug in self.installed

    def install(
        self,
        slug: str,
        program_arguments: list[str],
        working_directory: str,
    ) -> None:
        if not program_arguments:
            raise ManagedScriptsError("启动命令为空")
        self.installed[slug] = (working_directory, *program_arguments)

    def uninstall(self, slug: str) -> None:
        self.installed.pop(slug, None)


class MacLaunchAgentStore:
    def __init__(self, *, runtime_root: Path, repo_root: Path) -> None:
        self._runtime_root = runtime_root
        self._repo_root = repo_root

    def is_installed(self, slug: str) -> bool:
        return self._plist_path(slug).is_file()

    def install(
        self,
        slug: str,
        program_arguments: list[str],
        working_directory: str,
    ) -> None:
        if not program_arguments:
            raise ManagedScriptsError("启动命令为空")
        plist_path = self._plist_path(slug)
        log_dir = self._runtime_root / "managed-scripts"
        log_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": self._label(slug),
            "ProgramArguments": program_arguments,
            "WorkingDirectory": working_directory,
            "RunAtLoad": True,
            "KeepAlive": False,
            "StandardOutPath": str(log_dir / f"{slug}.log"),
            "StandardErrorPath": str(log_dir / f"{slug}.err.log"),
        }
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_bytes(plistlib.dumps(payload))
        domain = f"gui/{os.getuid()}"
        self._run_launchctl(["bootout", domain, str(plist_path)], allow_failure=True)
        completed = self._run_launchctl(["bootstrap", domain, str(plist_path)])
        if completed.returncode != 0:
            raise ManagedScriptsError(
                completed.stderr.strip() or completed.stdout.strip() or "安装登录启动项失败"
            )

    def uninstall(self, slug: str) -> None:
        plist_path = self._plist_path(slug)
        domain = f"gui/{os.getuid()}"
        if plist_path.exists():
            self._run_launchctl(["bootout", domain, str(plist_path)], allow_failure=True)
            plist_path.unlink(missing_ok=True)

    def _plist_path(self, slug: str) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self._label(slug)}.plist"

    @staticmethod
    def _label(slug: str) -> str:
        return f"{LAUNCHD_LABEL_PREFIX}{slug}"

    @staticmethod
    def _run_launchctl(
        args: list[str],
        *,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["launchctl", *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 and not allow_failure:
            return completed
        return completed


class ManagedScriptsService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: ManagedScriptStore,
        workspaces: WorkspaceStore,
        local_mapping: LocalWorkspaceMappingService,
        shared_files: WorkspaceSharedFilesService,
        launch_agents: LaunchAgentStore | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._workspaces = workspaces
        self._mapping = local_mapping
        self._shared_files = shared_files
        self._repo_root = repo_root or REPO_ROOT
        self._launch_agents = launch_agents or MacLaunchAgentStore(
            runtime_root=settings.runtime_root,
            repo_root=self._repo_root,
        )

    def list_scripts(self) -> ManagedScriptList:
        try:
            self._ensure_catalog()
            records = self._repository.list_all()
        except ManagedScriptRepositoryError as exc:
            raise ManagedScriptsError(str(exc)) from exc
        workspaces = self._visible_workspaces()
        return ManagedScriptList(
            scripts=[self._view(item, workspaces) for item in records],
            workspaces=[ManagedScriptWorkspace(id=item.id, name=item.name) for item in workspaces],
        )

    def set_autostart(self, script_id: str, enabled: bool) -> ManagedScript:
        try:
            record = self._repository.get(script_id)
        except ManagedScriptRepositoryError as exc:
            raise ManagedScriptsError(str(exc)) from exc
        if record is None:
            raise ManagedScriptsError("找不到脚本")
        if record.kind != "autostart" or record.action_key not in AUTOSTART_ACTIONS:
            raise ManagedScriptsError("这个脚本不能跟随 Context Router 启动")
        view = self._view(record, self._visible_workspaces())
        if enabled and (not view.available or not view.command_path):
            raise ManagedScriptsError(view.unavailable_reason or "项目启动脚本当前不可用")
        self._launch_agents.uninstall(record.slug)
        try:
            updated = self._repository.set_autostart(record.id, enabled)
        except ManagedScriptRepositoryError as exc:
            raise ManagedScriptsError(str(exc)) from exc
        if updated.action_key in COMPANION_FOLLOW_FLAGS:
            self._write_companion_follow_flag(updated.action_key, enabled)
        return self._view(updated, self._visible_workspaces())

    def follows_shared_config(self) -> bool:
        return self._follows_companion(ACTION_SHARED_CONFIG)

    def follows_personal_utils(self) -> bool:
        return self._follows_companion(ACTION_PERSONAL_UTILS)

    def ensure_shared_config(self) -> None:
        self._ensure_companion(
            ACTION_SHARED_CONFIG,
            self._shared_config_command(),
            missing="共享配置中心保障脚本不可用",
            failed="拉起共享配置中心失败",
        )

    def ensure_personal_utils(self) -> None:
        self._ensure_companion(
            ACTION_PERSONAL_UTILS,
            self._personal_utils_command(),
            missing="Personal Utils Hub 保障脚本不可用",
            failed="拉起 Personal Utils Hub 失败",
        )

    def run(self, script_id: str, workspace_id: str | None = None) -> ManagedScriptRunResult:
        try:
            record = self._repository.get(script_id)
        except ManagedScriptRepositoryError as exc:
            raise ManagedScriptsError(str(exc)) from exc
        if record is None:
            raise ManagedScriptsError("找不到脚本")
        if record.action_key not in GLOBAL_ACTIONS:
            raise ManagedScriptsError("项目启动脚本只通过开关绑定，不在页面直接执行")
        target_id = workspace_id or record.workspace_id
        if not target_id:
            raise ManagedScriptsError("请选择要同步的工作空间")
        try:
            if record.action_key == ACTION_SYNC_SCRIPTS:
                synced = self._shared_files.sync_scripts(target_id)
                message = (
                    f"已从数据库同步 {synced.script_count} 个脚本到 {synced.target_directory}。"
                )
            elif record.action_key == ACTION_SYNC_DOCUMENTS:
                synced = self._shared_files.sync_documents(target_id)
                message = f"已从数据库同步 {synced.file_count} 个文档到 {synced.target_directory}。"
            else:
                synced = self._shared_files.sync_deploy(target_id)
                message = (
                    f"已从数据库同步 {synced.file_count} 个部署文件到 {synced.target_directory}。"
                )
        except WorkspaceSharedFilesError as exc:
            raise ManagedScriptsError(str(exc)) from exc
        return ManagedScriptRunResult(
            script_id=record.id,
            action=record.action_key,
            workspace_id=target_id,
            message=message,
        )

    def _ensure_catalog(self) -> None:
        existing = {item.slug: item for item in self._repository.list_all()}
        for slug in RETIRED_SLUGS:
            if slug not in existing:
                continue
            self._launch_agents.uninstall(slug)
            self._repository.delete_by_slug(slug)
            existing.pop(slug, None)
        for record in existing.values():
            if record.action_key in AUTOSTART_ACTIONS:
                self._launch_agents.uninstall(record.slug)
        workspaces = self._visible_workspaces()
        now = datetime.now(UTC)
        for spec in CATALOG:
            current = existing.get(spec.slug)
            preserved_enabled = spec.default_autostart
            if current is not None and (
                current.name != spec.name
                or current.description != spec.description
                or current.action_key != spec.action_key
                or current.sort_order != spec.sort_order
            ):
                preserved_enabled = current.autostart_enabled
                self._repository.delete_by_slug(spec.slug)
                existing.pop(spec.slug, None)
                current = None
            if current is not None:
                continue
            workspace_id = None
            if spec.bind_panzhihua:
                workspace_id = self._panzhihua_workspace_id(workspaces)
                if workspace_id is None:
                    continue
            self._repository.insert(
                ManagedScriptRecord(
                    id=new_managed_script_id(),
                    slug=spec.slug,
                    name=spec.name,
                    description=spec.description,
                    kind=spec.kind,
                    action_key=spec.action_key,
                    workspace_id=workspace_id,
                    autostart_enabled=preserved_enabled,
                    sort_order=spec.sort_order,
                    created_at=now,
                    updated_at=now,
                )
            )
            if spec.action_key in COMPANION_FOLLOW_FLAGS:
                self._write_companion_follow_flag(spec.action_key, preserved_enabled)

    def _visible_workspaces(self):
        records = []
        for item in self._workspaces.list_workspaces():
            mapped = self._mapping.map_record(item)
            if mapped is not None:
                records.append(mapped)
        return records

    def _panzhihua_workspace_id(self, workspaces) -> str | None:
        for item in workspaces:
            root = Path(item.root_path)
            if "攀枝花" in item.name or root.name == "panzhihua_dev_workforce":
                return item.id
        return None

    def _view(self, record: ManagedScriptRecord, workspaces) -> ManagedScript:
        workspace = next((item for item in workspaces if item.id == record.workspace_id), None)
        command_path, available, reason = self._resolve_command(record, workspace)
        bound = (
            record.kind == "autostart"
            and record.action_key in AUTOSTART_ACTIONS
            and record.autostart_enabled
            and available
        )
        return ManagedScript(
            id=record.id,
            slug=record.slug,
            name=record.name,
            description=record.description,
            kind=record.kind,
            action_key=record.action_key,
            workspace_id=None if workspace is None else workspace.id,
            workspace_name=None if workspace is None else workspace.name,
            command_path=None if command_path is None else str(command_path),
            autostart_enabled=record.autostart_enabled,
            autostart_installed=bound,
            available=available,
            unavailable_reason=reason,
        )

    def _resolve_command(
        self,
        record: ManagedScriptRecord,
        workspace,
    ) -> tuple[Path | None, bool, str | None]:
        if record.action_key == ACTION_SHARED_CONFIG:
            path = self._shared_config_command()
            if path is None:
                return None, False, "找不到共享配置中心保障脚本"
            return path, True, None
        if record.action_key == ACTION_PERSONAL_UTILS:
            path = self._personal_utils_command()
            if path is None:
                return None, False, "找不到 Personal Utils Hub 保障脚本"
            return path, True, None
        if record.action_key == ACTION_HOST_RUNTIME:
            if workspace is None:
                return None, False, "未找到已启用的攀枝花工作空间"
            try:
                root = self._mapping.main_host_path(workspace.id, workspace.root_path)
            except LocalWorkspaceMappingError as exc:
                return None, False, str(exc)
            path = root / "deploy" / "host-runtime" / "ensure.sh"
            if not path.is_file():
                return None, False, f"找不到 {path}"
            return path, True, None
        if record.action_key in GLOBAL_ACTIONS:
            candidates = [workspace] if workspace is not None else self._visible_workspaces()
            if not workspaces_available(candidates):
                return None, False, "没有可同步的工作空间"
            return None, True, None
        return None, False, "未知脚本动作"

    def _program_arguments(self, record: ManagedScriptRecord, command_path: Path) -> list[str]:
        wrapper = self._repo_root / "scripts" / "run-managed-autostart.sh"
        if record.action_key == ACTION_HOST_RUNTIME:
            return [str(wrapper), str(command_path), "ensure"]
        return [str(wrapper), str(command_path)]

    def _follows_companion(self, action_key: str) -> bool:
        try:
            self._ensure_catalog()
            records = self._repository.list_all()
        except ManagedScriptRepositoryError:
            return False
        workspaces = self._visible_workspaces()
        for record in records:
            if record.action_key != action_key or not record.autostart_enabled:
                continue
            return self._view(record, workspaces).available
        return False

    def _ensure_companion(
        self,
        action_key: str,
        command: Path | None,
        *,
        missing: str,
        failed: str,
    ) -> None:
        if not self._follows_companion(action_key):
            return
        if command is None:
            raise ManagedScriptsError(missing)
        completed = subprocess.run(
            [str(command)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or failed
            raise ManagedScriptsError(detail)

    def _shared_config_command(self) -> Path | None:
        path = self._repo_root / "scripts" / "ensure-shared-config-center.sh"
        return path if path.is_file() else None

    def _personal_utils_command(self) -> Path | None:
        path = self._repo_root / "scripts" / "ensure-personal-utils.sh"
        return path if path.is_file() else None

    def _write_companion_follow_flag(self, action_key: str, enabled: bool) -> None:
        flag_name = COMPANION_FOLLOW_FLAGS.get(action_key)
        if flag_name is None:
            return
        directory = Path(self._settings.runtime_root) / "managed-scripts"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / flag_name).write_text(
            "1\n" if enabled else "0\n",
            encoding="utf-8",
        )


def workspaces_available(workspaces) -> bool:
    return bool(workspaces)
