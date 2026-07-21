from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from context_router.config import Settings
from context_router.main import create_app
from context_router.repositories.document_read_repository import (
    DocumentReadCallRecord,
    DocumentReadItemRecord,
    DocumentReadItemWrite,
)
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.task_repository import TaskListRecord, TaskRecord


class FakeTaskStore:
    def __init__(self) -> None:
        self.project_key = ""
        self.created_at = datetime.now(UTC)

    def create_task(self, *, project_key: str, **_: object) -> int:
        self.project_key = project_key
        return 12

    def get_task(self, task_id: int) -> TaskRecord:
        assert task_id == 12
        return TaskRecord(
            id=12,
            project_key=self.project_key,
            project_name="测试项目",
            task="排查登录问题",
            cwd="/workspace/test",
            agent_name="codex",
            created_at=self.created_at,
        )

    def list_tasks(
        self,
        project_key: str,
        *,
        limit: int = 30,
        include_system: bool = False,
    ) -> list[TaskListRecord]:
        assert project_key == self.project_key
        assert limit == 30
        assert include_system is False
        task = self.get_task(12)
        return [
            TaskListRecord(
                id=task.id,
                project_key=task.project_key,
                project_name=task.project_name,
                task=task.task,
                cwd=task.cwd,
                agent_name=task.agent_name,
                created_at=task.created_at,
                read_call_count=1,
            )
        ]


class FakeReadStore:
    def __init__(self, created_at: datetime) -> None:
        self.created_at = created_at

    def create_read_call(
        self,
        *,
        task_id: int,
        items: list[DocumentReadItemWrite],
    ) -> int:
        return 31

    def list_read_calls(self, task_id: int) -> list[DocumentReadCallRecord]:
        assert task_id == 12
        return [
            DocumentReadCallRecord(
                id=31,
                task_id=12,
                created_at=self.created_at,
                items=[
                    DocumentReadItemRecord(
                        id=90,
                        position=1,
                        document_id="abc",
                        document_path="docs/startup.md",
                        requested_section="启动",
                        status="ok",
                    )
                ],
            )
        ]


def test_lists_project_tasks_and_ordered_read_history(tmp_path: Path) -> None:
    root = tmp_path / "project" / "AGENTS.md"
    root.parent.mkdir(parents=True)
    root.write_text("# 项目入口", encoding="utf-8")
    task_store = FakeTaskStore()
    read_store = FakeReadStore(task_store.created_at)
    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        task_repository=task_store,
        document_read_repository=read_store,
        project_repository=InMemoryProjectRepository(),
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "测试项目", "agents_path": str(root)},
        ).json()
        client.post(f"/api/projects/{project['id']}/prepare-preview")
        tasks = client.get(f"/api/projects/{project['id']}/tasks")
        history = client.get("/api/tasks/12/document-reads")

    assert tasks.status_code == 200
    assert tasks.json()[0]["task_id"] == 12
    assert tasks.json()[0]["read_call_count"] == 1
    assert history.status_code == 200
    assert history.json()["calls"][0]["read_call_id"] == 31
    assert history.json()["calls"][0]["documents"] == [
        {
            "position": 1,
            "document_id": "abc",
            "path": "docs/startup.md",
            "section": "启动",
            "status": "ok",
        }
    ]
