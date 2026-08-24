from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from context_router.services.ai_interface_visualization import (
    AiInterfaceVisualizationService,
)


class _Cursor(AbstractContextManager["_Cursor"]):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.query = ""
        self.params: tuple[object, ...] = ()

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.query = query
        self.params = params

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class _Connection(AbstractContextManager["_Connection"]):
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _Connection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self._cursor


class _Service(AiInterfaceVisualizationService):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(None)
        self.cursor = _Cursor(rows)

    def _connect(self) -> _Connection:  # type: ignore[override]
        return _Connection(self.cursor)


def _row(log_id: str, created_at: datetime) -> dict[str, Any]:
    return {
        "id": log_id,
        "workspace_id": "workspace-1",
        "workspace_name": "攀枝花开发工作空间",
        "task_id": 9,
        "tool_call_id": 18,
        "plan_id": "plan-1",
        "request_sha256": "a" * 64,
        "request_body": '{"path":{},"query":{},"body":{"pageNumber":1}}',
        "response_body": '{"code":0,"data":[]}',
        "status_code": 200,
        "success": True,
        "duration_ms": 32,
        "response_bytes": 20,
        "response_truncated": False,
        "created_at": created_at,
        "environment_key": "local",
        "environment_name": "LOCAL · 运营端",
        "identity_name": "superAdmin",
        "identity_role": "运营管理员",
        "interface_id": "interface-1",
        "interface_name": "分页查询合同",
        "method": "post",
        "path": "/member-api/admin/contract/page",
        "service_name": "c12-portal",
        "address_name": "运营端",
        "description": "查询最新合同第一页",
        "agent_name": "codex",
        "parameter_evidence": {"body": {"pageNumber": {"source": "caller"}}},
    }


def test_interface_request_list_uses_newest_first_and_bounded_paging() -> None:
    now = datetime(2026, 8, 24, 10, 30, tzinfo=UTC)
    service = _Service([_row("log-new", now), _row("log-old", now)])

    result = service.list_requests(workspace_id="workspace-1", limit=1, offset=0)

    assert [item.id for item in result.items] == ["log-new"]
    assert result.has_more is True
    assert "ORDER BY log.created_at DESC, log.id DESC" in service.cursor.query
    assert service.cursor.params[-2:] == (2, 0)


def test_interface_request_detail_joins_intent_request_response_and_evidence() -> None:
    service = _Service([_row("log-1", datetime(2026, 8, 24, 10, 30, tzinfo=UTC))])

    result = service.get_request("log-1")

    assert result.source == "codex"
    assert result.description == "查询最新合同第一页"
    assert result.request["body"] == {"pageNumber": 1}
    assert result.response == {"code": 0, "data": []}
    assert result.parameter_evidence["body"]["pageNumber"]["source"] == "caller"
