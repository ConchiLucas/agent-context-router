from context_router.services.interface_forwarding import InterfaceForwardingService
from context_router.services.interface_forwarding_context import InterfaceForwardingContextService


def test_parse_spec_builds_location_aware_contract_and_read_kind() -> None:
    endpoints = InterfaceForwardingService._parse_spec(
        {
            "openapi": "3.0.0",
            "paths": {
                "/order-api/admin/orders/{orderId}": {
                    "parameters": [
                        {
                            "in": "path",
                            "name": "orderId",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "post": {
                        "summary": "查询订单详情",
                        "parameters": [
                            {
                                "in": "query",
                                "name": "includeCargo",
                                "schema": {"type": "boolean", "default": False},
                            }
                        ],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"pageSize": {"type": "integer"}},
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "ok"}},
                    },
                }
            },
        }
    )

    assert len(endpoints) == 1
    endpoint = endpoints[0]
    assert endpoint["operation_kind"] == "read"
    assert endpoint["request_contract"]["path"]["required"] == ["orderId"]
    assert endpoint["request_contract"]["query"]["properties"]["includeCargo"]["default"] is False
    assert "pageSize" in endpoint["request_contract"]["body"]["properties"]


def test_materialize_request_keeps_saved_origin_and_encodes_path_values() -> None:
    url, query, body = InterfaceForwardingContextService._materialize_request(
        "http://192.168.0.222:28080/rest/mtp",
        {
            "method": "POST",
            "path_template": "/order-api/admin/orders/{orderId}",
            "values": {
                "path": {"orderId": "A/B 1"},
                "query": {"preview": True},
                "body": {"pageNumber": 1},
            },
        },
    )

    assert url == "http://192.168.0.222:28080/rest/mtp/order-api/admin/orders/A%2FB%201"
    assert query == {"preview": True}
    assert body == {"pageNumber": 1}


def test_operation_kind_is_conservative_for_post_requests() -> None:
    assert InterfaceForwardingService._operation_kind("POST", "分页查询订单") == "read"
    assert InterfaceForwardingService._operation_kind("POST", "删除订单") == "destructive"
    assert InterfaceForwardingService._operation_kind("POST", "处理订单") == "unknown"
    assert InterfaceForwardingService._operation_kind("GET", "取消订阅 SSE 事件") == "write"


def test_gateway_route_path_includes_service_prefix() -> None:
    assert InterfaceForwardingContextService._route_path(
        {
            "gateway_path_prefix": "data",
            "path": "/data-api/mtp/admin/goods/selectable/page",
        }
    ) == "/data/data-api/mtp/admin/goods/selectable/page"


def test_existing_paths_are_added_to_the_compact_request_contract() -> None:
    contract = InterfaceForwardingContextService._normalize_contract(
        {"body": {"type": "object", "properties": {}}},
        "/order-api/orders/{orderId}",
    )
    summary = InterfaceForwardingContextService._contract_summary(contract)

    assert summary["path"] == [{"name": "orderId", "type": "string", "required": True}]


def test_http_success_respects_common_business_failure_fields() -> None:
    assert InterfaceForwardingContextService._response_success(200, '{"code":0}') is True
    assert InterfaceForwardingContextService._response_success(200, '{"success":false}') is False
    assert InterfaceForwardingContextService._response_success(200, '{"code":500}') is False


def test_successful_history_is_sanitized_and_pagination_is_bounded() -> None:
    values, changes = InterfaceForwardingContextService._sanitize_history_values(
        {
            "body": {
                "pageNumber": 8,
                "pageSize": 200,
                "shipperId": "shipper-1",
                "timestamp": 123456,
                "filter": {"accessToken": "expired", "status": "ACTIVE"},
            }
        }
    )

    assert values == {
        "path": {},
        "query": {},
        "body": {
            "pageNumber": 1,
            "pageSize": 20,
            "shipperId": "shipper-1",
            "filter": {"status": "ACTIVE"},
        },
    }
    assert {item["action"] for item in changes} == {
        "reset_page_number",
        "clamp_page_size",
        "remove_volatile_history_value",
    }


def test_parameter_evidence_keeps_source_and_caller_overrides_history() -> None:
    values = {"path": {}, "query": {}, "body": {}}
    sources = {"path": {}, "query": {}, "body": {}}
    evidence = {"path": {}, "query": {}, "body": {}}
    history = {"log_id": "log-1", "status_code": 200}

    InterfaceForwardingContextService._merge_values(
        values,
        sources,
        evidence,
        {"body": {"shipperId": "old", "pageNumber": 1}},
        "successful_history",
        context=history,
    )
    InterfaceForwardingContextService._merge_values(
        values,
        sources,
        evidence,
        {"body": {"shipperId": "current"}},
        "caller",
    )

    assert values["body"]["shipperId"] == "current"
    assert sources["body"]["shipperId"] == "caller"
    assert evidence["body"]["shipperId"] == {
        "source": "caller",
        "confidence": "high",
    }
    assert evidence["body"]["pageNumber"]["source"] == "successful_history"
    assert evidence["body"]["pageNumber"]["evidence"] == history


def test_historical_ids_are_reported_as_not_database_validated() -> None:
    values = {"path": {}, "query": {}, "body": {"shipperId": "shipper-1"}}
    evidence = {
        "path": {},
        "query": {},
        "body": {
            "shipperId": {
                "source": "successful_history",
                "confidence": "medium",
            }
        },
    }

    warnings = InterfaceForwardingContextService._parameter_warnings(values, evidence)

    assert warnings[0]["code"] == "historical_id_not_database_validated"
    assert warnings[0]["fields"] == [{"location": "body", "name": "shipperId"}]
    assert evidence["body"]["shipperId"]["database_validation"] == "not_checked"
