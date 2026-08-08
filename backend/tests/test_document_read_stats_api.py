import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from context_router.main import create_app
from context_router.schemas.document_read_stats import (
    DocumentReadStatItem,
    DocumentReadTaskItem,
)
from context_router.repositories.document_read_stats_repository import (
    InMemoryDocumentReadStatsRepository,
)


class DummyDocumentReadStatsRepository(InMemoryDocumentReadStatsRepository):
    def __init__(self):
        super().__init__()
        self.stats = [
            DocumentReadStatItem(
                document_id="doc1",
                document_path="docs/STARTUP_GUIDE.md",
                read_count=10,
                task_count=3,
                last_read_at=datetime.now(timezone.utc),
            ),
            DocumentReadStatItem(
                document_id="AGENTS.md",
                document_path="AGENTS.md",
                read_count=99,
                task_count=50,
                last_read_at=datetime.now(timezone.utc),
            ),
        ]
        self.task_items = [
            DocumentReadTaskItem(
                task_id=1,
                task="Test Task 1",
                agent_name="AgentA",
                cwd="/test",
                workspace_name="ws1",
                active_project_name="proj1",
                created_at=datetime.now(timezone.utc),
                read_count=5,
                sections=["Section 1", "Section 2"],
            )
        ]

    def get_document_read_stats(
        self, *, workspace_id: str | None = None, limit: int = 50
    ) -> list[DocumentReadStatItem]:
        # InMemory 逻辑中排除 AGENTS.md
        return [
            item
            for item in self.stats
            if not item.document_id.endswith("AGENTS.md")
        ][:limit]

    def get_document_read_tasks(
        self, document_id: str, *, limit: int = 50
    ) -> list[DocumentReadTaskItem]:
        if document_id.endswith("AGENTS.md"):
            return []
        return self.task_items[:limit]


def test_document_read_stats_api():
    repo = DummyDocumentReadStatsRepository()
    app = create_app(document_read_stats_repository=repo)
    client = TestClient(app)

    # 1. 测试 GET /api/document-read-stats
    res = client.get("/api/document-read-stats")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["document_id"] == "doc1"
    assert data[0]["read_count"] == 10

    # 2. 测试 GET /api/document-read-stats/doc1/tasks
    res = client.get("/api/document-read-stats/doc1/tasks")
    assert res.status_code == 200
    tasks_data = res.json()
    assert len(tasks_data) == 1
    assert tasks_data[0]["task_id"] == 1
    assert tasks_data[0]["task"] == "Test Task 1"
    assert tasks_data[0]["sections"] == ["Section 1", "Section 2"]

    # 3. 测试 AGENTS.md 被直接拒绝/排查
    res = client.get("/api/document-read-stats/AGENTS.md/tasks")
    assert res.status_code == 200
    assert res.json() == []
