from pathlib import Path

import pytest

from context_router.config import Settings
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
