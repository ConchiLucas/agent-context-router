from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Literal

import yaml

from context_router.config import Settings
from context_router.repositories.workspace_repository import WorkspaceRecord


class LocalWorkspaceMappingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LocalWorkspaceEntry:
    workspace_id: str
    visible: bool
    main_path: str
    document_reader_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LocalWorkspaceMatch:
    workspace_id: str
    access_mode: Literal["full", "documents_only"]
    host_path: Path
    resolved_path: Path


class LocalWorkspaceMappingService:
    """Loads machine-local workspace paths without changing database records."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = RLock()
        self._entries: dict[str, LocalWorkspaceEntry] = {}
        self.reload()

    @property
    def is_configured(self) -> bool:
        return self._settings.workspace_mapping_file is not None

    def reload(self) -> None:
        mapping_file = self._settings.workspace_mapping_file
        if mapping_file is None:
            with self._lock:
                self._entries = {}
            return
        try:
            payload = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise LocalWorkspaceMappingError(f"找不到本机工作空间映射文件：{mapping_file}") from exc
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise LocalWorkspaceMappingError(
                f"本机工作空间映射文件读取失败：{mapping_file}"
            ) from exc
        entries = self._parse_payload(payload)
        with self._lock:
            self._entries = entries

    def map_record(self, record: WorkspaceRecord) -> WorkspaceRecord | None:
        if not self.is_configured:
            return record
        entry = self._entry(record.id)
        if entry is None or not entry.visible:
            return None
        return replace(record, root_path=str(self._host_path(entry.main_path)))

    def require_visible_record(self, record: WorkspaceRecord) -> WorkspaceRecord:
        mapped = self.map_record(record)
        if mapped is None:
            raise LocalWorkspaceMappingError("工作空间未在本机映射文件中启用")
        return mapped

    def reader_count(self, workspace_id: str) -> int:
        entry = self._entry(workspace_id)
        return len(entry.document_reader_paths) if entry is not None else 0

    def main_host_path(self, workspace_id: str, fallback: str | None = None) -> Path:
        if not self.is_configured:
            if fallback is None:
                raise LocalWorkspaceMappingError("工作空间主目录不可用")
            return Path(fallback).expanduser()
        entry = self._entry(workspace_id)
        if entry is None or not entry.visible:
            raise LocalWorkspaceMappingError("工作空间未在本机映射文件中启用")
        return self._host_path(entry.main_path)

    def match_cwd(self, cwd: str) -> LocalWorkspaceMatch | None:
        source = Path(cwd.strip()).expanduser()
        if not source.is_absolute():
            raise LocalWorkspaceMappingError("cwd 必须是绝对路径")
        if not self.is_configured:
            return None
        candidates: list[LocalWorkspaceMatch] = []
        with self._lock:
            entries = tuple(self._entries.values())
        for entry in entries:
            if not entry.visible:
                continue
            candidates.append(self._match(entry.workspace_id, "full", entry.main_path))
            candidates.extend(
                self._match(entry.workspace_id, "documents_only", item)
                for item in entry.document_reader_paths
            )
        matched = [
            item
            for item in candidates
            if source.resolve() == item.host_path.resolve()
            or item.host_path.resolve() in source.resolve().parents
        ]
        if not matched:
            return None
        return max(matched, key=lambda item: len(item.host_path.parts))

    def require_full_access(self, *, cwd: str, workspace_id: str) -> None:
        if not self.is_configured:
            return
        match = self.match_cwd(cwd)
        if match is None or match.workspace_id != workspace_id or match.access_mode != "full":
            raise LocalWorkspaceMappingError(
                "当前目录只有共享文档读取权限，不能使用数据库或部署工具"
            )

    def _entry(self, workspace_id: str) -> LocalWorkspaceEntry | None:
        with self._lock:
            return self._entries.get(workspace_id)

    def _match(
        self,
        workspace_id: str,
        access_mode: Literal["full", "documents_only"],
        relative_path: str,
    ) -> LocalWorkspaceMatch:
        host_path = self._host_path(relative_path)
        return LocalWorkspaceMatch(
            workspace_id=workspace_id,
            access_mode=access_mode,
            host_path=host_path,
            resolved_path=self._container_path(relative_path),
        )

    def _host_path(self, relative_path: str) -> Path:
        return (self._settings.workspace_host_root / relative_path).resolve()

    def _container_path(self, relative_path: str) -> Path:
        return (self._settings.workspace_container_root / relative_path).resolve()

    def _parse_payload(self, payload: object) -> dict[str, LocalWorkspaceEntry]:
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise LocalWorkspaceMappingError("本机工作空间映射文件 version 必须为 1")
        raw_workspaces = payload.get("workspaces")
        if not isinstance(raw_workspaces, dict):
            raise LocalWorkspaceMappingError("本机工作空间映射文件缺少 workspaces")
        entries: dict[str, LocalWorkspaceEntry] = {}
        claimed_paths: dict[str, str] = {}
        for raw_id, raw_entry in raw_workspaces.items():
            workspace_id = str(raw_id).strip()
            if not workspace_id or not isinstance(raw_entry, dict):
                raise LocalWorkspaceMappingError("工作空间映射项格式不正确")
            visible = raw_entry.get("visible", True)
            if not isinstance(visible, bool):
                raise LocalWorkspaceMappingError(f"{workspace_id}.visible 必须是布尔值")
            main_path = self._normalize_relative_path(
                raw_entry.get("main_path"), f"{workspace_id}.main_path"
            )
            raw_readers = raw_entry.get("document_reader_paths", [])
            if not isinstance(raw_readers, list):
                raise LocalWorkspaceMappingError(f"{workspace_id}.document_reader_paths 必须是列表")
            readers = tuple(
                self._normalize_relative_path(item, f"{workspace_id}.document_reader_paths")
                for item in raw_readers
            )
            for path in (main_path, *readers):
                owner = claimed_paths.get(path)
                if owner is not None:
                    raise LocalWorkspaceMappingError(
                        f"本机路径 {path} 被 {owner} 和 {workspace_id} 重复使用"
                    )
                claimed_paths[path] = workspace_id
            entries[workspace_id] = LocalWorkspaceEntry(
                workspace_id=workspace_id,
                visible=visible,
                main_path=main_path,
                document_reader_paths=readers,
            )
        return entries

    @staticmethod
    def _normalize_relative_path(value: object, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise LocalWorkspaceMappingError(f"{label} 不能为空")
        raw = value.strip()
        if "\\" in raw or raw.startswith(("/", "~")):
            raise LocalWorkspaceMappingError(f"{label} 必须是相对 workspace_host_root 的路径")
        path = PurePosixPath(raw)
        if any(part in {"", ".", ".."} for part in path.parts):
            raise LocalWorkspaceMappingError(f"{label} 不能包含 . 或 ..")
        return path.as_posix()
