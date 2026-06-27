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
                "project": {"type": "string"},
                "task": {"type": "string"},
                "area": {"type": "string"},
                "cwd": {"type": "string"},
                "entrypoint_path": {"type": "string"},
                "entrypoint_rule": {"type": "string"},
                "route_hint": {"type": "string"},
                "agent_name": {"type": "string"},
                "max_documents": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["project", "task"],
        },
    },
    {
        "name": "read_context_document",
        "description": "Read a full context document and record the reason in a trace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "trace_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["document_id", "trace_id", "reason"],
        },
    },
]


def api_url() -> str:
    return os.environ.get("CTX_API_URL", DEFAULT_API_URL).rstrip("/")


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


def _call_tool(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    try:
        if name == "prepare_task_context":
            return _text_result(_prepare_task_context(arguments))
        if name == "read_context_document":
            return _text_result(_read_context_document(arguments))
    except httpx.HTTPError as exc:
        return _text_result(f"Context router API error: {exc}", is_error=True)

    return _text_result(f"Unknown tool: {name}", is_error=True)


def _prepare_task_context(arguments: dict[str, Any]) -> str:
    body = _request_json(
        "POST",
        "/api/context/prepare",
        json_body={
            "project": arguments["project"],
            "task": arguments["task"],
            "area": arguments.get("area"),
            "cwd": arguments.get("cwd"),
            "entrypoint_path": arguments.get("entrypoint_path"),
            "entrypoint_rule": arguments.get("entrypoint_rule"),
            "route_hint": arguments.get("route_hint"),
            "source": "mcp",
            "agent_name": arguments.get("agent_name"),
            "max_documents": arguments.get("max_documents", 5),
            "output_format": "markdown",
        },
    )
    return body["markdown"]


def _read_context_document(arguments: dict[str, Any]) -> str:
    body = _request_json(
        "GET",
        f"/api/documents/{arguments['document_id']}",
        params={
            "trace_id": arguments["trace_id"],
            "reason": arguments["reason"],
            "source": "mcp",
        },
    )
    metadata = {
        "document_id": body["id"],
        "title": body["title"],
        "source_path": body.get("source_path"),
        "doc_type": body.get("doc_type"),
        "area": body.get("area"),
        "tags": body.get("tags", []),
        "status": body.get("status"),
    }
    return f"{json.dumps(metadata, ensure_ascii=False, indent=2)}\n\n{body['content_markdown']}"


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
