from context_router import mcp_server


def test_mcp_prepare_tool_calls_prepare_api(monkeypatch) -> None:
    mcp_server.CURRENT_TRACE_ID = None
    mcp_server.CURRENT_DOCUMENT_ID = "old-doc"
    mcp_server.CURRENT_DEPTH = 3
    requests: list[tuple[str, str, dict | None, dict | None]] = []

    def fake_request_json(
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        requests.append((method, path, json_body, params))
        return {
            "trace_id": "ctx_001",
            "project": "my-app",
            "task": "准备上下文：my-app/payments",
            "documents": [],
            "markdown": "project: my-app",
        }

    monkeypatch.setattr(mcp_server, "_request_json", fake_request_json)

    response = mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "prepare_task_context",
                "arguments": {
                    "project": "my-app",
                    "area": "payments",
                    "cwd": "/repo/my-app",
                    "entrypoint_path": "AI_CONTEXT_INDEX.md",
                    "entrypoint_rule": "payments tasks",
                    "route_hint": "payments",
                    "agent_name": "codex",
                },
            },
        }
    )

    assert requests == [
        (
            "POST",
            "/api/context/prepare",
            {
                "project": "my-app",
                "task": "",
                "area": "payments",
                "cwd": "/repo/my-app",
                "entrypoint_path": "AI_CONTEXT_INDEX.md",
                "entrypoint_rule": "payments tasks",
                "route_hint": "payments",
                "source": "mcp",
                "agent_name": "codex",
                "max_documents": 5,
                "output_format": "markdown",
            },
            None,
        )
    ]
    assert response is not None
    assert response["result"]["content"][0]["text"] == "project: my-app"
    assert mcp_server.CURRENT_TRACE_ID == "ctx_001"
    assert mcp_server.CURRENT_DOCUMENT_ID is None
    assert mcp_server.CURRENT_DEPTH == 0


def test_mcp_read_tool_calls_document_api(monkeypatch) -> None:
    mcp_server.CURRENT_TRACE_ID = "ctx_001"
    mcp_server.CURRENT_DOCUMENT_ID = "root-index"
    mcp_server.CURRENT_DEPTH = 1
    requests: list[tuple[str, str, dict | None, dict | None]] = []

    def fake_request_json(
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        requests.append((method, path, json_body, params))
        return {
            "id": "payments-runbook",
            "trace_id": "ctx_001",
            "title": "Payments runbook",
            "content_markdown": "# Payments\nRun tests.",
        }

    monkeypatch.setattr(mcp_server, "_request_json", fake_request_json)

    response = mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "read_context_document",
                "arguments": {
                    "document_id": "payments-runbook",
                },
            },
        }
    )

    assert requests == [
        (
            "GET",
            "/api/documents/payments-runbook",
            None,
            {
                "trace_id": "ctx_001",
                "parent_document_id": "root-index",
                "depth": 2,
                "source": "mcp",
            },
        )
    ]
    assert response is not None
    assert "Payments runbook" in response["result"]["content"][0]["text"]
    assert mcp_server.CURRENT_DOCUMENT_ID == "payments-runbook"
    assert mcp_server.CURRENT_DEPTH == 2


def test_mcp_lists_context_router_tools() -> None:
    response = mcp_server.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
    )

    assert response is not None
    tool_names = [tool["name"] for tool in response["result"]["tools"]]
    assert tool_names == ["prepare_task_context", "read_context_document"]
