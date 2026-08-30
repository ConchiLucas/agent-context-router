from pathlib import Path

import pytest

from context_router.config import Settings
from context_router.services.runtime_paths import RuntimePathError, RuntimePathResolver


def test_native_paths_use_the_real_workspace_root(tmp_path: Path) -> None:
    resolver = RuntimePathResolver(Settings(runtime_mode="native", workspace_root=tmp_path))

    assert resolver.host_root == tmp_path
    assert resolver.readable_root == tmp_path
    assert resolver.map_host_path(tmp_path / "workspace/docs/AGENTS.md") == (
        tmp_path / "workspace/docs/AGENTS.md"
    )


def test_container_paths_keep_the_legacy_mount_translation(tmp_path: Path) -> None:
    host_root = tmp_path / "host"
    container_root = tmp_path / "container"
    resolver = RuntimePathResolver(
        Settings(
            runtime_mode="container",
            workspace_host_root=host_root,
            workspace_container_root=container_root,
        )
    )

    assert resolver.map_host_path(host_root / "workspace/AGENTS.md") == (
        container_root / "workspace/AGENTS.md"
    )


def test_relative_mapping_rejects_escape(tmp_path: Path) -> None:
    resolver = RuntimePathResolver(Settings(workspace_root=tmp_path))

    with pytest.raises(RuntimePathError, match="安全的相对路径"):
        resolver.map_relative_path("../outside")


def test_legacy_runtime_paths_map_to_native_runtime_root(tmp_path: Path) -> None:
    resolver = RuntimePathResolver(Settings(runtime_root=tmp_path / "runtime"))

    assert resolver.resolve_stored_runtime_path("/runtime/runs/1.log") == (
        tmp_path / "runtime/runs/1.log"
    )
