from pathlib import Path

import pytest

from context_router.config import Settings
from context_router.repositories.database_environment_repository import (
    DatabaseEnvironmentConfigRecord,
)
from context_router.services.context_preparation import (
    ContextPreparationError,
    ContextPreparationService,
)
from context_router.services.project_registry import ProjectRegistry


class FakeTaskRepository:
    def __init__(self) -> None:
        self.next_id = 40
        self.created: list[dict[str, object]] = []

    def create_workspace_task(self, **values: object) -> int:
        self.next_id += 1
        self.created.append(values)
        return self.next_id


class FakeDatabaseAccessService:
    def __init__(self) -> None:
        self.payload_calls: list[dict[str, object]] = []
        self.database_calls: list[dict[str, object]] = []

    def get_active_workspace_environment(
        self,
        workspace_id: str,
    ) -> DatabaseEnvironmentConfigRecord:
        return DatabaseEnvironmentConfigRecord(
            workspace_id=workspace_id,
            enabled=True,
            active_environment="uat",
            revision=8,
        )

    def get_active_environment_payload(
        self,
        workspace_id: str,
        *,
        environment: str,
        revision: int,
        database_environment_selection: str,
    ) -> object:
        assert workspace_id
        assert revision == 8
        self.payload_calls.append(
            {
                "environment": environment,
                "selection": database_environment_selection,
            }
        )
        return {
            "mq": {"nameServer": f"{environment}-mq:9876"},
            "es": {"endpoint": f"http://{environment}-es:9200"},
        }

    def list_prepared_workspace_databases(
        self,
        _workspace_id: str,
        **arguments: object,
    ) -> list[object]:
        self.database_calls.append(arguments)
        return []


class FakeUnconfiguredDatabaseAccessService:
    def get_active_workspace_environment(self, _workspace_id: str) -> None:
        return None

    def get_active_environment_payload(self, *_: object, **__: object) -> object:
        raise AssertionError("unconfigured selector must fail before reading payload")

    def list_prepared_workspace_databases(
        self,
        *_: object,
        **__: object,
    ) -> list[object]:
        raise AssertionError("unconfigured selector must fail before listing databases")


def write_document(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_registry(tmp_path: Path) -> tuple[ProjectRegistry, str]:
    root = tmp_path / "project" / "AGENTS.md"
    child = tmp_path / "project" / "docs" / "details.md"
    write_document(
        root,
        """---
title: 项目入口
summary: 提供项目的完整文档导航。
---

## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 详情 | `./docs/details.md` |
""",
    )
    write_document(child, "---\ntitle: 详情\n---\n\n# 不应成为 summary")

    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        )
    )
    project = registry.add_project(name="测试项目", agents_path=str(root))
    return registry, project.id


def test_prepare_returns_complete_tree_and_explicit_metadata(tmp_path: Path) -> None:
    registry, _ = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(registry, repository)

    result = service.prepare(
        task="修复登录问题",
        cwd=str(tmp_path / "project" / "src"),
        agent_name="codex",
    )
    payload = result.model_dump(exclude_none=True)

    assert payload["task_id"] == 41
    assert payload["workspace"]["name"] == "测试项目"
    assert payload["project"]["node_count"] == 2
    assert payload["projects"] == [payload["active_project"]]
    project_root = payload["documents"]
    assert project_root["path"] == "AGENTS.md"
    assert project_root["summary"] == "提供项目的完整文档导航。"
    child = project_root["children"][0]
    assert child["path"] == "docs/details.md"
    assert "summary" not in child
    assert "content" not in str(payload)
    assert repository.created[0]["agent_name"] == "codex"
    assert repository.created[0]["active_project_id"] == payload["project"]["project_id"]
    assert repository.created[0]["workspace_key"] == registry.get_workspace_key(
        payload["workspace"]["workspace_id"]
    )


def test_workspace_preview_uses_same_result_shape(tmp_path: Path) -> None:
    registry, project_id = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(registry, repository)
    workspace_id = registry.get_project_summary(project_id).workspace_id
    assert workspace_id is not None

    payload = service.prepare_for_workspace(workspace_id).model_dump(exclude_none=True)

    assert payload["task_id"] == 41
    assert payload["workspace"]["workspace_id"] == workspace_id
    assert payload["projects"][0]["project_id"] == project_id
    assert payload["documents"]["children"][0]["title"] == "详情"
    assert "project" not in payload
    assert repository.created[0]["agent_name"] == "web-preview"


def test_prepare_returns_only_explicit_active_environment_json(tmp_path: Path) -> None:
    registry, _ = build_registry(tmp_path)
    repository = FakeTaskRepository()
    database_service = FakeDatabaseAccessService()
    service = ContextPreparationService(
        registry,
        repository,
        database_service,  # type: ignore[arg-type]
    )

    payload = service.prepare(
        task="检查环境配置",
        cwd=str(tmp_path / "project"),
    ).model_dump(exclude_none=True)

    assert payload["database_environment"] == {
        "key": "uat",
        "name": "UAT",
        "revision": 8,
        "selection": "workspace_default",
    }
    assert payload["environment_config"] == {
        "mq": {"nameServer": "uat-mq:9876"},
        "es": {"endpoint": "http://uat-es:9200"},
    }
    assert repository.created[0]["database_environment"] == "uat"
    assert repository.created[0]["database_environment_revision"] == 8
    assert repository.created[0]["database_environment_selection"] == "workspace_default"
    assert database_service.payload_calls == [
        {"environment": "uat", "selection": "workspace_default"}
    ]
    assert database_service.database_calls == [
        {
            "database_environment": "uat",
            "database_environment_revision": 8,
            "database_environment_selection": "workspace_default",
        }
    ]


def test_prepare_can_select_task_environment_without_changing_workspace_default(
    tmp_path: Path,
) -> None:
    registry, _ = build_registry(tmp_path)
    repository = FakeTaskRepository()
    database_service = FakeDatabaseAccessService()
    service = ContextPreparationService(
        registry,
        repository,
        database_service,  # type: ignore[arg-type]
    )

    payload = service.prepare(
        task="检查 TEST 环境",
        cwd=str(tmp_path / "project"),
        environment="test",
    ).model_dump(exclude_none=True)

    assert payload["database_environment"] == {
        "key": "test",
        "name": "TEST",
        "revision": 8,
        "selection": "task_explicit",
    }
    assert payload["environment_config"]["mq"]["nameServer"] == "test-mq:9876"
    assert repository.created[0]["database_environment"] == "test"
    assert repository.created[0]["database_environment_selection"] == "task_explicit"
    assert database_service.payload_calls == [{"environment": "test", "selection": "task_explicit"}]
    assert database_service.database_calls[0]["database_environment_selection"] == "task_explicit"
    assert (
        database_service.get_active_workspace_environment(
            payload["workspace"]["workspace_id"]
        ).active_environment
        == "uat"
    )


def test_prepare_rejects_explicit_environment_without_workspace_selector(
    tmp_path: Path,
) -> None:
    registry, _ = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(
        registry,
        repository,
        FakeUnconfiguredDatabaseAccessService(),  # type: ignore[arg-type]
    )

    with pytest.raises(ContextPreparationError) as caught:
        service.prepare(
            task="检查 TEST 环境",
            cwd=str(tmp_path / "project"),
            environment="test",
        )

    assert caught.value.code == "environment_not_configured"
    assert repository.created == []


def test_prepare_failure_after_task_creation_preserves_task_id_for_tracing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _ = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(registry, repository)

    def fail_tree(*_: object) -> None:
        raise RuntimeError("tree serialization failed")

    monkeypatch.setattr(service, "_context_node", fail_tree)

    with pytest.raises(ContextPreparationError) as caught:
        service.prepare(
            task="触发准备失败",
            cwd=str(tmp_path / "project"),
            agent_name="codex",
        )

    assert caught.value.task_id == 41
    assert caught.value.code == "context_preparation_failed"
