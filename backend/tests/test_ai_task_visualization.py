from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.api.ai_task_visualization import router
from context_router.schemas.ai_task_visualization import (
    AiTaskRelatedArtifacts,
    AiTaskResult,
    AiTaskTimeline,
    AiTaskTimelineEvent,
    AiTaskVisualizationDetail,
    AiTaskVisualizationList,
    AiTaskVisualizationListItem,
)


def _item() -> AiTaskVisualizationListItem:
    now = datetime.now(UTC)
    return AiTaskVisualizationListItem(
        task_id=42,
        description="排查合同分页接口",
        workspace_id="workspace-1",
        workspace_name="攀枝花开发工作空间",
        environment="uat",
        agent_name="codex",
        status="resolved",
        created_at=now,
        last_activity_at=now,
        tool_call_count=8,
        tool_error_count=1,
        running_call_count=0,
        data_query_count=1,
        interface_success_count=1,
        interface_failed_count=1,
        error_event_count=2,
    )


class FakeTaskVisualizationService:
    def list_tasks(self, **_: object) -> AiTaskVisualizationList:
        return AiTaskVisualizationList(items=[_item()], limit=30, has_more=False)

    def get_task(self, task_id: int) -> AiTaskVisualizationDetail:
        assert task_id == 42
        item = _item()
        now = datetime.now(UTC)
        return AiTaskVisualizationDetail(
            **item.model_dump(),
            cwd="/workspace/project",
            active_project_name="backend",
            result=AiTaskResult(
                task_id=42,
                status="resolved",
                summary="已确认并修复分页参数",
                source="codex",
                revision=1,
                created_at=now,
                updated_at=now,
                finalized_at=now,
            ),
            related=AiTaskRelatedArtifacts(
                mcp_trace=True,
                data_visualization=True,
                interface_visualization=True,
                log_visualization=True,
            ),
        )

    def timeline(self, task_id: int, **_: object) -> AiTaskTimeline:
        assert task_id == 42
        return AiTaskTimeline(
            task_id=42,
            items=[
                AiTaskTimelineEvent(
                    event_id="mcp:1",
                    event_type="mcp_call",
                    title="prepare_task_context",
                    status="ok",
                    occurred_at=datetime.now(UTC),
                    summary="工具调用已记录",
                    artifact_type="mcp",
                    artifact_id="1",
                )
            ],
            limit=50,
            has_more=False,
        )


def test_task_visualization_read_api_returns_list_detail_and_timeline() -> None:
    app = FastAPI()
    app.state.ai_task_visualization_service = FakeTaskVisualizationService()
    app.include_router(router, prefix="/api")

    with TestClient(app) as client:
        listed = client.get("/api/ai-visualization/tasks")
        detail = client.get("/api/ai-visualization/tasks/42")
        timeline = client.get("/api/ai-visualization/tasks/42/timeline")

    assert listed.status_code == 200
    assert listed.json()["items"][0]["task_id"] == 42
    assert detail.status_code == 200
    assert detail.json()["result"]["summary"] == "已确认并修复分页参数"
    assert timeline.status_code == 200
    assert timeline.json()["items"][0]["event_type"] == "mcp_call"
