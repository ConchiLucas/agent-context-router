import json

import pytest

from context_router.schemas.interface_forwarding import BrowserInterfaceCapture
from context_router.services.interface_forwarding import InterfaceForwardingService as Service
from context_router.services.interface_request_status import request_status


@pytest.mark.parametrize(
    "body,missing,code,expected,success",
    [
        ({"code": 9000}, False, 200, "business_error", False),
        ({"code": 200, "data": []}, False, 200, "no_data", True),
        ({"code": 200, "data": [1]}, False, 200, "has_data", True),
        (None, True, 200, "requested", False),
        (None, False, 200, "no_data", True),
        ({"_truncated": True, "preview": "abc"}, False, 200, "requested", False),
        ({"_capture_kind": "binary"}, False, 200, "requested", True),
        ({"_capture_kind": "text"}, False, 200, "requested", False),
        (None, True, 404, "not_found", False),
        ({"code": 200}, False, 500, "error", False),
        ({"code": 200}, False, 200, "requested", True),
    ],
)
def test_browser_status(body, missing, code, expected, success):
    capture = BrowserInterfaceCapture(
        url="http://local.test/query",
        method="POST",
        status_code=code,
        response_body=body,
        response_body_missing=missing,
    )
    observed = Service._browser_response(capture)
    saved, truncated, _ = Service._bounded_json(observed, 1000)
    actual_success = Service._browser_success(capture, observed, truncated)
    assert actual_success == success
    assert (
        request_status(
            requested=True,
            operation_kind="read",
            status_code=code,
            success=actual_success,
            response_body=saved,
            truncated=truncated,
        )
        == expected
    )


def test_server_truncation_is_unknown_not_data_or_error():
    capture = BrowserInterfaceCapture(
        url="http://local.test/query",
        method="POST",
        status_code=200,
        response_body={"data": ["x" * 500]},
    )
    saved, truncated, _ = Service._bounded_json(capture.response_body, 100)
    assert truncated
    assert not Service._browser_success(capture, capture.response_body, truncated)
    assert (
        request_status(
            requested=True,
            operation_kind="read",
            status_code=200,
            success=False,
            response_body=saved,
            truncated=True,
        )
        == "requested"
    )


def test_jsonb_safety_and_legacy_binary():
    value = Service._postgres_safe_json({"body": ["a\x00b"], "\x00key": "value"})
    assert "\x00" not in repr(value)
    assert value["body"] == ["a\\u0000b"]
    assert json.loads(json.dumps(value)) == value
    capture = BrowserInterfaceCapture(
        url="http://local.test/query", method="POST", status_code=200, response_body="PK\x00binary"
    )
    assert Service._browser_response(capture)["_capture_kind"] == "binary"
