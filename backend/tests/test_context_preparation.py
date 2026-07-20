from pathlib import Path

from context_router.config import Settings
from context_router.services.context_preparation import ContextPreparationService
from context_router.services.project_registry import ProjectRegistry


class FakeTaskRepository:
    def __init__(self) -> None:
        self.next_id = 40
        self.created: list[dict[str, object]] = []

    def create_task(self, **values: object) -> int:
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
    assert payload["project"]["node_count"] == 2
    assert payload["documents"]["path"] == "AGENTS.md"
    assert payload["documents"]["summary"] == "提供项目的完整文档导航。"
    child = payload["documents"]["children"][0]
    assert child["path"] == "docs/details.md"
    assert "summary" not in child
    assert "content" not in str(payload)
    assert repository.created[0]["agent_name"] == "codex"


def test_preview_uses_same_result_shape(tmp_path: Path) -> None:
    registry, project_id = build_registry(tmp_path)
    repository = FakeTaskRepository()
    service = ContextPreparationService(registry, repository)

    payload = service.prepare_for_project(project_id).model_dump(exclude_none=True)

    assert payload["task_id"] == 41
    assert payload["project"]["project_id"] == project_id
    assert payload["documents"]["children"][0]["title"] == "详情"
    assert repository.created[0]["agent_name"] == "web-preview"
