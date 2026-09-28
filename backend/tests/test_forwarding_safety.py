from contextlib import nullcontext

import pytest
from test_host_runtime_runner import load_runner_module

from context_router.services.forwarding_safety import is_sse_control
from context_router.services.interface_forwarding_context import (
    InterfaceForwardingContextError,
    InterfaceForwardingContextService,
)


@pytest.mark.parametrize("action", ["connect", "disconnect", "subscribe", "unsubscribe"])
@pytest.mark.parametrize("prefix", ["/api", "/rest/mtp/api", "/other"])
def test_sse_control_rejected_before_network(action, prefix):
    path = f"{prefix}/sse/{action}/?x=1"
    assert is_sse_control(path)
    module = load_runner_module()
    with pytest.raises(module.RunnerSecurityError, match="SSE"):
        module.HostRuntimeRunner._forwarding_request(
            {
                "method": "GET",
                "url": "http://local.test" + path,
                "timeout_seconds": 30,
                "max_response_bytes": 1048576,
            }
        )


def test_unrelated_reads_not_blocked():
    assert not is_sse_control("/api/sse/status")
    assert not is_sse_control("/api/orders/connect")
    assert is_sse_control("/api//sse/%64isconnect")


@pytest.mark.parametrize("stage", ["prepare", "execute"])
def test_service_gate_blocks_even_read_metadata(monkeypatch, stage):
    service = object.__new__(InterfaceForwardingContextService)
    monkeypatch.setattr(service, "_task_scope", lambda *args: ("workspace", "test"))

    class Cursor:
        def execute(self, *args):
            pass

        def fetchone(self):
            return {"path": "/api/sse/disconnect", "request_payload": {}}

    class Connection:
        def cursor(self):
            return nullcontext(Cursor())

    monkeypatch.setattr(service, "_connect", lambda: nullcontext(Connection()))
    monkeypatch.setattr(
        service,
        "_load_interface",
        lambda *args: {
            "path": "/api/sse/disconnect",
            "operation_kind": "read",
        },
    )
    with pytest.raises(InterfaceForwardingContextError) as exc:
        if stage == "prepare":
            service.prepare(task_id=1, interface_id="interface")
        else:
            service.execute(task_id=1, plan_id="plan", request_sha256="hash")
    assert exc.value.code == "sse_control_not_supported"
