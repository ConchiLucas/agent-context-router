from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.api.ai_data_visualization import router
from context_router.middleware.browser_read_only import BrowserReadOnlyMiddleware
from context_router.repositories.ai_data_query_repository import (
    InMemoryAiDataQueryRepository,
)
from context_router.repositories.database_environment_repository import (
    InMemoryDatabaseEnvironmentRepository,
)
from context_router.repositories.table_relation_repository import (
    InMemoryTableRelationRepository,
    TableRelationGenerationRecord,
    TableRelationTableRecord,
)
from context_router.repositories.workspace_repository import InMemoryWorkspaceRepository
from context_router.services.ai_data_visualization import AiDataVisualizationService


def _client() -> TestClient:
    workspaces = InMemoryWorkspaceRepository()
    workspaces.create_workspace(
        workspace_id="workspace-1",
        name="测试工作空间",
        workspace_type="个人项目",
        root_path="/workspace/test",
    )
    environments = InMemoryDatabaseEnvironmentRepository()
    relations = InMemoryTableRelationRepository()
    relations.add_generation(
        TableRelationGenerationRecord(
            id="generation-1",
            workspace_id="workspace-1",
            environment="local",
            status="published",
            revision=1,
            relation_count=1,
        ),
        tables=[
            TableRelationTableRecord(
                generation_id="generation-1",
                database_key="app",
                schema_name="public",
                table_name="orders",
                relation_count=1,
            )
        ],
    )
    app = FastAPI()
    app.state.ai_data_visualization_service = AiDataVisualizationService(
        records=InMemoryAiDataQueryRepository(),
        workspaces=workspaces,
        environments=environments,
        relations=relations,
    )
    app.add_middleware(BrowserReadOnlyMiddleware, api_prefix="/api")
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _payload(keyword: str = "ORDER-1") -> dict[str, str]:
    return {
        "source": "codex",
        "description": f"查询订单 {keyword} 的关联数据",
        "workspace_id": "workspace-1",
        "environment": "local",
        "database_key": "app",
        "schema_name": "public",
        "table_name": "orders",
        "keyword": keyword,
    }


def test_local_ai_can_save_and_browser_reads_latest_history() -> None:
    with _client() as client:
        first = client.post("/api/ai-visualization/query-records", json=_payload("ORDER-1"))
        second = client.post("/api/ai-visualization/query-records", json=_payload("ORDER-2"))
        headers = {"Origin": "http://127.0.0.1:49175"}
        latest = client.get(
            "/api/ai-visualization/query-records/latest",
            headers=headers,
        )
        history = client.get(
            "/api/ai-visualization/query-records?limit=20",
            headers=headers,
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert latest.status_code == 200
    assert latest.json()["record"]["keyword"] == "ORDER-2"
    assert latest.json()["record"]["workspace_name"] == "测试工作空间"
    assert [item["keyword"] for item in history.json()["items"]] == [
        "ORDER-2",
        "ORDER-1",
    ]


def test_browser_cannot_write_ai_query_record() -> None:
    with _client() as client:
        response = client.post(
            "/api/ai-visualization/query-records",
            json=_payload(),
            headers={"Origin": "http://127.0.0.1:49175"},
        )

    assert response.status_code == 405
    assert response.json()["detail"].startswith("management_read_only")


def test_rejects_table_outside_published_relation_snapshot() -> None:
    payload = _payload()
    payload["table_name"] = "unknown_table"
    with _client() as client:
        response = client.post("/api/ai-visualization/query-records", json=payload)

    assert response.status_code == 404
    assert response.json()["detail"].startswith("relation_table_not_found")


def test_idempotent_save_and_execution_summary_are_workspace_scoped() -> None:
    payload = _payload("ORDER-3")
    payload["idempotency_key"] = "codex-retry-order-3"
    with _client() as client:
        first = client.post("/api/ai-visualization/query-records", json=payload)
        second = client.post("/api/ai-visualization/query-records", json=payload)
        record_id = first.json()["id"]
        client.app.state.ai_data_visualization_service.record_execution(
            record_id=record_id,
            workspace_id="workspace-1",
            environment="local",
            succeeded=True,
            result_card_count=2,
            result_row_count=7,
            duration_ms=18,
        )
        history = client.get(
            "/api/ai-visualization/query-records"
            "?workspace_id=workspace-1&environment=local&limit=20"
        )
        latest = client.get(
            "/api/ai-visualization/query-records/latest?workspace_id=workspace-1&environment=local"
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == record_id
    assert len(history.json()["items"]) == 1
    assert latest.json()["record"]["execution_status"] == "succeeded"
    assert latest.json()["record"]["result_row_count"] == 7
