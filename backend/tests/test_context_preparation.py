from datetime import UTC, datetime
from pathlib import Path

import pytest

from context_router.config import Settings
from context_router.repositories.database_environment_repository import (
    DatabaseEnvironmentConfigRecord,
    WorkspaceEnvironmentRecord,
)
from context_router.repositories.mcp_environment_default_repository import (
    InMemoryMcpEnvironmentDefaultRepository,
)
from context_router.repositories.task_repository import TaskRecord
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

    def get_task(self, task_id: int) -> TaskRecord:
        values = self.created[task_id - 41]
        return TaskRecord(
            id=task_id,
            project_id=values.get("active_project_id"),  # type: ignore[arg-type]
            project_key=str(values["workspace_key"]),
            project_name=str(values["workspace_name"]),
            task=str(values["task"]),
            cwd=str(values["cwd"]),
            agent_name=values.get("agent_name"),  # type: ignore[arg-type]
            created_at=datetime.now(UTC),
            scope="workspace",
            workspace_id=str(values["workspace_id"]),
            workspace_key=str(values["workspace_key"]),
            workspace_name=str(values["workspace_name"]),
            active_project_id=values.get("active_project_id"),  # type: ignore[arg-type]
            active_project_name=values.get("active_project_name"),  # type: ignore[arg-type]
            active_project_kind=values.get("active_project_kind"),  # type: ignore[arg-type]
            database_environment=values.get("database_environment"),  # type: ignore[arg-type]
            database_environment_revision=values.get(  # type: ignore[arg-type]
                "database_environment_revision"
            ),
            database_environment_selection=values.get(  # type: ignore[arg-type]
                "database_environment_selection"
            ),
        )


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
            active_environment="uat",
            revision=8,
        )

    def list_workspace_environments(self, workspace_id: str) -> list[WorkspaceEnvironmentRecord]:
        return [
            WorkspaceEnvironmentRecord(
                workspace_id=workspace_id,
                key="local",
                display_name="LOCAL",
                aliases=("local", "本地", "本地环境"),
                sort_order=0,
                is_default=True,
            ),
            WorkspaceEnvironmentRecord(
                workspace_id=workspace_id,
                key="test",
                display_name="TEST",
                aliases=("test", "测试", "测试环境"),
                sort_order=10,
                is_default=False,
            ),
            WorkspaceEnvironmentRecord(
                workspace_id=workspace_id,
                key="uat",
                display_name="UAT",
                aliases=("uat", "验收", "预发布环境"),
                sort_order=20,
                is_default=False,
            ),
        ]

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
    grandchild = tmp_path / "project" / "docs" / "deep" / "AGENTS.md"
    great_grandchild = tmp_path / "project" / "docs" / "deep" / "implementation.md"
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
    write_document(
        child,
        """---
title: 详情
---

## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 深层说明 | `./deep/AGENTS.md` |
""",
    )
    write_document(
        grandchild,
        """---
title: 深层说明
---

## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 实现细节 | `./implementation.md` |
""",
    )
    write_document(great_grandchild, "---\ntitle: 实现细节\n---\n")

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


def test_prepare_returns_only_compact_tree_and_task_capabilities(tmp_path: Path) -> None:
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
    assert set(payload) == {
        "task_id",
        "documents",
        "execution_contract",
        "access",
        "warnings",
    }
    assert payload["access"] == [
        "documents",
        "database",
        "environment",
        "middleware",
        "runtime",
    ]
    project_root = payload["documents"]
    assert set(project_root) == {"document_id", "summary", "children"}
    assert project_root["summary"] == "提供项目的完整文档导航。"
    child = project_root["children"][0]
    assert set(child) == {"document_id", "summary", "children"}
    assert child["summary"] == "详情"
    grandchild = child["children"][0]
    assert grandchild["summary"] == "深层说明"
    assert grandchild["children"] == []
    assert "实现细节" not in str(payload)
    assert "content" not in str(payload)
    assert repository.created[0]["agent_name"] == "codex"
    assert repository.created[0]["active_project_id"] is not None
    assert payload["execution_contract"]["intent_type"] == "task_execute"
    assert payload["execution_contract"]["intent_source"] == "compatibility_default"
    assert payload["execution_contract"]["mutation_policy"] == "allowed"
    assert "未声明 intent_type" in payload["warnings"][0]
    workspace_id = str(repository.created[0]["workspace_id"])
    assert repository.created[0]["workspace_key"] == registry.get_workspace_key(workspace_id)


def test_prepare_persists_declared_bug_investigation_contract(tmp_path: Path) -> None:
    registry, _ = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(registry, repository)

    result = service.prepare(
        task="只查询 UAT 服务报错，不修改代码",
        cwd=str(tmp_path / "project" / "src"),
        agent_name="codex",
        intent_type="bug_investigate",
        error_signal=True,
        intent_summary="只查询报错原因",
    )

    assert result.execution_contract.intent_type == "bug_investigate"
    assert result.execution_contract.mutation_policy == "forbidden"
    assert result.execution_contract.visualization_targets == ["task", "log"]
    assert result.warnings is None
    assert repository.created[0]["intent_type"] == "bug_investigate"
    assert repository.created[0]["intent_error_signal"] is True
    assert repository.created[0]["intent_source"] == "agent_declared"


def test_interface_search_contract_is_read_only_and_progressive(tmp_path: Path) -> None:
    registry, _ = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(registry, repository)

    result = service.prepare(
        task="查找并比较批量查询货物的接口，不执行",
        cwd=str(tmp_path / "project" / "src"),
        agent_name="codex",
        intent_type="interface_search",
        intent_summary="只定位最符合语义的接口",
    )

    contract = result.execution_contract
    assert contract.intent_type == "interface_search"
    assert contract.mutation_policy == "forbidden"
    assert contract.required_steps == ["search_forwarding_interfaces"]
    instructions = " ".join(contract.instructions)
    assert "compare_forwarding_interfaces" in instructions
    assert "read_forwarding_interface_detail" in instructions
    assert "不得准备或执行接口请求" in instructions
    assert repository.created[0]["intent_type"] == "interface_search"


def test_data_query_contract_prefers_direct_mapping_random_selection(tmp_path: Path) -> None:
    registry, _ = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(registry, repository)

    result = service.prepare(
        task="随机查询一个 UAT 货主信息",
        cwd=str(tmp_path / "project" / "src"),
        agent_name="gemini",
        intent_type="data_query",
        intent_summary="随机查询一条货主信息",
    )

    instructions = " ".join(result.execution_contract.instructions)
    assert "selection=random" in instructions
    assert "ORDER BY RAND()" in instructions
    assert "命中映射时不要" in instructions
    assert "没有合适的已发布映射时，才调用 read_task_context" in instructions


def test_workspace_preview_uses_same_result_shape(tmp_path: Path) -> None:
    registry, project_id = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(registry, repository)
    workspace_id = registry.get_project_summary(project_id).workspace_id
    assert workspace_id is not None

    payload = service.prepare_for_workspace(workspace_id).model_dump(exclude_none=True)

    assert payload["task_id"] == 41
    assert payload["documents"]["children"][0]["summary"] == "详情"
    assert payload["documents"]["children"][0]["children"][0]["summary"] == "深层说明"
    assert payload["documents"]["children"][0]["children"][0]["children"] == []
    assert "workspace" not in payload
    assert "projects" not in payload
    assert repository.created[0]["agent_name"] == "web-preview"


def test_environment_and_database_context_are_loaded_only_when_requested(tmp_path: Path) -> None:
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

    assert "databases" not in payload
    assert payload["environment"] == {
        "key": "local",
        "name": "LOCAL",
        "revision": 8,
        "selection": "workspace_default",
    }
    assert database_service.payload_calls == []
    assert database_service.database_calls == []

    context = service.read_task_context(
        task_id=payload["task_id"],
        sections=["databases", "environment"],
    ).model_dump(exclude_none=True)

    assert context["databases"] == []
    assert context["environment"]["selected"] == {
        "key": "local",
        "name": "LOCAL",
        "revision": 8,
        "selection": "workspace_default",
    }
    assert context["environment"]["config"] == {
        "mq": {"nameServer": "local-mq:9876"},
        "es": {"endpoint": "http://local-es:9200"},
    }
    assert repository.created[0]["database_environment"] == "local"
    assert repository.created[0]["database_environment_revision"] == 8
    assert repository.created[0]["database_environment_selection"] == "workspace_default"
    assert database_service.payload_calls == [
        {"environment": "local", "selection": "workspace_default"}
    ]
    assert database_service.database_calls == [
        {
            "database_environment": "local",
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

    prepared = service.prepare(
        task="检查 TEST 环境",
        cwd=str(tmp_path / "project"),
        environment="test",
    ).model_dump(exclude_none=True)

    assert prepared["environment"] == {
        "key": "test",
        "name": "TEST",
        "revision": 8,
        "selection": "task_explicit",
    }
    context = service.read_task_context(
        task_id=prepared["task_id"],
        sections=["environment"],
    ).model_dump(exclude_none=True)
    assert context["environment"]["selected"] == {
        "key": "test",
        "name": "TEST",
        "revision": 8,
        "selection": "task_explicit",
    }
    assert context["environment"]["config"]["mq"]["nameServer"] == "test-mq:9876"
    assert repository.created[0]["database_environment"] == "test"
    assert repository.created[0]["database_environment_selection"] == "task_explicit"
    assert database_service.payload_calls == [{"environment": "test", "selection": "task_explicit"}]
    assert database_service.database_calls == []
    assert (
        database_service.get_active_workspace_environment(
            str(repository.created[0]["workspace_id"])
        ).active_environment
        == "uat"
    )


def test_prepare_detects_registered_environment_alias_from_task_description(
    tmp_path: Path,
) -> None:
    registry, _ = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(
        registry,
        repository,
        FakeDatabaseAccessService(),  # type: ignore[arg-type]
    )

    prepared = service.prepare(
        task="查询预发布环境的委托订单",
        cwd=str(tmp_path / "project"),
    )

    assert prepared.environment is not None
    assert prepared.environment.key == "uat"
    assert prepared.environment.selection == "task_description"
    assert repository.created[0]["database_environment"] == "uat"
    assert repository.created[0]["database_environment_selection"] == "task_description"


def test_prepare_rejects_conflicting_environment_intent(tmp_path: Path) -> None:
    registry, _ = build_registry(tmp_path)
    service = ContextPreparationService(
        registry,
        FakeTaskRepository(),
        FakeDatabaseAccessService(),  # type: ignore[arg-type]
    )

    with pytest.raises(ContextPreparationError) as caught:
        service.prepare(
            task="查询 UAT 环境的委托订单",
            cwd=str(tmp_path / "project"),
            environment="test",
        )

    assert caught.value.code == "environment_intent_conflict"


def test_prepare_ignores_removed_per_tool_default_when_environment_is_omitted(
    tmp_path: Path,
) -> None:
    registry, project_id = build_registry(tmp_path)
    repository = FakeTaskRepository()
    database_service = FakeDatabaseAccessService()
    defaults = InMemoryMcpEnvironmentDefaultRepository()
    workspace_id = registry.get_project_summary(project_id).workspace_id
    assert workspace_id is not None
    defaults.upsert_default(
        workspace_id=workspace_id,
        tool_name="prepare_task_context",
        environment="test",
    )
    service = ContextPreparationService(
        registry,
        repository,
        database_service,  # type: ignore[arg-type]
        defaults,
    )

    prepared = service.prepare(
        task="检查默认环境",
        cwd=str(tmp_path / "project"),
    )

    assert prepared.task_id == 41
    assert repository.created[0]["database_environment"] == "local"
    assert repository.created[0]["database_environment_selection"] == "workspace_default"


def test_prepare_uses_local_as_the_registered_initial_default(
    tmp_path: Path,
) -> None:
    registry, _ = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(
        registry,
        repository,
        FakeDatabaseAccessService(),  # type: ignore[arg-type]
        InMemoryMcpEnvironmentDefaultRepository(),
    )

    service.prepare(task="检查系统初始默认", cwd=str(tmp_path / "project"))

    assert repository.created[0]["database_environment"] == "local"
    assert repository.created[0]["database_environment_selection"] == "workspace_default"


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
