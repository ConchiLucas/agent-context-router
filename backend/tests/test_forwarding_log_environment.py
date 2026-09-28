import re
from contextlib import nullcontext
from unittest.mock import MagicMock

import httpx
import pytest

from context_router.schemas.interface_forwarding import (
    InterfaceForwardingExecute,
    InterfaceForwardingLogWrite,
)
from context_router.services.interface_forwarding import (
    InterfaceForwardingError,
    InterfaceForwardingService,
)


def setup_service(monkeypatch, environment, path="/query"):
    service = InterfaceForwardingService("postgresql://unused")
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor
    monkeypatch.setattr(service, "_connect", lambda: connection)
    cursor.fetchone.side_effect = [
        {
            "id": "interface",
            "workspace_id": "workspace",
            "service_id": "service",
            "path": path,
            "method": "POST",
        },
        {
            "id": "address",
            "service_id": "service",
            "name": "Display label",
            "environment_key": environment,
            "workspace_environment_name": "Custom display",
            "base_url": "https://example.invalid",
        },
        {"id": "identity", "login_account": "tester", "role_name": "", "request_header": ""},
        {"id": "saved-log"},
    ]
    return service, cursor


def assert_log_environment(cursor, environment):
    inserts = []
    for call in cursor.execute.call_args_list:
        sql, params = call.args
        assert sql.count("%s") == len(params)
        if "INSERT INTO interface_forwarding_logs" in sql:
            columns = re.search(r"interface_forwarding_logs\s*\(([^)]+)\)", sql)[1]
            inserts.append(dict(zip((c.strip() for c in columns.split(",")), params, strict=True)))
    assert len(inserts) == 1
    assert inserts[0]["environment_key"] == environment
    assert inserts[0]["environment_name"] == "Custom display · Display label"
    address_query = next(
        call.args[0]
        for call in cursor.execute.call_args_list
        if "FROM interface_forwarding_environments" in call.args[0]
    )
    assert "forwarding.environment_key" in address_query.split("FROM")[0]


@pytest.mark.parametrize("environment", ["test", "uat", "custom-env"])
@pytest.mark.parametrize("outcome", [200, 404, 500, "timeout"])
def test_execute_persists_selected_environment_on_success_and_failure(
    monkeypatch, environment, outcome
):
    service, cursor = setup_service(monkeypatch, environment)
    client = MagicMock()
    if outcome == "timeout":
        client.request.side_effect = httpx.ReadTimeout("simulated")
    else:
        client.request.return_value = httpx.Response(outcome, json={"data": []})
    monkeypatch.setattr(
        "context_router.services.interface_forwarding.httpx.Client",
        lambda **kwargs: nullcontext(client),
    )
    result = service.execute(
        "interface",
        InterfaceForwardingExecute(
            environment_id="address",
            identity_id="identity",
            request_body="{}",
        ),
    )
    assert result["status_code"] == (None if outcome == "timeout" else outcome)
    client.request.assert_called_once()
    assert_log_environment(cursor, environment)


@pytest.mark.parametrize("environment", ["test", "uat", "custom-env"])
def test_external_log_persists_selected_environment(monkeypatch, environment):
    service, cursor = setup_service(monkeypatch, environment)
    service.record_external_log(
        "interface",
        InterfaceForwardingLogWrite(
            environment_id="address",
            identity_id="identity",
            duration_ms=5,
            status_code=200,
            success=True,
        ),
    )
    assert_log_environment(cursor, environment)


def test_execute_substitutes_and_logs_path_parameter(monkeypatch):
    service, cursor = setup_service(monkeypatch, "test", "/items/{id}")
    client = MagicMock()
    client.request.return_value = httpx.Response(200, json={"success": True})
    monkeypatch.setattr(
        "context_router.services.interface_forwarding.httpx.Client",
        lambda **kwargs: nullcontext(client),
    )
    service.execute(
        "interface",
        InterfaceForwardingExecute(
            environment_id="address", identity_id="identity", path_params={"id": 123}
        ),
    )
    assert client.request.call_args.args[1] == "https://example.invalid/items/123"
    log_call = next(
        call for call in cursor.execute.call_args_list
        if "INSERT INTO interface_forwarding_logs" in call.args[0]
    )
    assert "https://example.invalid/items/123" in log_call.args[1]


@pytest.mark.parametrize("path_params", [{}, {"id": ".."}, {"id": "123/456"}, {"other": 1}])
def test_execute_rejects_invalid_path_parameter_before_http(monkeypatch, path_params):
    service, cursor = setup_service(monkeypatch, "test", "/items/{id}")
    client = MagicMock()
    monkeypatch.setattr(
        "context_router.services.interface_forwarding.httpx.Client",
        lambda **kwargs: nullcontext(client),
    )
    with pytest.raises(InterfaceForwardingError):
        service.execute(
            "interface",
            InterfaceForwardingExecute(environment_id="address", path_params=path_params),
        )
    client.request.assert_not_called()
