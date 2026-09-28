import json

import pytest

from context_router.services.interface_request_status import request_status


@pytest.mark.parametrize(
    "data",
    [
        {"rows": []},
        {"estimatedDistance": None, "estimatedArrivalDate": None, "relateDetailQueryList": None},
        {"id": None, "code": None, "chineseName": None, "siteFeeCargoList": None},
    ],
)
def test_overview_environment_and_no_response_leak(monkeypatch, data):
    from test_interface_forwarding_generic import _OverviewConnection, _OverviewCursor

    from context_router.services.interface_forwarding import InterfaceForwardingService

    class Cursor(_OverviewCursor):
        def fetchall(self):
            if "SELECT i.id" not in self.calls[-1][0]:
                return []
            return [
                {
                    "id": "interface-1",
                    "name": "查询",
                    "description": "查询",
                    "path": "/query",
                    "method": "POST",
                    "operation_kind": "read",
                    "last_requested_at": "2026-09-22",
                    "last_environment": "test",
                    "last_status_code": 200,
                    "last_success": True,
                    "last_response_body": json.dumps({"code": 200, "data": data}),
                    "last_truncated": False,
                }
            ]

    cursor = Cursor(total=1)
    service = InterfaceForwardingService("unused")
    monkeypatch.setattr(service, "_connect", lambda: _OverviewConnection(cursor))
    monkeypatch.setattr(service, "list_environments", lambda *args, **kwargs: [])
    result = service.overview("workspace-1", environment="test")
    item = result["interfaces"][0]
    assert item["request_status"] == "no_data"
    assert "last_response_body" not in item
    assert "last_success" not in item
    statement, params = cursor.calls[-1]
    assert params[:2] == ("test", "test")
    assert "logs.environment_key = %s" in statement
    assert "ORDER BY logs.created_at DESC, logs.id DESC" in statement


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"code": 200, "data": {"rows": [], "total": 100}}, "no_data"),
        ({"code": "200", "data": {"records": [{"name": "测试"}]}}, "has_data"),
        ({"code": 0, "data": {"name": "无主键详情"}}, "has_data"),
        ({"code": 200, "data": None}, "no_data"),
        ({"code": 200, "data": {}}, "no_data"),
        ({"code": 200, "data": []}, "no_data"),
        ({"code": 200, "data": 0}, "has_data"),
        ({"code": 200, "data": False}, "has_data"),
        ({"code": 200, "data": {"id": None, "name": None}}, "no_data"),
        ({"code": 200, "data": {"id": None, "code": None, "name": None}}, "no_data"),
        ({"code": 200, "data": {"id": None, "success": None}}, "no_data"),
        ({"code": 500, "data": {"id": None, "code": None}}, "business_error"),
        ({"success": False, "data": {"id": None, "code": None}}, "business_error"),
        ({"code": 200, "data": {"code": None, "distance": 0}}, "has_data"),
        ({"code": 200, "data": {"code": None, "enabled": False}}, "has_data"),
        ({"code": 200, "data": {"id": "1", "code": "SITE", "name": "站点"}}, "has_data"),
        ({"code": 200, "data": {"success": False, "id": "1"}}, "has_data"),
        ({"code": 200, "data": {"code": 200, "msg": "ok"}}, "requested"),
        ({"code": 200, "data": {"code": 500, "message": "error"}}, "requested"),
        ({"code": 200, "id": "1"}, "requested"),
        ({"code": 500, "data": {"id": "1", "code": "SITE"}}, "business_error"),
        ({"success": False, "data": {"id": "1", "code": "SITE"}}, "business_error"),
        ({"id": None, "name": None}, "no_data"),
        ({"code": 200, "data": {"id": None, "distance": 0}}, "has_data"),
        ({"code": 200, "data": {"id": None, "enabled": False}}, "has_data"),
        ({"code": 200, "data": {"id": None, "name": "value"}}, "has_data"),
        ({"code": 200, "data": {"nested": {"id": None}}}, "has_data"),
        ({"code": 200, "data": [{"id": None}]}, "has_data"),
        ({"code": 200, "data": {"total": None}}, "requested"),
        ({"code": 200}, "requested"),
        ({"code": 404, "data": []}, "business_error"),
        ({"code": 9000}, "business_error"),
        ({"success": False, "data": [1]}, "business_error"),
        ([1], "has_data"),
        ([], "no_data"),
    ],
)
def test_query_status(payload, expected):
    assert (
        request_status(
            requested=True,
            operation_kind="read",
            status_code=200,
            success=True,
            response_body=json.dumps(payload),
        )
        == expected
    )


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"requested": False}, "not_requested"),
        ({"status_code": 404, "success": False}, "not_found"),
        ({"status_code": 500}, "error"),
        ({"status_code": 401}, "error"),
        ({"status_code": None}, "error"),
        ({"success": False}, "error"),
        ({"truncated": True}, "requested"),
        ({"response_body": "<html>login</html>"}, "requested"),
        ({"response_body": "", "status_code": 204}, "no_data"),
        ({"operation_kind": "write"}, "succeeded"),
        ({"operation_kind": "destructive"}, "succeeded"),
        ({"operation_kind": "unknown"}, "requested"),
        ({"operation_kind": "write", "response_body": '{"code":500}'}, "business_error"),
        ({"success": False, "response_body": '{"code":9000}'}, "business_error"),
        ({"success": False, "response_body": '{"success":false}'}, "business_error"),
        ({"status_code": 500, "response_body": '{"code":9000}'}, "error"),
        ({"status_code": 404, "response_body": '{"code":9000}'}, "not_found"),
        ({"success": False, "truncated": True}, "error"),
        ({"success": False, "response_body": "invalid json"}, "error"),
    ],
)
def test_request_status_precedence(overrides, expected):
    values = dict(
        requested=True,
        operation_kind="read",
        status_code=200,
        success=True,
        response_body='{"code":200,"data":null}',
    )
    values.update(overrides)
    assert request_status(**values) == expected
