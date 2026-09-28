from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "import_browser_har.py"
SPEC = importlib.util.spec_from_file_location("import_browser_har", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_har_to_captures_extracts_payload_without_headers() -> None:
    response = base64.b64encode(b'{"ok":true}').decode("ascii")
    captures = MODULE.har_to_captures(
        {
            "log": {
                "entries": [
                    {
                        "time": 42.4,
                        "request": {
                            "method": "post",
                            "url": "https://example.test/api/orders?token=secret",
                            "headers": [{"name": "Authorization", "value": "Bearer secret"}],
                            "postData": {"text": '{"password":"secret","name":"demo"}'},
                        },
                        "response": {
                            "status": 201,
                            "headers": [{"name": "Set-Cookie", "value": "secret"}],
                            "content": {"text": response, "encoding": "base64"},
                        },
                    }
                ]
            }
        }
    )

    assert captures == [
        {
            "url": "https://example.test/api/orders?token=secret",
            "method": "POST",
            "request_body": {"password": "secret", "name": "demo"},
            "response_body": {"ok": True},
            "status_code": 201,
            "duration_ms": 42,
        }
    ]
    assert "headers" not in captures[0]


def test_har_to_captures_rejects_missing_entries() -> None:
    try:
        MODULE.har_to_captures({"log": {}})
    except ValueError as exc:
        assert str(exc) == "HAR 缺少 log.entries 数组"
    else:
        raise AssertionError("缺少 entries 时必须失败")


def test_select_environment_address_uses_environment_origin_and_capture_path() -> None:
    selected = MODULE.select_environment_address(
        [
            {
                "environment_key": "test",
                "addresses": [
                    {
                        "id": "portal-address",
                        "service_name": "Portal",
                        "name": "TEST",
                        "base_url": "http://192.168.0.222:18080/rest/portal",
                    },
                    {
                        "id": "mtp-address",
                        "service_name": "MTP",
                        "name": "TEST",
                        "base_url": "http://192.168.0.222:18080/rest/mtp",
                    },
                ],
            },
            {
                "environment_key": "uat",
                "addresses": [
                    {
                        "id": "uat-address",
                        "service_name": "MTP",
                        "name": "UAT",
                        "base_url": "http://192.168.0.222:28080/rest/mtp",
                    }
                ],
            },
        ],
        environment_key="test",
        entry_url="http://192.168.0.222:18080/op/login",
        captures=[{"url": "http://192.168.0.222:18080/rest/mtp/order-api/orders"}],
    )

    assert selected["id"] == "mtp-address"


def test_select_environment_address_rejects_wrong_origin() -> None:
    try:
        MODULE.select_environment_address(
            [
                {
                    "environment_key": "uat",
                    "addresses": [
                        {
                            "id": "uat-address",
                            "base_url": "http://192.168.0.222:28080/rest/mtp",
                        }
                    ],
                }
            ],
            environment_key="uat",
            entry_url="http://192.168.0.222:18080/op/login",
            captures=[],
        )
    except ValueError as exc:
        assert "同源" in str(exc)
    else:
        raise AssertionError("入口端口与转发地址不一致时必须失败")
