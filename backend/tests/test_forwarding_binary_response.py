"""Local-only regression tests: no business endpoint or persistent data writes."""

import hashlib
from contextlib import nullcontext

import httpx
import pytest
from test_host_runtime_runner import load_runner_module

from context_router.services.interface_forwarding_context import (
    InterfaceForwardingContextService,
    _response_preview,
)


@pytest.mark.parametrize(
    ("content", "media_type", "binary"),
    [
        (b"%PDF\x00\xff", "application/pdf", True),
        (b"PK\x00\xff", "application/zip", True),
        (b"abc", "application/octet-stream", True),
        (b"a\x00b", "", True),
        (b'{"code":200,"data":[]}', "application/json", False),
        (b'{"value":"\\u0000"}', "application/json", False),
        (b'{"code":400}', "application/problem+json", False),
        ("中文".encode(), "text/plain; charset=utf-8", False),
    ],
)
def test_preview_runner_backend_parity(content, media_type, binary):
    preview = _response_preview(content, media_type)
    assert preview == load_runner_module()._response_preview(content, media_type)
    assert "\x00" not in preview
    if binary:
        assert preview.startswith("[binary response omitted;")
        assert f"retained_bytes={len(content)}" in preview
        assert hashlib.sha256(content).hexdigest() in preview
        assert len(preview) < 200
    else:
        assert preview == content.decode()


@pytest.mark.parametrize("status_code", [200, 404, 500])
def test_direct_binary_response_preserves_http_status(monkeypatch, status_code):
    real_client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code, content=b"PK\x00\xff", headers={"content-type": "application/zip"}
        )
    )
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs)
    )
    service = object.__new__(InterfaceForwardingContextService)
    result = service._execute_direct(
        method="GET", url="http://local.test/download", headers={}, query_values={}, body_values={}
    )
    assert result["status_code"] == status_code
    assert result["error_type"] is None
    assert result["response_bytes"] == 4
    assert result["response_truncated"] is False
    assert result["response_body"].startswith("[binary response omitted;")


@pytest.mark.parametrize("large", [False, True])
def test_old_runner_completion_cannot_store_nul(monkeypatch, large):
    class Cursor:
        parameters = None

        def execute(self, sql, parameters):
            if "UPDATE" in sql:
                self.parameters = parameters

        def fetchone(self):
            return {
                "status": "leased",
                "runner_id": "runner",
                "lease_token_hash": hashlib.sha256(b"token").hexdigest(),
            }

    cursor = Cursor()

    class Connection:
        def cursor(self):
            return nullcontext(cursor)

    service = object.__new__(InterfaceForwardingContextService)
    monkeypatch.setattr(service, "_connect", lambda: nullcontext(Connection()))
    service.complete_host_job(
        job_id="job",
        runner_id="runner",
        lease_token="token",
        status_code=200,
        response_body="PK\x00binary" if not large else "\x00" * 1_048_576,
        response_headers={"content-type": "x\x00y"},
        response_bytes=9,
        response_truncated=False,
        error_type=None,
        duration_ms=1,
    )
    params = cursor.parameters
    assert params[0] == "completed"
    assert params[1] == 200
    assert "\x00" not in params[2]
    if large:
        assert len(params[2].encode()) <= 1_048_576
        assert params[5] is True
    else:
        assert params[2] == "PK\\u0000binary"
    assert params[3].obj == {"content-type": "x\\u0000y"}
