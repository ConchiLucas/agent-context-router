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
        """# 工作空间入口

        ## 下级文档

        | 功能说明 | 相对路径 |
        | --- | --- |
        | 前端入口 | `./docs/frontend/root/AGENTS.md` |
        """,
    )
    _write_agents(
        root_path / "docs" / "frontend" / "root" / "AGENTS.md",
        "# 前端入口\n\nfrontend marker",
    )
    _write_agents(
        root_path / "docs" / "backend" / "server" / "AGENTS.md",
        "# 后端入口\n\nworkspace backend needle",
    )
    _write_agents(
        root_path / "docs" / "backend" / "worker" / "AGENTS.md",
        "# 后台任务入口\n\nworkspace worker needle",
    )
    (root_path / "server").mkdir()
    (root_path / "worker").mkdir()

    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace-id",
        name="测试工作空间",
        workspace_type="公司项目",
        root_path=str(root_path),
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
    registry.add_workspace_project(
        workspace,
        name="前端",
        relative_path=".",
        document_relative_path="docs/frontend/root/AGENTS.md",
        project_kind="frontend",
    )
    backend = registry.add_workspace_project(
        workspace,
        name="后端",
        relative_path="server",
        document_relative_path="docs/backend/server/AGENTS.md",
        project_kind="backend",
    )
    registry.add_workspace_project(
        workspace,
        name="后台任务",
        relative_path="worker",
        document_relative_path="docs/backend/worker/AGENTS.md",
        project_kind="backend",
    )

    task_repository = FakeWorkspaceTaskRepository()
    preparation = ContextPreparationService(registry, task_repository)
    prepared = preparation.prepare(
        task="开发接口",
        cwd=str(root_path / "server" / "src"),
        agent_name="codex",
    )

    assert prepared.access == [
        "documents",
        "database",
        "environment",
        "middleware",
        "runtime",
    ]
    workspace_snapshot = registry.get_workspace_snapshot("workspace-id")
    assert workspace_snapshot.document_cache is not None
    assert prepared.documents.document_id == workspace_snapshot.document_cache.root.id
    assert prepared.documents.summary == "工作空间文档入口"
    assert [node.summary for node in prepared.documents.children] == ["前端入口"]
    tree_ids = [
        prepared.documents.document_id,
        *[node.document_id for node in prepared.documents.children],
    ]
    assert len(tree_ids) == len(set(tree_ids))
    assert task_repository.created[0]["workspace_id"] == "workspace-id"
    assert task_repository.created[0]["active_project_id"] == backend.id

    searched = ContextDocumentSearchService(
        registry,
        task_repository,
        search_repository,
    ).search(task_id=prepared.task_id, query="worker needle")
    worker_result = next(
        result for result in searched.results if result.path == "docs/backend/worker/AGENTS.md"
    )
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

    (root_path / "docs" / "backend" / "server" / "AGENTS.md").unlink()
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

    assert prepared.documents.summary == "汇总前后端服务文档和业务链路。"
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
        root_path / "docs" / "backend" / "service" / "AGENTS.md",
        "# 合成根下的服务入口",
    )
    (root_path / "service").mkdir()
    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace-empty",
        name="空工作空间",
        workspace_type="公司项目",
        root_path=str(root_path),
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
        document_relative_path="docs/backend/service/AGENTS.md",
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

    prepared = ContextPreparationService(
        registry,
        FakeWorkspaceTaskRepository(),
    ).prepare(
        task="开发服务接口",
        cwd=str(root_path / "service" / "src"),
        agent_name="codex",
    )
    assert prepared.documents.document_id == registry.get_tree(project.id).id


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


def test_workspace_refresh_collects_all_project_failures_and_retains_caches(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "workspace"
    for project_name in ("alpha", "beta"):
        (root_path / "services" / project_name).mkdir(parents=True)
        _write_agents(
            root_path / "docs" / "backend" / project_name / "AGENTS.md",
            f"# {project_name}",
        )

    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace-failures",
        name="失败聚合工作空间",
        workspace_type="公司项目",
        root_path=str(root_path),
    )
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        ),
        InMemoryProjectRepository(workspace_repository),
    )
    workspace = workspace_repository.get_workspace("workspace-failures")
    registry.register_workspace(workspace)
    projects = [
        registry.add_workspace_project(
            workspace,
            name=project_name,
            relative_path=f"services/{project_name}",
            document_relative_path=f"docs/backend/{project_name}/AGENTS.md",
        )
        for project_name in ("alpha", "beta")
    ]
    retained_document_ids = {project.id: registry.get_tree(project.id).id for project in projects}
    for project_name in ("alpha", "beta"):
        (root_path / "docs" / "backend" / project_name / "AGENTS.md").unlink()

    with pytest.raises(ProjectRegistryError) as raised:
        registry.refresh_workspace("workspace-failures")

    message = str(raised.value)
    assert "alpha" in message
    assert "beta" in message
    for project in projects:
        summary = registry.get_project_summary(project.id)
        assert "找不到入口文件" in (summary.error or "")
        assert registry.get_tree(project.id).id == retained_document_ids[project.id]


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
