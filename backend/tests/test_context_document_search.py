from datetime import UTC, datetime
from pathlib import Path

import pytest

from context_router.config import Settings
from context_router.repositories.document_search_repository import (
    InMemoryDocumentSearchRepository,
)
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.task_repository import (
    TaskRecord,
    TaskRepositoryError,
)
from context_router.services.context_document_search import (
    ContextDocumentSearchError,
    ContextDocumentSearchService,
)
from context_router.services.document_search_index import DocumentSearchIndexer
from context_router.services.project_registry import ProjectRegistry


class StaticTaskRepository:
    def __init__(self, task: TaskRecord) -> None:
        self._task = task

    def get_task(self, task_id: int) -> TaskRecord:
        if task_id != self._task.id:
            raise TaskRepositoryError("任务不存在")
        return self._task


def _write_document(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _task_for(registry: ProjectRegistry, project_id: str, *, task_id: int = 1) -> TaskRecord:
    return TaskRecord(
        id=task_id,
        project_id=project_id,
        project_key=registry.get_project_key(project_id),
        project_name="测试项目",
        task="查找文档",
        cwd="/workspace/project",
        agent_name="codex",
        created_at=datetime.now(UTC),
    )


def _registry(
    tmp_path: Path,
    search_repository: InMemoryDocumentSearchRepository,
) -> ProjectRegistry:
    return ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        ),
        InMemoryProjectRepository(),
        DocumentSearchIndexer(search_repository),
    )


def test_search_is_task_bound_and_returns_metadata_without_markdown_body(
    tmp_path: Path,
) -> None:
    search_repository = InMemoryDocumentSearchRepository()
    registry = _registry(tmp_path, search_repository)
    first_root = tmp_path / "first" / "AGENTS.md"
    second_root = tmp_path / "second" / "AGENTS.md"
    _write_document(
        first_root,
        "---\n"
        "title: 数据库迁移手册\n"
        "summary: 说明 PostgreSQL migration 的执行方式。\n"
        "---\n"
        "# Docker 操作\n"
        "使用 docker compose 执行 alembic upgrade head。\n",
    )
    _write_document(second_root, "# 私有说明\n仅第二个项目包含 secret-marker。\n")
    first = registry.add_project(name="第一个项目", agents_path=str(first_root))
    registry.add_project(name="第二个项目", agents_path=str(second_root))
    service = ContextDocumentSearchService(
        registry,
        StaticTaskRepository(_task_for(registry, first.id)),
        search_repository,
    )

    result = service.search(task_id=1, query="PostgreSQL migration", limit=10)

    assert result.returned_count == 1
    assert result.results[0].title == "数据库迁移手册"
    assert result.results[0].summary == "说明 PostgreSQL migration 的执行方式。"
    assert result.results[0].path == "AGENTS.md"
    assert result.results[0].matched_sections
    assert "content" not in result.results[0].model_dump()
    assert service.search(task_id=1, query="secret-marker").results == []


def test_refresh_atomically_replaces_the_searchable_cache_version(tmp_path: Path) -> None:
    search_repository = InMemoryDocumentSearchRepository()
    registry = _registry(tmp_path, search_repository)
    root = tmp_path / "project" / "AGENTS.md"
    _write_document(root, "# 运行\n旧启动标识 abcdefghijklmno\n")
    project = registry.add_project(name="测试项目", agents_path=str(root))
    service = ContextDocumentSearchService(
        registry,
        StaticTaskRepository(_task_for(registry, project.id)),
        search_repository,
    )
    assert service.search(task_id=1, query="abcdefghijklmno").returned_count == 1

    _write_document(root, "# 运行\n新启动标识 pqrstuvwxyz01234\n")
    registry.refresh_project(project.id)

    assert service.search(task_id=1, query="abcdefghijklmno").results == []
    assert service.search(task_id=1, query="pqrstuvwxyz01234").returned_count == 1


def test_search_rejects_missing_or_stale_index_without_memory_fallback(
    tmp_path: Path,
) -> None:
    search_repository = InMemoryDocumentSearchRepository()
    root = tmp_path / "project" / "AGENTS.md"
    _write_document(root, "# 文档\n不会走内存兜底\n")
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        ),
        InMemoryProjectRepository(),
    )
    project = registry.add_project(name="测试项目", agents_path=str(root))
    service = ContextDocumentSearchService(
        registry,
        StaticTaskRepository(_task_for(registry, project.id)),
        search_repository,
    )

    with pytest.raises(ContextDocumentSearchError) as error:
        service.search(task_id=1, query="内存")

    assert error.value.code == "document_search_index_not_ready"


@pytest.mark.parametrize(
    ("task_id", "query", "limit", "code"),
    [
        (0, "文档", 10, "invalid_task_id"),
        (1, "   ", 10, "invalid_search_query"),
        (1, "文档", 0, "invalid_search_limit"),
        (1, "文档", 51, "invalid_search_limit"),
    ],
)
def test_search_validates_public_input(
    tmp_path: Path,
    task_id: int,
    query: str,
    limit: int,
    code: str,
) -> None:
    search_repository = InMemoryDocumentSearchRepository()
    root = tmp_path / "project" / "AGENTS.md"
    _write_document(root, "# 文档\n")
    registry = _registry(tmp_path, search_repository)
    project = registry.add_project(name="测试项目", agents_path=str(root))
    service = ContextDocumentSearchService(
        registry,
        StaticTaskRepository(_task_for(registry, project.id)),
        search_repository,
    )

    with pytest.raises(ContextDocumentSearchError) as error:
        service.search(task_id=task_id, query=query, limit=limit)

    assert error.value.code == code
