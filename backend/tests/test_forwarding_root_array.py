import json

import httpx
import pytest
from test_host_runtime_runner import load_runner_module

from context_router.services.interface_forwarding_context import (
    InterfaceForwardingContextError,
)
from context_router.services.interface_forwarding_context import (
    InterfaceForwardingContextService as Service,
)


@pytest.mark.parametrize("location", ["body", "path", "query"])
@pytest.mark.parametrize("value", [2**53, -(2**53), 2e18, float("inf"), float("nan")])
def test_prepare_rejects_nested_unsafe_numbers_before_database_access(location, value):
    service = object.__new__(Service)
    with pytest.raises(InterfaceForwardingContextError, match=rf"{location}.items\[0\].id") as exc:
        service.prepare(task_id=1, interface_id="example", **{location: {"items": [{"id": value}]}})
    assert exc.value.code == "unsafe_integer_input"


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        1.5,
        2**53 - 1,
        -(2**53 - 1),
        "2076587153191649281",
        ["2076586632527527938"],
    ],
)
def test_safe_caller_values_are_preserved(value):
    incoming = {"items": [{"id": value}]}
    before = json.dumps(incoming)
    Service._validate_caller_numbers(incoming, "body")
    assert json.dumps(incoming) == before


def test_prepare_rejects_root_numeric_array_before_database_access():
    with pytest.raises(InterfaceForwardingContextError, match=r"body\[0\]"):
        object.__new__(Service).prepare(task_id=1, interface_id="example", body=[2**53])


@pytest.mark.parametrize("body", [[123, 456], [], {"id": 123}])
def test_runner_preserves_body_shape(body):
    module = load_runner_module()
    request, _, _ = module.HostRuntimeRunner._forwarding_request(
        {
            "method": "POST",
            "url": "http://local.test/list",
            "body": body,
            "query": {},
            "headers": {},
            "timeout_seconds": 30,
            "max_response_bytes": 1048576,
        }
    )
    assert json.loads(request.data) == body


@pytest.mark.parametrize("body", [[123, 456], [], {"id": 123}])
def test_direct_preserves_body_shape(monkeypatch, body):
    real_client = httpx.Client

    def handle(request):
        assert json.loads(request.content) == body
        return httpx.Response(200, json={"code": 200})

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = object.__new__(Service)._execute_direct(
        method="POST",
        url="http://local.test/list",
        headers={},
        query_values={},
        body_values=body,
    )
    assert result["status_code"] == 200


def test_array_history_and_caller_replacement():
    values = {"path": {}, "query": {}, "body": {}}
    sources = {key: {} for key in values}
    evidence = {key: {} for key in values}
    historic, _ = Service._sanitize_history_values({"body": [1, 2]})
    Service._merge_values(values, sources, evidence, historic, "successful_history")
    Service._merge_values(values, sources, evidence, {"body": None}, "caller")
    assert values["body"] == [1, 2]
    Service._merge_values(values, sources, evidence, {"body": []}, "caller")
    assert values["body"] == []
    assert sources["body"] == {"$": "caller"}
    Service._merge_values(values, sources, evidence, {"body": {"id": 3}}, "caller")
    assert values["body"] == {"id": 3}


def test_array_history_strips_volatile_object_fields():
    values, _ = Service._sanitize_history_values({"body": [{"accessToken": "secret", "id": 1}]})
    assert values == {"path": {}, "query": {}, "body": [{"id": 1}]}


def test_array_contract_and_materialization():
    schema = {"type": "array", "items": {"type": "integer"}}
    contract = Service._normalize_contract({"body": schema}, "/list")
    assert Service._contract_summary(contract)["body_schema"] == schema
    values = {"path": {}, "query": {}, "body": []}
    Service._apply_defaults(values, {k: {} for k in values}, {k: {} for k in values}, contract)
    assert not Service._missing_required(contract, values)
    _, _, body = Service._materialize_request(
        "http://local.test", {"values": values, "path_template": "/list"}
    )
    assert body == []


@pytest.mark.parametrize(
    "body,valid",
    [([1, 2], True), ([], True), (["1"], False), ([True], False), ({"ids": [1]}, False)],
)
def test_array_element_validation(body, valid):
    contract = {"body": {"type": "array", "items": {"type": "integer"}}}
    assert (Service._body_validation_error(contract, body) is None) == valid


def test_object_contract_rejects_array():
    assert Service._body_validation_error({"body": {"type": "object"}}, []) == "type"


def test_big_integer_roundtrip():
    contract = {"body": {"type": "array", "items": {"type": "integer", "format": "int64"}}}
    caller = ["2075468122958659585"]
    body = Service._normalize_integer_array(contract, caller, caller=caller)
    assert body == [2075468122958659585]
    assert Service._safe_integer_view({"body": body}) == {"body": caller}
    assert Service._body_validation_error(contract, body) is None
    module = load_runner_module()
    request, _, _ = module.HostRuntimeRunner._forwarding_request(
        {
            "method": "POST",
            "url": "http://local.test/query",
            "body": body,
            "timeout_seconds": 30,
            "max_response_bytes": 1048576,
        }
    )
    assert request.data == b"[2075468122958659585]"
    assert Service._normalize_integer_array(contract, body, caller=None) == body


@pytest.mark.parametrize("value", [2075468122958659600, 2075468122958659585.0])
def test_unsafe_numeric_input_is_rejected(value):
    from context_router.services.interface_forwarding_context import InterfaceForwardingContextError

    with pytest.raises(InterfaceForwardingContextError, match="十进制字符串"):
        Service._normalize_integer_array(
            {"body": {"type": "array", "items": {"type": "integer"}}},
            [value],
            caller=[value],
        )


@pytest.mark.parametrize("value", ["1.5", "1e18", " 12", "01", True])
def test_invalid_integer_text_is_not_coerced(value):
    contract = {"body": {"type": "array", "items": {"type": "integer"}}}
    result = Service._normalize_integer_array(contract, [value], caller=[value])
    assert Service._body_validation_error(contract, result) == "type"


def test_int64_boundaries_and_string_arrays():
    from context_router.services.interface_forwarding_context import InterfaceForwardingContextError

    contract = {"body": {"type": "array", "items": {"type": "integer", "format": "int64"}}}
    for value in [str(-(2**63)), str(2**63 - 1)]:
        assert Service._normalize_integer_array(contract, [value], caller=[value]) == [int(value)]
    with pytest.raises(InterfaceForwardingContextError, match="int64"):
        Service._normalize_integer_array(contract, [str(2**63)], caller=[str(2**63)])
    assert Service._normalize_integer_array(
        {"body": {"type": "array", "items": {"type": "string"}}}, ["123"], caller=["123"]
    ) == ["123"]
