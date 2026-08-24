from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from context_router.api.ai_task_visualization import router
from context_router.schemas.ai_task_visualization import (
    AiTaskChainHealthItem,
    AiTaskRelatedArtifacts,
    AiTaskResult,
    AiTaskResultWrite,
    AiTaskTimeline,
    AiTaskTimelineEvent,
    AiTaskVisualizationDetail,
    AiTaskVisualizationList,
    AiTaskVisualizationListItem,
)
from context_router.services.ai_task_visualization import AiTaskVisualizationService


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
            chain_health=[
                AiTaskChainHealthItem(
                    key="mcp",
                    label="MCP 调用",
                    status="healthy",
                    summary="8 次调用均已完成",
                )
            ],
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
    assert detail.json()["chain_health"][0]["status"] == "healthy"
    assert timeline.status_code == 200
    assert timeline.json()["items"][0]["event_type"] == "mcp_call"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "resolved", "summary": "声称已完成但没有验证"},
        {"status": "failed", "summary": "声称失败但没有根因"},
    ],
)
def test_terminal_task_result_requires_evidence(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        AiTaskResultWrite.model_validate(payload)


def test_chain_health_explains_failures_partial_success_and_log_evidence() -> None:
    item = _item()
    result = AiTaskResult(
        task_id=42,
        status="resolved",
        summary="已完成",
        verification=[{"type": "test", "description": "回归测试", "result": "通过"}],
        source="codex",
        revision=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    health = AiTaskVisualizationService._chain_health(
        item,
        {
            "data_succeeded_count": 1,
            "data_failed_count": 1,
            "data_pending_count": 0,
        },
        result,
    )

    assert [(entry.key, entry.status) for entry in health] == [
        ("mcp", "failed"),
        ("data", "attention"),
        ("interface", "attention"),
        ("log", "attention"),
        ("conclusion", "healthy"),
    ]
    assert health[-1].summary == "已完成并记录 1 项验证"


def test_chain_health_does_not_treat_unused_chains_as_failures() -> None:
    item = _item().model_copy(
        update={
            "tool_call_count": 0,
            "tool_error_count": 0,
            "data_query_count": 0,
            "interface_success_count": 0,
            "interface_failed_count": 0,
            "error_event_count": 0,
        }
    )

    health = AiTaskVisualizationService._chain_health(
        item,
        {
            "data_succeeded_count": 0,
            "data_failed_count": 0,
            "data_pending_count": 0,
        },
        None,
    )

    assert [entry.status for entry in health] == [
        "unused",
        "unused",
        "unused",
        "unused",
        "attention",
    ]
