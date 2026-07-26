from datetime import UTC, datetime
from pathlib import Path

import pytest

from context_router.config import Settings
from context_router.repositories.document_search_repository import (
    InMemoryDocumentSearchRepository,
)
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.task_repository import TaskRecord
from context_router.repositories.workspace_repository import InMemoryWorkspaceRepository
from context_router.schemas.context import ContextDocumentReadRequest
from context_router.services.context_document_read import ContextDocumentReadService
from context_router.services.context_document_search import ContextDocumentSearchService
from context_router.services.context_preparation import ContextPreparationService
from context_router.services.document_search_index import DocumentSearchIndexer
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError


class FakeWorkspaceTaskRepository:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.task: TaskRecord | None = None

    def create_workspace_task(self, **values: object) -> int:
        self.created.append(values)
        self.task = TaskRecord(
            id=51,
            project_id=values.get("active_project_id"),  # type: ignore[arg-type]
            project_key=str(values["workspace_key"]),
            project_name=str(values.get("active_project_name") or values["workspace_name"]),
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
        )
        return 51

    def get_task(self, task_id: int) -> TaskRecord:
        assert task_id == 51
        assert self.task is not None
        return self.task


class FakeReadRepository:
    def create_read_call(self, *, task_id: int, items: object, **_: object) -> int:
        assert task_id == 51
        assert items
        return 61


def _write_agents(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_workspace_task_aggregates_project_documents_and_routes_by_workspace(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "workspace"
    _write_agents(
        root_path / "AGENTS.md",
        """# 前端入口

frontend marker

## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 后端入口 | `./server/AGENTS.md` |
""",
    )
    _write_agents(
        root_path / "server" / "AGENTS.md",
        "# 后端入口\n\nworkspace backend needle",
    )
    _write_agents(
        root_path / "worker" / "AGENTS.md",
        "# 后台任务入口\n\nworkspace worker needle",
    )

    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace-id",
        name="测试工作空间",
        workspace_type="公司项目",
        root_path=str(root_path),
        enabled=True,
    )
    project_repository = InMemoryProjectRepository(workspace_repository)
    search_repository = InMemoryDocumentSearchRepository()
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        ),
        project_repository,
        DocumentSearchIndexer(search_repository),
    )
    workspace = workspace_repository.get_workspace("workspace-id")
    registry.register_workspace(workspace)
    frontend = registry.add_workspace_project(
        workspace,
        name="前端",
        relative_path=".",
        project_kind="frontend",
    )
    backend = registry.add_workspace_project(
        workspace,
        name="后端",
        relative_path="server",
        project_kind="backend",
    )
    worker = registry.add_workspace_project(
        workspace,
        name="后台任务",
        relative_path="worker",
        project_kind="backend",
    )

    task_repository = FakeWorkspaceTaskRepository()
    preparation = ContextPreparationService(registry, task_repository)
    prepared = preparation.prepare(
        task="开发接口",
        cwd=str(root_path / "server" / "src"),
        agent_name="codex",
    )

    assert prepared.workspace.workspace_id == "workspace-id"
    assert {project.project_id for project in prepared.projects} == {
        frontend.id,
        backend.id,
        worker.id,
    }
    assert prepared.active_project is not None
    assert prepared.active_project.project_id == backend.id
    assert [node.path for node in prepared.documents.children] == ["server/AGENTS.md"]
    tree_ids = [
        prepared.documents.document_id,
        *[node.document_id for node in prepared.documents.children],
    ]
    assert len(tree_ids) == len(set(tree_ids))
    assert task_repository.created[0]["workspace_id"] == "workspace-id"

    searched = ContextDocumentSearchService(
        registry,
        task_repository,
        search_repository,
    ).search(task_id=prepared.task_id, query="worker needle")
    worker_result = next(result for result in searched.results if result.path == "worker/AGENTS.md")
    assert worker_result.document_id not in tree_ids

    document_id = worker_result.document_id
    read = ContextDocumentReadService(
        registry,
        task_repository,
        FakeReadRepository(),
    ).read(
        task_id=prepared.task_id,
        requests=[ContextDocumentReadRequest(document_id=document_id)],
    )
    assert read.documents[0].content is not None
    assert "workspace worker needle" in read.documents[0].content

    (root_path / "server" / "AGENTS.md").unlink()
    with pytest.raises(ProjectRegistryError, match="已保留上一版映射"):
        registry.refresh_workspace("workspace-id")
    retained = registry.get_workspace_snapshot("workspace-id")
    assert "workspace worker needle" in retained.cache.documents[document_id].content


def test_workspace_document_entry_works_without_projects(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "workspace"
    _write_agents(
        root_path / "AGENTS.md",
        """---
title: 工作空间开发索引
summary: 汇总前后端服务文档和业务链路。
---

# 工作空间开发索引

workspace-only-search-needle

## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 登录链路 | `./docs/login.md` |
""",
    )
    _write_agents(
        root_path / "docs" / "login.md",
        "# 登录链路\n\nlogin-chain-search-needle",
    )

    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace-only",
        name="仅工作空间文档",
        workspace_type="公司项目",
        root_path=str(root_path),
        enabled=True,
    )
    search_repository = InMemoryDocumentSearchRepository()
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        ),
        InMemoryProjectRepository(workspace_repository),
        DocumentSearchIndexer(search_repository),
    )
    registry.register_workspace(workspace_repository.get_workspace("workspace-only"))

    task_repository = FakeWorkspaceTaskRepository()
    prepared = ContextPreparationService(registry, task_repository).prepare(
        task="排查登录链路",
        cwd=str(root_path),
        agent_name="codex",
    )

    assert prepared.projects == []
    assert prepared.documents.title == "工作空间开发索引"
    assert len(prepared.documents.children) == 1
    searched = ContextDocumentSearchService(
        registry,
        task_repository,
        search_repository,
    ).search(
        task_id=prepared.task_id,
        query="login-chain-search-needle",
    )
    login_result = next(result for result in searched.results if result.path == "docs/login.md")

    read = ContextDocumentReadService(
        registry,
        task_repository,
        FakeReadRepository(),
    ).read(
        task_id=prepared.task_id,
        requests=[
            ContextDocumentReadRequest(
                document_id=login_result.document_id,
            )
        ],
    )
    assert read.documents[0].content is not None
    assert "login-chain-search-needle" in read.documents[0].content


def test_workspace_without_root_agents_keeps_synthetic_root(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "workspace"
    root_path.mkdir()
    _write_agents(
        root_path / "service" / "AGENTS.md",
        "# 合成根下的服务入口",
    )
    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace-empty",
        name="空工作空间",
        workspace_type="公司项目",
        root_path=str(root_path),
        enabled=True,
    )
    search_repository = InMemoryDocumentSearchRepository()
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        ),
        InMemoryProjectRepository(workspace_repository),
        DocumentSearchIndexer(search_repository),
    )
    workspace = workspace_repository.get_workspace("workspace-empty")
    registry.register_workspace(workspace)
    project = registry.add_workspace_project(
        workspace,
        name="服务项目",
        relative_path="service",
        project_kind="backend",
    )

    snapshot = registry.get_workspace_snapshot("workspace-empty")
    assert snapshot.document_cache is None
    assert [item.id for item in snapshot.projects] == [project.id]
    assert snapshot.cache.root.title == "空工作空间"
    assert [child.id for child in snapshot.cache.root.children] == [
        registry.get_tree(project.id).id
    ]
    assert len(snapshot.cache.documents) == 2
    assert search_repository.get_workspace_index_state("workspace-empty") is None


def test_workspace_refresh_removes_deleted_root_document_index(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "workspace"
    _write_agents(root_path / "AGENTS.md", "# 工作空间\n\nstale-workspace-needle")
    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace-refresh",
        name="刷新工作空间",
        workspace_type="公司项目",
        root_path=str(root_path),
        enabled=True,
    )
    search_repository = InMemoryDocumentSearchRepository()
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        ),
        InMemoryProjectRepository(workspace_repository),
        DocumentSearchIndexer(search_repository),
    )
    registry.register_workspace(workspace_repository.get_workspace("workspace-refresh"))
    assert search_repository.get_workspace_index_state("workspace-refresh") is not None

    (root_path / "AGENTS.md").unlink()
    snapshot = registry.refresh_workspace("workspace-refresh")

    assert snapshot.document_cache is None
    assert snapshot.cache.root.title == "刷新工作空间"
    assert search_repository.get_workspace_index_state("workspace-refresh") is None


def test_workspace_root_agents_symlink_cannot_escape_workspace(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "workspace"
    root_path.mkdir()
    outside = tmp_path / "outside" / "AGENTS.md"
    _write_agents(outside, "# 越界文档")
    (root_path / "AGENTS.md").symlink_to(outside)

    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        )
    )
    with pytest.raises(ProjectRegistryError, match="不能越出工作空间"):
        registry.validate_workspace_document_entry(str(root_path))
