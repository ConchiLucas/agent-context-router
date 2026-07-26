import pytest

from context_router.repositories.project_repository import (
    InMemoryProjectRepository,
    ProjectRepositoryError,
)
from context_router.repositories.workspace_repository import (
    InMemoryWorkspaceRepository,
    WorkspaceRepositoryError,
)


def test_workspace_and_projects_share_in_memory_backing_and_legacy_fields() -> None:
    workspaces = InMemoryWorkspaceRepository()
    projects = InMemoryProjectRepository(workspaces)
    workspaces.create_workspace(
        workspace_id="workspace-a",
        name="业务工作空间",
        workspace_type="业务系统",
        root_path="/workspace/company",
        enabled=True,
    )
    projects.create_project(
        project_id="project-a",
        workspace_id="workspace-a",
        relative_path="services/order",
        name="订单服务",
        project_kind="backend",
    )

    project = projects.get_project("project-a")

    assert project.project_type == "业务系统"
    assert project.project_kind == "backend"
    assert project.agents_path == "/workspace/company/services/order/AGENTS.md"
    assert project.workspace_name == "业务工作空间"
    assert project.workspace_root_path == "/workspace/company"
    assert project.workspace_enabled is True

    workspaces.update_workspace(
        "workspace-a",
        name="新工作空间名",
        workspace_type="交通物流",
        root_path="/workspace/new-company",
    )
    updated = projects.get_project("project-a")
    assert updated.project_type == "交通物流"
    assert updated.agents_path == "/workspace/new-company/services/order/AGENTS.md"
    assert updated.workspace_name == "新工作空间名"

    workspaces.set_workspace_enabled("workspace-a", enabled=False)
    assert projects.get_project("project-a").workspace_enabled is False

    workspaces.delete_workspace("workspace-a")
    assert projects.list_projects() == []
    with pytest.raises(ProjectRepositoryError, match="项目不存在"):
        projects.get_project("project-a")


def test_workspace_rejects_duplicate_root_path() -> None:
    repository = InMemoryWorkspaceRepository()
    repository.create_workspace(
        workspace_id="workspace-a",
        name="A",
        root_path="/workspace/shared",
        enabled=True,
    )

    with pytest.raises(WorkspaceRepositoryError, match="工作空间目录已经添加"):
        repository.create_workspace(
            workspace_id="workspace-b",
            name="B",
            root_path="/workspace/shared",
            enabled=True,
        )
