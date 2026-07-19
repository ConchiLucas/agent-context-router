import json

from context_router import mcp_server


def test_mcp_prepare_uses_minimal_task_contract(monkeypatch) -> None:
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
            "task": "fix login timeout",
            "documents": [],
        }

    monkeypatch.setattr(mcp_server, "_request_json", fake_request_json)

    response = mcp_server.handle_request(
        _tool_call(
            "prepare_task_context",
            {
                "task": "fix login timeout",
                "cwd": "/repo/my-app",
                "agent_name": "codex",
            },
        )
    )

    assert requests == [
        (
            "POST",
            "/api/context/prepare",
            {
                "project": None,
                "task": "fix login timeout",
                "cwd": "/repo/my-app",
                "source": "mcp",
                "agent_name": "codex",
                "max_documents": 3,
                "output_format": "json",
            },
            None,
        )
    ]
    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["trace_id"] == "ctx_001"
    assert payload["documents"] == []


def test_mcp_read_forwards_explicit_trace_and_parent(monkeypatch) -> None:
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
            "id": "auth-debugging",
            "trace_id": "ctx_002",
            "title": "Auth debugging",
            "source_path": "docs/auth-debugging.md",
            "doc_type": "debugging",
            "area": "backend",
            "tags": ["auth"],
            "status": "active",
            "content_markdown": "# Auth debugging\nCheck token expiry.",
            "links": [],
        }

    monkeypatch.setattr(mcp_server, "_request_json", fake_request_json)

    response = mcp_server.handle_request(
        _tool_call(
            "read_context_document",
            {
                "trace_id": "ctx_002",
                "document_id": "auth-debugging",
                "parent_document_id": "auth-guide",
            },
        )
    )

    assert requests == [
        (
            "GET",
            "/api/documents/auth-debugging",
            None,
            {
                "trace_id": "ctx_002",
                "parent_document_id": "auth-guide",
                "source": "mcp",
            },
        )
    ]
    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["trace_id"] == "ctx_002"
    assert payload["document_id"] == "auth-debugging"
    assert payload["content_markdown"].startswith("# Auth debugging")


def test_mcp_lists_only_stateless_context_tools() -> None:
    response = mcp_server.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
    )

    assert response is not None
    tools = response["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "prepare_task_context",
        "read_context_document",
    ]
    assert tools[0]["inputSchema"]["required"] == ["task", "cwd"]
    assert tools[1]["inputSchema"]["required"] == ["trace_id", "document_id"]


def _tool_call(name: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
