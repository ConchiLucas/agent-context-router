from datetime import UTC, datetime
from pathlib import Path

from context_router.config import Settings
from context_router.repositories.document_read_repository import DocumentReadItemWrite
from context_router.repositories.task_repository import TaskRecord
from context_router.schemas.context import ContextDocumentReadRequest
from context_router.services.context_document_read import ContextDocumentReadService
from context_router.services.project_registry import ProjectRegistry


class FakeTaskRepository:
    def __init__(self, task: TaskRecord) -> None:
        self.task = task

    def get_task(self, task_id: int) -> TaskRecord:
        assert task_id == self.task.id
        return self.task


class FakeReadRepository:
    def __init__(self) -> None:
        self.created: list[tuple[int, list[DocumentReadItemWrite]]] = []

    def create_read_call(
        self,
        *,
        task_id: int,
        items: list[DocumentReadItemWrite],
    ) -> int:
        self.created.append((task_id, items))
        return 91


def build_service(tmp_path: Path) -> tuple[ContextDocumentReadService, ProjectRegistry, str]:
    root = tmp_path / "project" / "AGENTS.md"
    first = tmp_path / "project" / "docs" / "first.md"
    second = tmp_path / "project" / "docs" / "second.md"
    first.parent.mkdir(parents=True)
    root.write_text(
        """---
title: 入口
---

## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 第一份 | `./docs/first.md` |
| 第二份 | `./docs/second.md` |
""",
        encoding="utf-8",
    )
    first.write_text("# 第一份\n\n## 启动\n启动内容\n\n## 测试\n测试内容\n", encoding="utf-8")
    second.write_text("---\ntitle: 第二份\n---\n\n# 第二份正文\n", encoding="utf-8")

    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        )
    )
    project = registry.add_project(name="测试项目", agents_path=str(root))
    snapshot = registry.get_snapshot(project.id)
    task = TaskRecord(
        id=44,
        project_key=snapshot.project_key,
        project_name=project.name,
        task="排查启动问题",
        cwd=str(root.parent),
        agent_name="codex",
        created_at=datetime.now(UTC),
    )
    read_repository = FakeReadRepository()
    service = ContextDocumentReadService(
        registry,
        FakeTaskRepository(task),
        read_repository,
    )
    return service, registry, project.id


def test_reads_multiple_documents_in_request_order(tmp_path: Path) -> None:
    service, registry, project_id = build_service(tmp_path)
    tree = registry.get_tree(project_id)
    first_id = tree.children[0].id
    second_id = tree.children[1].id

    result = service.read(
        task_id=44,
        requests=[
            ContextDocumentReadRequest(document_id=second_id),
            ContextDocumentReadRequest(document_id=first_id, section="启动"),
        ],
    )

    assert result.read_call_id == 91
    assert [item.document_id for item in result.documents] == [second_id, first_id]
    assert [item.position for item in result.documents] == [1, 2]
    assert result.documents[0].path == "docs/second.md"
    assert result.documents[0].content == "---\ntitle: 第二份\n---\n\n# 第二份正文\n"
    assert result.documents[1].content == "## 启动\n启动内容\n"


def test_invalid_document_is_recorded_without_blocking_valid_item(tmp_path: Path) -> None:
    service, registry, project_id = build_service(tmp_path)
    valid_id = registry.get_tree(project_id).children[0].id

    result = service.read(
        task_id=44,
        requests=[
            ContextDocumentReadRequest(document_id="missing"),
            ContextDocumentReadRequest(document_id=valid_id),
        ],
    )

    assert result.documents[0].error is not None
    assert result.documents[0].error.code == "document_not_found"
    assert result.documents[1].content is not None

    repository = service._read_repository  # noqa: SLF001
    _, writes = repository.created[0]  # type: ignore[attr-defined]
    assert [(item.position, item.status) for item in writes] == [(1, "error"), (2, "ok")]
