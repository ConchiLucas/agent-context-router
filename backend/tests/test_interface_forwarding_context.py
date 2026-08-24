from datetime import UTC, datetime

import pytest

from context_router.services.interface_forwarding import InterfaceForwardingService
from context_router.services.interface_forwarding_context import InterfaceForwardingContextService


class _ValueMappings:
    def __init__(self) -> None:
        self.resolved: list[str] = []

    def search_for_task(self, **_: object) -> dict[str, object]:
        return {
            "mappings": [
                {
                    "mapping_id": "mapping-shipper",
                    "value_key": "shipper_id",
                    "bindings": [
                        {
                            "location": "body",
                            "parameter_path": "shipperId",
                        }
                    ],
                },
                {
                    "mapping_id": "mapping-carrier",
                    "value_key": "carrier_id",
                    "bindings": [
                        {
                            "location": "body",
                            "parameter_path": "carrierId",
                        }
                    ],
                },
            ]
        }

    def resolve_for_task(self, mapping_id: str, **_: object) -> dict[str, object]:
        self.resolved.append(mapping_id)
        values = {
            "mapping-shipper": ["shipper-old", "shipper-new"],
            "mapping-carrier": ["carrier-new"],
        }
        return {
            "candidates": [
                {"value": value, "label": value, "labels": {}}
                for value in values[mapping_id]
            ]
        }


def _context_service(mappings: _ValueMappings) -> InterfaceForwardingContextService:
    return InterfaceForwardingContextService(
        database_url=None,
        task_repository=object(),  # type: ignore[arg-type]
        database_environment_repository=object(),  # type: ignore[arg-type]
        value_mapping_service=mappings,  # type: ignore[arg-type]
    )


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


def test_selection_uses_the_only_candidate_without_history() -> None:
    candidate = {"id": "address-1", "name": "运营端"}
    selected, evidence = InterfaceForwardingContextService._choose_selection_candidate(
        [candidate], explicit=False, historic_id=None, history=None
    )
    assert selected == candidate
    assert evidence == {"source": "single_candidate"}


def test_explicit_selection_is_reported_as_caller() -> None:
    candidate = {"id": "identity-1", "login_account": "superAdmin"}
    selected, evidence = InterfaceForwardingContextService._choose_selection_candidate(
        [candidate], explicit=True, historic_id=None, history=None
    )
    assert selected == candidate
    assert evidence == {"source": "caller"}


def test_multiple_candidates_reuse_latest_successful_valid_selection() -> None:
    candidates = [{"id": "address-1"}, {"id": "address-2"}]
    created_at = datetime(2026, 8, 23, 8, 30, tzinfo=UTC)
    selected, evidence = InterfaceForwardingContextService._choose_selection_candidate(
        candidates,
        explicit=False,
        historic_id="address-2",
        history={"log_id": "log-9", "created_at": created_at, "status_code": 200},
    )
    assert selected == {"id": "address-2"}
    assert evidence == {
        "source": "successful_history",
        "log_id": "log-9",
        "created_at": created_at.isoformat(),
        "status_code": 200,
    }


def test_deleted_historical_selection_does_not_choose_another_candidate() -> None:
    selected, evidence = InterfaceForwardingContextService._choose_selection_candidate(
        [{"id": "address-1"}, {"id": "address-2"}],
        explicit=False,
        historic_id="deleted-address",
        history={"log_id": "log-old"},
    )
    assert selected is None
    assert evidence is None


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


def test_refresh_selected_replaces_only_named_mapping_and_excludes_history() -> None:
    mappings = _ValueMappings()
    service = _context_service(mappings)
    values = {
        "path": {},
        "query": {},
        "body": {"shipperId": "shipper-old", "carrierId": "carrier-old", "pageNumber": 1},
    }
    sources = {
        "path": {},
        "query": {},
        "body": {
            "shipperId": "successful_history",
            "carrierId": "successful_history",
            "pageNumber": "successful_history",
        },
    }
    evidence = {
        "path": {},
        "query": {},
        "body": {
            "shipperId": {"source": "successful_history"},
            "carrierId": {"source": "successful_history"},
            "pageNumber": {"source": "successful_history"},
        },
    }

    resolutions, issues = service._refresh_mapped_values(
        task_id=9,
        interface_id="interface-1",
        strategy="refresh_selected",
        refresh_value_keys=["shipper_id"],
        values=values,
        sources=sources,
        evidence=evidence,
        caller_values={"path": {}, "query": {}, "body": {}},
    )

    assert issues == []
    assert mappings.resolved == ["mapping-shipper"]
    assert values["body"] == {
        "shipperId": "shipper-new",
        "carrierId": "carrier-old",
        "pageNumber": 1,
    }
    assert sources["body"]["shipperId"] == "value_mapping"
    assert evidence["body"]["shipperId"]["action"] == "refreshed"
    assert resolutions[0]["previous_value_excluded"] is True


def test_caller_value_wins_without_querying_the_selected_mapping() -> None:
    mappings = _ValueMappings()
    service = _context_service(mappings)
    values = {"path": {}, "query": {}, "body": {"shipperId": "shipper-old"}}
    sources = {"path": {}, "query": {}, "body": {"shipperId": "successful_history"}}
    evidence = {
        "path": {},
        "query": {},
        "body": {"shipperId": {"source": "successful_history"}},
    }

    resolutions, issues = service._refresh_mapped_values(
        task_id=9,
        interface_id="interface-1",
        strategy="refresh_selected",
        refresh_value_keys=["shipper_id"],
        values=values,
        sources=sources,
        evidence=evidence,
        caller_values={"path": {}, "query": {}, "body": {"shipperId": "caller-value"}},
    )

    assert issues == []
    assert mappings.resolved == []
    assert resolutions[0]["status"] == "caller_override"
    assert values["body"]["shipperId"] == "shipper-old"


def test_refresh_selected_reports_unbound_value_key_without_querying_database() -> None:
    mappings = _ValueMappings()
    service = _context_service(mappings)

    resolutions, issues = service._refresh_mapped_values(
        task_id=9,
        interface_id="interface-1",
        strategy="refresh_selected",
        refresh_value_keys=["unknown_id"],
        values={"path": {}, "query": {}, "body": {}},
        sources={"path": {}, "query": {}, "body": {}},
        evidence={"path": {}, "query": {}, "body": {}},
        caller_values={"path": {}, "query": {}, "body": {}},
    )

    assert resolutions == []
    assert issues[0]["code"] == "value_mapping_unavailable"
    assert mappings.resolved == []


def test_refresh_mapped_refreshes_every_bound_business_value() -> None:
    mappings = _ValueMappings()
    service = _context_service(mappings)
    values = {
        "path": {},
        "query": {},
        "body": {"shipperId": "shipper-old", "carrierId": "carrier-old"},
    }
    sources = {
        "path": {},
        "query": {},
        "body": {
            "shipperId": "successful_history",
            "carrierId": "successful_history",
        },
    }
    evidence = {
        "path": {},
        "query": {},
        "body": {
            "shipperId": {"source": "successful_history"},
            "carrierId": {"source": "successful_history"},
        },
    }

    resolutions, issues = service._refresh_mapped_values(
        task_id=9,
        interface_id="interface-1",
        strategy="refresh_mapped",
        refresh_value_keys=[],
        values=values,
        sources=sources,
        evidence=evidence,
        caller_values={"path": {}, "query": {}, "body": {}},
    )

    assert issues == []
    assert mappings.resolved == ["mapping-shipper", "mapping-carrier"]
    assert values["body"]["shipperId"] == "shipper-new"
    assert values["body"]["carrierId"] == "carrier-new"
    assert [item["status"] for item in resolutions] == ["refreshed", "refreshed"]


def test_refresh_selected_requires_at_least_one_stable_value_key() -> None:
    mappings = _ValueMappings()
    service = _context_service(mappings)

    resolutions, issues = service._refresh_mapped_values(
        task_id=9,
        interface_id="interface-1",
        strategy="refresh_selected",
        refresh_value_keys=[],
        values={"path": {}, "query": {}, "body": {}},
        sources={"path": {}, "query": {}, "body": {}},
        evidence={"path": {}, "query": {}, "body": {}},
        caller_values={"path": {}, "query": {}, "body": {}},
    )

    assert resolutions == []
    assert issues[0]["code"] == "refresh_value_keys_required"
    assert mappings.resolved == []


def test_refresh_value_keys_are_rejected_for_non_selected_strategy() -> None:
    service = _context_service(_ValueMappings())

    with pytest.raises(ValueError, match="只用于 refresh_selected"):
        service.prepare(
            task_id=9,
            interface_id="interface-1",
            value_strategy="reuse_successful",
            refresh_value_keys=["shipper_id"],
        )
