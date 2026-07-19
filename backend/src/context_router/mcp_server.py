from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

DEFAULT_API_URL = "http://127.0.0.1:8000"
PROTOCOL_VERSION = "2024-11-05"


TOOLS = [
    {
        "name": "prepare_task_context",
        "description": "Return a compact context package for an AI coding task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "minLength": 1},
                "cwd": {"type": "string", "minLength": 1},
                "project": {"type": "string"},
                "agent_name": {"type": "string"},
            },
            "required": ["task", "cwd"],
        },
    },
    {
        "name": "read_context_document",
        "description": "Read a full context document. Trace recording is handled internally.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "minLength": 1},
                "document_id": {"type": "string", "minLength": 1},
                "parent_document_id": {"type": "string"},
            },
            "required": ["trace_id", "document_id"],
        },
    },
]


def api_url() -> str:
    return os.environ.get("CONTEXT_ROUTER_API_URL", DEFAULT_API_URL).rstrip("/")


def _request_json(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        response = client.request(
            method,
            f"{api_url()}{path}",
            json=json_body,
            params=params,
        )
        response.raise_for_status()
        return response.json()


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _result(
            message_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "agent-context-router",
                    "version": "0.1.0",
                },
            },
        )
    if method == "tools/list":
        return _result(message_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        return _result(message_id, _call_tool(params))

    return _error(message_id, code=-32601, message=f"Unknown method: {method}")


def _call_tool(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        return _text_result("Invalid arguments: tool call params must be an object", is_error=True)

    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _text_result("Invalid arguments: arguments must be an object", is_error=True)

    try:
        if name == "prepare_task_context":
            return _text_result(_prepare_task_context(arguments))
        if name == "read_context_document":
            return _text_result(_read_context_document(arguments))
    except (KeyError, TypeError, ValueError) as exc:
        return _text_result(f"Invalid arguments: {exc}", is_error=True)
    except httpx.HTTPError as exc:
        return _text_result(f"Context router API error: {exc}", is_error=True)
    except Exception as exc:  # Keep one malformed request from terminating the stdio server.
        return _text_result(
            f"Unexpected Context Router error: {type(exc).__name__}",
            is_error=True,
        )

    return _text_result(f"Unknown tool: {name}", is_error=True)


def _prepare_task_context(arguments: dict[str, Any]) -> str:
    body = _request_json(
        "POST",
        "/api/context/prepare",
        json_body={
            "project": _optional_string(arguments, "project"),
            "task": _required_string(arguments, "task"),
            "cwd": _required_string(arguments, "cwd"),
            "source": "mcp",
            "agent_name": _optional_string(arguments, "agent_name"),
            "max_documents": 3,
            "output_format": "json",
        },
    )
    result = {
        "trace_id": body["trace_id"],
        "project": body["project"],
        "task": body["task"],
        "documents": body.get("documents", []),
    }
    return json.dumps(result, ensure_ascii=False)


def _read_context_document(arguments: dict[str, Any]) -> str:
    trace_id = _required_string(arguments, "trace_id")
    document_id = _required_string(arguments, "document_id")
    params = {
        "trace_id": trace_id,
        "source": "mcp",
    }
    parent_document_id = _optional_string(arguments, "parent_document_id")
    if parent_document_id:
        params["parent_document_id"] = parent_document_id

    body = _request_json(
        "GET",
        f"/api/documents/{document_id}",
        params=params,
    )
    result = {
        "trace_id": body.get("trace_id"),
        "document_id": body["id"],
        "title": body["title"],
        "source_path": body.get("source_path"),
        "doc_type": body.get("doc_type"),
        "area": body.get("area"),
        "tags": body.get("tags", []),
        "status": body.get("status"),
        "content_markdown": body["content_markdown"],
        "links": [
            {
                "document_id": link["target_document_id"],
                "label": link["label"],
            }
            for link in body.get("links", [])
            if link.get("target_document_id")
        ],
    }
    return json.dumps(result, ensure_ascii=False)


def _required_string(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_string(arguments: dict[str, Any], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value.strip() or None


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return result


def _result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Any, *, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        response = handle_request(json.loads(line))
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
