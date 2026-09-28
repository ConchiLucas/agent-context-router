from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from context_router.config import Settings
from context_router.repositories.managed_script_repository import (
    InMemoryManagedScriptRepository,
    ManagedScriptRecord,
)
from context_router.repositories.workspace_repository import (
    InMemoryWorkspaceRepository,
    WorkspaceRecord,
)
from context_router.services.local_workspace_mapping import LocalWorkspaceMappingService
from context_router.services.managed_scripts import (
    ACTION_SYNC_DOCUMENTS,
    ACTION_SYNC_SCRIPTS,
    InMemoryLaunchAgentStore,
    ManagedScriptsError,
    ManagedScriptsService,
)


class _FakeSharedFiles:
    def __init__(self) -> None:
        self.synced: list[str] = []
        self.documents: list[str] = []
        self.deploys: list[str] = []

    def sync_scripts(self, workspace_id: str):
        self.synced.append(workspace_id)

        class _Result:
            script_count = 2
            target_directory = "/tmp/ws/script"

        return _Result()

    def sync_documents(self, workspace_id: str):
        self.documents.append(workspace_id)

        class _Result:
            file_count = 3
            target_directory = "/tmp/ws/docs"

        return _Result()

    def sync_deploy(self, workspace_id: str):
        self.deploys.append(workspace_id)

        class _Result:
            file_count = 4
            target_directory = "/tmp/ws/deploy"

        return _Result()


def _workspace(tmp_path: Path) -> WorkspaceRecord:
    root = tmp_path / "panzhihua_dev_workforce"
    ensure = root / "deploy" / "host-runtime"
    ensure.mkdir(parents=True)
    (ensure / "ensure.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    now = datetime.now(UTC)
    return WorkspaceRecord(
        id="b9ce65eddc27437d9615177fbd07cb0a",
        name="攀枝花开发工作空间",
        workspace_type="公司项目",
        root_path=str(root),
        created_at=now,
        updated_at=now,
    )


def _service(
    tmp_path: Path,
) -> tuple[ManagedScriptsService, InMemoryLaunchAgentStore, _FakeSharedFiles]:
    record = _workspace(tmp_path)
    workspaces = InMemoryWorkspaceRepository()
    workspaces.create_workspace(
        workspace_id=record.id,
        name=record.name,
        workspace_type=record.workspace_type,
        root_path=record.root_path,
    )
    settings = Settings(runtime_root=tmp_path / "runtime")
    mapping = LocalWorkspaceMappingService(settings)
    shared = _FakeSharedFiles()
    launch = InMemoryLaunchAgentStore()
    service = ManagedScriptsService(
        settings=settings,
        repository=InMemoryManagedScriptRepository(),
        workspaces=workspaces,
        local_mapping=mapping,
        shared_files=shared,  # type: ignore[arg-type]
        launch_agents=launch,
        repo_root=Path(__file__).resolve().parents[2],
    )
    return service, launch, shared


def test_catalog_seeds_boot_and_global_scripts(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    listing = service.list_scripts()
    slugs = {item.slug for item in listing.scripts}
    assert "context-router-native-stack" not in slugs
    assert "sync-workspace-files" not in slugs
    assert "panzhihua-host-runtime" in slugs
    assert "shared-config-center" in slugs
    assert "personal-utils" in slugs
    assert "sync-workspace-scripts" in slugs
    assert "sync-workspace-deploy" in slugs
    assert "sync-workspace-docs" in slugs
    boot = next(item for item in listing.scripts if item.slug == "panzhihua-host-runtime")
    assert boot.kind == "autostart"
    assert boot.autostart_enabled is False
    assert boot.available is True
    shared = next(item for item in listing.scripts if item.slug == "shared-config-center")
    assert shared.kind == "autostart"
    assert shared.autostart_enabled is True
    assert shared.available is True
    assert shared.command_path.endswith("ensure-shared-config-center.sh")
    utils = next(item for item in listing.scripts if item.slug == "personal-utils")
    assert utils.kind == "autostart"
    assert utils.autostart_enabled is True
    assert utils.available is True
    assert utils.command_path.endswith("ensure-personal-utils.sh")


def test_retired_native_stack_is_removed_from_list(tmp_path: Path) -> None:
    service, launch, _ = _service(tmp_path)
    now = datetime.now(UTC)
    service._repository.insert(
        ManagedScriptRecord(
            id="retired-native",
            slug="context-router-native-stack",
            name="Context Router Native Stack",
            description="登录后启动本机查看台前后端和 Host Runner。",
            kind="autostart",
            action_key="native_stack_start",
            workspace_id=None,
            autostart_enabled=True,
            sort_order=10,
            created_at=now,
            updated_at=now,
        )
    )
    launch.installed["context-router-native-stack"] = ("/tmp", "start")
    slugs = {item.slug for item in service.list_scripts().scripts}
    assert "context-router-native-stack" not in slugs
    assert "context-router-native-stack" not in launch.installed


def test_autostart_toggle_binds_context_router_start_without_login_item(tmp_path: Path) -> None:
    service, launch, _ = _service(tmp_path)
    boot = next(
        item for item in service.list_scripts().scripts if item.slug == "panzhihua-host-runtime"
    )
    launch.installed[boot.slug] = ("/tmp", "ensure")
    enabled = service.set_autostart(boot.id, True)
    assert enabled.autostart_enabled is True
    assert enabled.autostart_installed is True
    assert boot.slug not in launch.installed
    disabled = service.set_autostart(boot.id, False)
    assert disabled.autostart_enabled is False
    assert disabled.autostart_installed is False
    assert boot.slug not in launch.installed


def test_shared_config_autostart_writes_follow_flag(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    script = next(
        item for item in service.list_scripts().scripts if item.slug == "shared-config-center"
    )
    flag = tmp_path / "runtime" / "managed-scripts" / "shared-config-center.follow"
    assert flag.read_text(encoding="utf-8").strip() == "1"
    assert service.follows_shared_config() is True
    service.set_autostart(script.id, False)
    assert flag.read_text(encoding="utf-8").strip() == "0"
    assert service.follows_shared_config() is False


def test_personal_utils_autostart_writes_follow_flag(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    script = next(
        item for item in service.list_scripts().scripts if item.slug == "personal-utils"
    )
    flag = tmp_path / "runtime" / "managed-scripts" / "personal-utils.follow"
    assert flag.read_text(encoding="utf-8").strip() == "1"
    assert service.follows_personal_utils() is True
    service.set_autostart(script.id, False)
    assert flag.read_text(encoding="utf-8").strip() == "0"
    assert service.follows_personal_utils() is False


def test_catalog_refresh_uninstalls_leftover_login_item_and_preserves_flag(
    tmp_path: Path,
) -> None:
    service, launch, _ = _service(tmp_path)
    boot = next(
        item for item in service.list_scripts().scripts if item.slug == "panzhihua-host-runtime"
    )
    enabled = service.set_autostart(boot.id, True)
    current = service._repository.get(enabled.id)
    assert current is not None
    service._repository._items[current.id] = replace(current, description="旧描述")
    launch.installed[boot.slug] = ("/tmp", "ensure")
    refreshed = next(
        item for item in service.list_scripts().scripts if item.slug == "panzhihua-host-runtime"
    )
    assert refreshed.autostart_enabled is True
    assert "也不随电脑开机" in refreshed.description
    assert boot.slug not in launch.installed


def test_global_script_runs_selected_workspace(tmp_path: Path) -> None:
    service, _, shared = _service(tmp_path)
    listing = service.list_scripts()
    script = next(item for item in listing.scripts if item.action_key == ACTION_SYNC_SCRIPTS)
    docs = next(item for item in listing.scripts if item.action_key == ACTION_SYNC_DOCUMENTS)
    workspace_id = listing.workspaces[0].id
    result = service.run(script.id, workspace_id)
    assert result.workspace_id == workspace_id
    assert shared.synced == [workspace_id]
    docs_result = service.run(docs.id, workspace_id)
    assert docs_result.workspace_id == workspace_id
    assert shared.documents == [workspace_id]
    with pytest.raises(ManagedScriptsError, match="请选择"):
        service.run(script.id, None)
