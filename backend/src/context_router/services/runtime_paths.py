from __future__ import annotations

from pathlib import Path

from context_router.config import Settings


class RuntimePathError(ValueError):
    pass


class RuntimePathResolver:
    """Translate configured host paths into paths readable by this process."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def host_root(self) -> Path:
        return (self._settings.workspace_root or self._settings.workspace_host_root).expanduser()

    @property
    def readable_root(self) -> Path:
        if self._settings.runtime_mode == "native":
            return self.host_root
        return self._settings.workspace_container_root.expanduser()

    def map_host_path(self, value: str | Path) -> Path:
        source = Path(value).expanduser()
        if not source.is_absolute():
            raise RuntimePathError("路径必须是绝对路径")
        try:
            relative = source.relative_to(self.host_root)
        except ValueError:
            return source.resolve()
        return self.readable_root.joinpath(relative).resolve()

    def map_relative_path(self, value: str | Path) -> Path:
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimePathError("工作空间映射路径必须是安全的相对路径")
        return self.readable_root.joinpath(relative).resolve()

    def resolve_stored_runtime_path(self, value: str | Path) -> Path:
        """Resolve current paths and old /runtime paths after the native cutover."""
        path = Path(value).expanduser()
        if path.is_absolute() and path.parts[:2] == ("/", "runtime"):
            return self._settings.runtime_root.joinpath(*path.parts[2:]).resolve()
        return path.resolve()
