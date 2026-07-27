import pytest

from context_router.repositories.project_repository import (
    InMemoryProjectRepository,
    ProjectRepositoryError,
)
from context_router.repositories.workspace_repository import InMemoryWorkspaceRepository


def test_legacy_project_create_and_update_maintain_implicit_workspace() -> None:
    projects = InMemoryProjectRepository()
    projects.create_project(
        project_id="legacy-project",
        name="旧项目",
        project_type="公司项目",
        project_kind="frontend",
        agents_path="/workspace/legacy/AGENTS.md",
    )

    workspace = projects.workspace_repository.get_workspace("legacy-project")
    project = projects.get_project("legacy-project")
    assert workspace.id == "legacy-project"
    assert workspace.root_path == "/workspace/legacy"
    assert project.workspace_id == "legacy-project"
    assert project.relative_path == "."
    assert project.agents_path == "/workspace/legacy/AGENTS.md"
    assert project.project_kind == "frontend"

    projects.update_project(
        "legacy-project",
        name="更新项目",
        project_type="交通物流",
        project_kind="backend",
        agents_path="/workspace/moved/AGENTS.md",
    )

    updated_workspace = projects.workspace_repository.get_workspace("legacy-project")
    updated_project = projects.get_project("legacy-project")
    assert updated_workspace.name == "更新项目"
    assert updated_workspace.workspace_type == "交通物流"
    assert updated_workspace.root_path == "/workspace/moved"
    assert updated_project.name == "更新项目"
    assert updated_project.project_type == "交通物流"
    assert updated_project.project_kind == "backend"
    assert updated_project.agents_path == "/workspace/moved/AGENTS.md"


def test_project_locations_are_unique_inside_a_workspace() -> None:
    workspaces = InMemoryWorkspaceRepository()
    projects = InMemoryProjectRepository(workspaces)
    workspaces.create_workspace(
        workspace_id="workspace-a",
        name="A",
        root_path="/workspace/a",
        enabled=True,
    )
    projects.create_project(
        project_id="project-a",
        workspace_id="workspace-a",
        relative_path="services/order",
        document_relative_path="docs/backend/order/AGENTS.md",
        name="订单",
        project_kind="backend",
    )

    with pytest.raises(ProjectRepositoryError, match="AGENTS.md 已经添加"):
        projects.create_project(
            project_id="project-b",
            workspace_id="workspace-a",
            relative_path="services/order",
            document_relative_path="docs/frontend/order/AGENTS.md",
            name="重复订单",
            project_kind="frontend",
        )


def test_project_can_move_between_workspaces_and_list_by_workspace() -> None:
    workspaces = InMemoryWorkspaceRepository()
    projects = InMemoryProjectRepository(workspaces)
    for workspace_id, root_path in (
        ("workspace-a", "/workspace/a"),
        ("workspace-b", "/workspace/b"),
    ):
        workspaces.create_workspace(
            workspace_id=workspace_id,
            name=workspace_id,
            root_path=root_path,
            enabled=True,
        )
    projects.create_project(
        project_id="project-a",
        workspace_id="workspace-a",
        relative_path=".",
        document_relative_path="docs/frontend/root/AGENTS.md",
        name="根项目",
        project_kind="frontend",
    )

    projects.update_project(
        "project-a",
        name="订单服务",
        workspace_id="workspace-b",
        relative_path="services/order",
        document_relative_path="docs/backend/order/AGENTS.md",
        project_kind="backend",
    )

    assert projects.list_projects("workspace-a") == []
    moved = projects.list_projects("workspace-b")
    assert len(moved) == 1
    assert moved[0].agents_path == "/workspace/b/docs/backend/order/AGENTS.md"
    assert moved[0].project_kind == "backend"


def test_legacy_update_rejects_workspace_child_project() -> None:
    workspaces = InMemoryWorkspaceRepository()
    projects = InMemoryProjectRepository(workspaces)
    workspaces.create_workspace(
        workspace_id="workspace-a",
        name="A",
        root_path="/workspace/a",
        enabled=True,
    )
    projects.create_project(
        project_id="project-a",
        workspace_id="workspace-a",
        relative_path="services/order",
        document_relative_path="docs/backend/order/AGENTS.md",
        name="订单",
    )

    with pytest.raises(ProjectRepositoryError, match="工作空间项目接口"):
        projects.update_project(
            "project-a",
            name="错误更新",
            project_type="公司项目",
            agents_path="/workspace/moved/AGENTS.md",
        )

    workspace = workspaces.get_workspace("workspace-a")
    project = projects.get_project("project-a")
    assert workspace.root_path == "/workspace/a"
    assert project.relative_path == "services/order"
    assert project.agents_path == "/workspace/a/docs/backend/order/AGENTS.md"


def test_legacy_update_rejects_docs_entry_for_single_root_project() -> None:
    workspaces = InMemoryWorkspaceRepository()
    projects = InMemoryProjectRepository(workspaces)
    workspaces.create_workspace(
        workspace_id="workspace-a",
        name="A",
        root_path="/workspace/a",
        enabled=True,
    )
    projects.create_project(
        project_id="project-a",
        workspace_id="workspace-a",
        relative_path=".",
        document_relative_path="docs/frontend/root/AGENTS.md",
        name="根项目",
        project_kind="frontend",
    )

    with pytest.raises(ProjectRepositoryError, match="工作空间项目接口"):
        projects.update_project(
            "project-a",
            name="错误更新",
            project_type="公司项目",
            agents_path="/workspace/moved/AGENTS.md",
        )

    workspace = workspaces.get_workspace("workspace-a")
    project = projects.get_project("project-a")
    assert workspace.root_path == "/workspace/a"
    assert project.agents_path == "/workspace/a/docs/frontend/root/AGENTS.md"


def test_legacy_update_rejects_root_project_with_siblings() -> None:
    workspaces = InMemoryWorkspaceRepository()
    projects = InMemoryProjectRepository(workspaces)
    workspaces.create_workspace(
        workspace_id="workspace-a",
        name="A",
        root_path="/workspace/a",
        enabled=True,
    )
    projects.create_project(
        project_id="root-project",
        workspace_id="workspace-a",
        relative_path=".",
        document_relative_path="docs/backend/root/AGENTS.md",
        name="根项目",
    )
    projects.create_project(
        project_id="child-project",
        workspace_id="workspace-a",
        relative_path="services/order",
        document_relative_path="docs/frontend/order/AGENTS.md",
        name="订单",
        project_kind="frontend",
    )

    with pytest.raises(ProjectRepositoryError, match="包含多个项目"):
        projects.update_project(
            "root-project",
            name="错误更新",
            project_type="公司项目",
            agents_path="/workspace/moved/AGENTS.md",
        )

    workspace = workspaces.get_workspace("workspace-a")
    assert workspace.root_path == "/workspace/a"
    assert projects.get_project("child-project").agents_path == (
        "/workspace/a/docs/frontend/order/AGENTS.md"
    )


def test_project_requires_an_existing_explicit_workspace() -> None:
    projects = InMemoryProjectRepository(InMemoryWorkspaceRepository())

    with pytest.raises(ProjectRepositoryError, match="工作空间不存在"):
        projects.create_project(
            project_id="project-a",
            workspace_id="missing",
            relative_path=".",
            name="项目",
        )


def test_project_kind_is_limited_to_frontend_or_backend() -> None:
    workspaces = InMemoryWorkspaceRepository()
    projects = InMemoryProjectRepository(workspaces)
    workspaces.create_workspace(
        workspace_id="workspace-a",
        name="A",
        root_path="/workspace/a",
        enabled=True,
    )

    with pytest.raises(ProjectRepositoryError, match="frontend 或 backend"):
        projects.create_project(
            project_id="project-a",
            workspace_id="workspace-a",
            relative_path=".",
            name="项目",
            project_kind="mobile",
        )
