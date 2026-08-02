from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path

import yaml

from context_router.schemas.runtime_configs import RuntimeConfigModeUpdate
from context_router.schemas.workspace_deploy_sync import (
    DeployChangeSummary,
    DeployConfigFile,
    DeployProfilePreview,
    ProjectDeployBundle,
    RuntimeProfileBundle,
    WorkspaceDeployBundle,
    WorkspaceDeploySyncPreview,
)
from context_router.schemas.workspace_runtime import (
    WorkspaceRuntimeConfigUpdate,
    WorkspaceRuntimePolicyUpdate,
)
from context_router.services.workspace_paths import normalize_project_relative_path

CONFIG_ROOT = Path("deploy/context-router")
MANIFEST_NAME = "manifest.yaml"
SENSITIVE_FILENAMES = frozenset(
    {
        ".env",
        ".env.local",
        "credentials.json",
        "secrets.json",
        "id_rsa",
        "id_ed25519",
    }
)
SENSITIVE_SUFFIXES = frozenset({".key", ".p12", ".pfx"})


class WorkspaceDeploySyncError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WorkspaceDeploySyncService:
    def __init__(
        self,
        *,
        workspace_repository: object,
        project_repository: object,
        workspace_runtime_repository: object,
        project_runtime_repository: object,
        deploy_repository: object,
        workspace_root_resolver: Callable[[str], Path] | None = None,
    ) -> None:
        self._workspaces = workspace_repository
        self._projects = project_repository
        self._workspace_runtime = workspace_runtime_repository
        self._project_runtime = project_runtime_repository
        self._deploy_repository = deploy_repository
        self._workspace_root_resolver = workspace_root_resolver

    def preview(self, workspace_id: str) -> WorkspaceDeploySyncPreview:
        bundle, root = self._scan(workspace_id)
        return self._preview_bundle(workspace_id, bundle, root)

    def _preview_bundle(
        self,
        workspace_id: str,
        bundle: WorkspaceDeployBundle,
        root: Path,
    ) -> WorkspaceDeploySyncPreview:
        profiles: list[DeployProfilePreview] = []
        profiles.append(
            DeployProfilePreview(
                owner="workspace",
                mode="start",
                file_count=len(bundle.start.files),
                changes=_diff(
                    self._workspace_runtime.list_files(workspace_id, "start"),
                    bundle.start,
                ),
            )
        )
        for project in bundle.projects:
            for mode, profile in (("fast", project.fast), ("full", project.full)):
                profiles.append(
                    DeployProfilePreview(
                        owner=project.relative_path,
                        mode=mode,
                        file_count=len(profile.files),
                        changes=_diff(
                            self._project_runtime.list_files(project.project_id, mode),
                            profile,
                        ),
                    )
                )
        total = DeployChangeSummary(
            additions=sum(item.changes.additions for item in profiles),
            updates=sum(item.changes.updates for item in profiles),
            deletions=sum(item.changes.deletions for item in profiles),
        )
        return WorkspaceDeploySyncPreview(
            valid=True,
            source_root=str(root / CONFIG_ROOT),
            digest=bundle.digest,
            profiles=tuple(profiles),
            total=total,
        )

    def commit(self, workspace_id: str, expected_digest: str) -> WorkspaceDeploySyncPreview:
        bundle, root = self._scan(workspace_id)
        if bundle.digest != expected_digest:
            raise WorkspaceDeploySyncError(
                "deploy_sync_stale_preview",
                "deploy 配置在预览后发生变化，请重新预览",
            )
        preview = self._preview_bundle(workspace_id, bundle, root)
        self._deploy_repository.replace_workspace_bundle(workspace_id, bundle)
        return replace(preview, synchronized=True)

    def _scan(self, workspace_id: str) -> tuple[WorkspaceDeployBundle, Path]:
        workspace = self._workspaces.get_workspace(workspace_id)
        root = (
            self._workspace_root_resolver(workspace_id)
            if self._workspace_root_resolver is not None
            else Path(str(workspace.root_path))
        )
        projects = self._projects.list_projects(workspace_id=workspace_id)
        return scan_workspace_deploy_bundle(root, projects), root.resolve()


def scan_workspace_deploy_bundle(
    workspace_root: Path,
    projects: Iterable[object],
) -> WorkspaceDeployBundle:
    root = workspace_root.resolve()
    config_root = root / CONFIG_ROOT
    manifest_path = config_root / MANIFEST_NAME
    _ensure_no_symlink_chain(root, manifest_path)
    _ensure_within_workspace(root, manifest_path)
    manifest = _read_manifest(manifest_path)

    registered = {
        normalize_project_relative_path(str(project.relative_path)): project for project in projects
    }
    requested_paths = _project_paths(manifest)
    _validate_project_set(requested_paths, registered)

    workspace_section = manifest.get("workspace")
    workspace_paths = (
        workspace_section.get("workspace_paths", []) if isinstance(workspace_section, dict) else []
    )
    try:
        policy = WorkspaceRuntimePolicyUpdate.model_validate(
            {"project_order": [], "workspace_paths": workspace_paths}
        )
    except ValueError as exc:
        raise WorkspaceDeploySyncError("invalid_manifest", str(exc)) from exc

    start = _scan_profile(
        config_root / "workspace/start",
        workspace=True,
        workspace_root=root,
    )
    project_bundles: list[ProjectDeployBundle] = []
    project_ids: list[str] = []
    for relative_path in requested_paths:
        project = registered[relative_path]
        project_root = root if relative_path == "." else root / relative_path
        _ensure_within_workspace(root, project_root)
        _ensure_no_symlink_chain(root, project_root)
        runtime_root = project_root / CONFIG_ROOT
        project_id = str(project.id)
        project_ids.append(project_id)
        project_bundles.append(
            ProjectDeployBundle(
                project_id=project_id,
                relative_path=relative_path,
                fast=_scan_profile(
                    runtime_root / "fast",
                    workspace=False,
                    workspace_root=root,
                ),
                full=_scan_profile(
                    runtime_root / "full",
                    workspace=False,
                    workspace_root=root,
                ),
            )
        )

    payload = {
        "schema_version": 1,
        "workspace_paths": policy.workspace_paths,
        "project_order": project_ids,
        "start": _profile_payload(start),
        "projects": [
            {
                "project_id": item.project_id,
                "relative_path": item.relative_path,
                "fast": _profile_payload(item.fast),
                "full": _profile_payload(item.full),
            }
            for item in project_bundles
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return WorkspaceDeployBundle(
        digest=digest,
        workspace_paths=tuple(policy.workspace_paths),
        project_order=tuple(project_ids),
        start=start,
        projects=tuple(project_bundles),
    )


def _read_manifest(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise WorkspaceDeploySyncError("symlink_forbidden", "manifest.yaml 不能是符号链接")
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise WorkspaceDeploySyncError(
            "manifest_missing",
            f"找不到 deploy/context-router/{MANIFEST_NAME}",
        ) from exc
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise WorkspaceDeploySyncError("invalid_manifest", "manifest.yaml 语法错误") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise WorkspaceDeploySyncError("invalid_manifest", "schema_version 必须是 1")
    return document


def _project_paths(manifest: dict[str, object]) -> tuple[str, ...]:
    raw = manifest.get("project_order")
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise WorkspaceDeploySyncError("invalid_manifest", "project_order 必须是路径数组")
    paths = tuple(normalize_project_relative_path(item) for item in raw)
    if len(paths) != len(set(paths)):
        raise WorkspaceDeploySyncError("invalid_manifest", "project_order 不能重复")
    return paths


def _validate_project_set(
    requested: tuple[str, ...],
    registered: dict[str, object],
) -> None:
    unknown = [item for item in requested if item not in registered]
    missing = [item for item in registered if item not in requested]
    if unknown:
        raise WorkspaceDeploySyncError("unknown_project", f"未登记的项目路径：{unknown[0]}")
    if missing:
        raise WorkspaceDeploySyncError("missing_project", f"project_order 缺少项目：{missing[0]}")


def _scan_profile(
    directory: Path,
    *,
    workspace: bool,
    workspace_root: Path,
) -> RuntimeProfileBundle:
    _ensure_within_workspace(workspace_root, directory)
    _ensure_no_symlink_chain(workspace_root, directory)
    if directory.is_symlink():
        raise WorkspaceDeploySyncError("symlink_forbidden", f"配置目录不能是符号链接：{directory}")
    if not directory.is_dir():
        mode = directory.name
        raise WorkspaceDeploySyncError("profile_missing", f"{mode} 配置目录不存在")
    files: list[DeployConfigFile] = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            relative_path = path.relative_to(directory).as_posix()
            raise WorkspaceDeploySyncError(
                "symlink_forbidden", f"运行配置不能包含符号链接：{relative_path}"
            )
        if not path.is_file():
            continue
        relative_path = path.relative_to(directory).as_posix()
        if _is_sensitive_file(path):
            raise WorkspaceDeploySyncError(
                "sensitive_file_forbidden", f"运行配置不能包含敏感文件：{relative_path}"
            )
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceDeploySyncError(
                "invalid_text_file", f"运行配置必须是 UTF-8 文本：{relative_path}"
            ) from exc
        files.append(
            DeployConfigFile(
                relative_path=relative_path,
                content=content,
                executable=bool(path.stat().st_mode & 0o111),
            )
        )

    validation_payload = {
        "files": [
            {
                "relative_path": item.relative_path,
                "content": item.content,
                "executable": item.executable,
            }
            for item in files
        ]
    }
    try:
        if workspace:
            WorkspaceRuntimeConfigUpdate.model_validate(validation_payload)
        else:
            RuntimeConfigModeUpdate.model_validate(validation_payload)
            entry = next((item for item in files if item.relative_path == "deploy.sh"), None)
            if entry is None or not entry.executable:
                raise ValueError(f"{directory.name} 配置必须包含可执行的 deploy.sh")
    except ValueError as exc:
        raise WorkspaceDeploySyncError("invalid_profile", str(exc)) from exc
    return RuntimeProfileBundle(files=tuple(files))


def _is_sensitive_file(path: Path) -> bool:
    name = path.name.casefold()
    return name in SENSITIVE_FILENAMES or path.suffix.casefold() in SENSITIVE_SUFFIXES


def _ensure_within_workspace(workspace_root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(workspace_root.resolve())
    except ValueError as exc:
        raise WorkspaceDeploySyncError(
            "path_outside_workspace", f"运行配置路径不能越出 Workspace：{path}"
        ) from exc


def _ensure_no_symlink_chain(workspace_root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(workspace_root)
    except ValueError as exc:
        raise WorkspaceDeploySyncError(
            "path_outside_workspace", f"运行配置路径不能越出 Workspace：{path}"
        ) from exc
    current = workspace_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise WorkspaceDeploySyncError(
                "symlink_forbidden", f"运行配置路径不能包含符号链接：{current}"
            )


def _profile_payload(profile: RuntimeProfileBundle) -> list[dict[str, object]]:
    return [
        {
            "relative_path": item.relative_path,
            "content": item.content,
            "executable": item.executable,
        }
        for item in profile.files
    ]


def _diff(current: Iterable[object], desired: RuntimeProfileBundle) -> DeployChangeSummary:
    current_files = {
        str(item.relative_path): (str(item.content), bool(item.executable)) for item in current
    }
    desired_files = {item.relative_path: (item.content, item.executable) for item in desired.files}
    shared = current_files.keys() & desired_files.keys()
    return DeployChangeSummary(
        additions=len(desired_files.keys() - current_files.keys()),
        updates=sum(current_files[path] != desired_files[path] for path in shared),
        deletions=len(current_files.keys() - desired_files.keys()),
    )
