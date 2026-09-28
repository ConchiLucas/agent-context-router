import json

import pytest

from context_router.services.interface_forwarding import (
    InterfaceForwardingError,
    InterfaceForwardingService,
)


class _OverviewCursor:
    def __init__(self, total: int = 0) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.total = total

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, statement: str, params: tuple[object, ...]) -> None:
        assert statement.count("%s") == len(params)
        self.calls.append((statement, params))

    def fetchone(self) -> dict[str, object]:
        return {"total": self.total}

    @staticmethod
    def fetchall() -> list[dict[str, object]]:
        return []


class _OverviewConnection:
    def __init__(self, cursor: _OverviewCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def cursor(self) -> _OverviewCursor:
        return self._cursor


def test_overview_binds_every_filter_placeholder_for_empty_and_non_empty_keywords(
    monkeypatch,
) -> None:
    service = InterfaceForwardingService("postgresql://unused")
    cursor = _OverviewCursor()
    connection = _OverviewConnection(cursor)
    monkeypatch.setattr(service, "_connect", lambda: connection)
    monkeypatch.setattr(service, "list_environments", lambda *_args, **_kwargs: [])

    service.overview("workspace-1")
    service.overview("workspace-1", "司机")

    interface_calls = [
        params
        for statement, params in cursor.calls
        if "SELECT i.id" in statement and "semantic.search_document" in statement
    ]
    assert interface_calls == [
        ("", "", "workspace-1", "", "", "", "%%", "%%", "%%", "%%", "%%", 50, 0),
        (
            "",
            "",
            "workspace-1",
            "",
            "",
            "司机",
            "%司机%",
            "%司机%",
            "%司机%",
            "%司机%",
            "%司机%",
            50,
            0,
        ),
    ]


def test_overview_uses_server_pagination_and_keeps_filtered_total(monkeypatch) -> None:
    service = InterfaceForwardingService("postgresql://unused")
    cursor = _OverviewCursor(total=121)
    connection = _OverviewConnection(cursor)
    monkeypatch.setattr(service, "_connect", lambda: connection)
    monkeypatch.setattr(service, "list_environments", lambda *_args, **_kwargs: [])

    result = service.overview("workspace-1", service_id="", page=3, page_size=50)

    assert result["page"] == 3
    assert result["page_size"] == 50
    assert result["interface_total"] == 121
    assert result["total_pages"] == 3
    interface_params = next(
        params
        for statement, params in cursor.calls
        if "SELECT i.id" in statement and "semantic.search_document" in statement
    )
    assert interface_params[-2:] == (50, 100)


def test_overview_status_filter_paginates_matching_interfaces(monkeypatch) -> None:
    class StatusCursor(_OverviewCursor):
        def fetchall(self):
            statement, params = self.calls[-1]
            if "SELECT i.id, i.operation_kind" in statement:
                return [
                    {
                        "id": interface_id,
                        "operation_kind": "read",
                        "last_requested_at": "2026-09-28",
                        "last_status_code": status_code,
                        "last_success": status_code == 200,
                        "last_response_body": json.dumps({"code": 200, "data": {"rows": rows}}),
                        "last_truncated": False,
                    }
                    for interface_id, status_code, rows in (
                        ("one", 200, [{"id": 1}]),
                        ("two", 404, []),
                        ("three", 200, [{"id": 3}]),
                    )
                ]
            if "SELECT i.id, i.service_id" in statement:
                assert params[:2] == ("test", "test")
                assert params[-3] == ["three"]
                return [{
                    "id": "three", "name": "查询", "description": "", "path": "/three",
                    "method": "POST", "operation_kind": "read",
                    "last_requested_at": "2026-09-28", "last_status_code": 200,
                    "last_success": True,
                    "last_response_body": json.dumps({"code": 200, "data": {"rows": [{"id": 3}]}}),
                    "last_truncated": False,
                }]
            return []

    cursor = StatusCursor()
    service = InterfaceForwardingService("postgresql://unused")
    monkeypatch.setattr(service, "_connect", lambda: _OverviewConnection(cursor))
    monkeypatch.setattr(service, "list_environments", lambda *_args, **_kwargs: [])

    result = service.overview(
        "workspace-1", service_id="", environment="test",
        status_filter="has_data", page=2, page_size=1,
    )

    assert result["interface_total"] == 2
    assert result["page"] == 2
    assert result["total_pages"] == 2
    assert [item["id"] for item in result["interfaces"]] == ["three"]
    assert result["interfaces"][0]["request_status"] == "has_data"
    assert "i.id = ANY(%s::text[])" in cursor.calls[-1][0]
    assert not any("SELECT count(*)" in statement for statement, _ in cursor.calls)


def test_overview_rejects_unknown_status_filter() -> None:
    service = InterfaceForwardingService("postgresql://unused")
    with pytest.raises(InterfaceForwardingError, match="状态筛选值无效"):
        service.overview("workspace-1", status_filter="not-a-status")


def test_source_identity_is_not_rewritten_by_workspace_business_rules() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "getDriverPage",
            operation_id="driverPage",
            method="GET",
            path="/api/drivers",
        )
        == "getDriverPage"
    )


def test_controller_name_is_derived_generically_from_openapi_tag() -> None:
    assert (
        InterfaceForwardingService._controller_name(
            {"tags": ["inventory-report-controller"]}
        )
        == "InventoryReportController"
    )


def test_openapi_result_does_not_contain_retired_semantic_fields() -> None:
    endpoint = InterfaceForwardingService._parse_spec(
        {
            "openapi": "3.0.0",
            "paths": {
                "/widgets": {
                    "post": {
                        "tags": ["widget-controller"],
                        "summary": "Create widget",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    )[0]

    assert endpoint["controller_name"] == "WidgetController"
    assert "crud_type" not in endpoint
    assert "controller_description" not in endpoint
