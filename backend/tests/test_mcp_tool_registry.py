from __future__ import annotations

import asyncio

from context_router.mcp_server import create_context_router_mcp


class _UnusedService:
    def prepare(self, **_: object) -> None:
        raise AssertionError("tools/list must not execute tools")

    def read(self, **_: object) -> None:
        raise AssertionError("tools/list must not execute tools")


def test_progressive_actions_expose_complete_parameter_descriptions() -> None:
    server = create_context_router_mcp(  # type: ignore[arg-type]
        _UnusedService(),
        _UnusedService(),
    )

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    for tool_name in (
        "resolve_database_target",
        "execute_database_query",
        "prepare_forwarding_request",
        "inspect_container_errors",
    ):
        properties = tools[tool_name].inputSchema["properties"]
        assert properties
        assert all(property_schema.get("description") for property_schema in properties.values())

    discover = tools["discover_task_tools"].inputSchema
    invoke = tools["invoke_task_tool"].inputSchema
    assert discover["required"] == ["task_id", "query"]
    assert invoke["required"] == [
        "task_id",
        "tool_name",
        "arguments",
        "definition_revision",
    ]


def test_progressive_descriptions_distinguish_direct_and_professional_tools() -> None:
    server = create_context_router_mcp(  # type: ignore[arg-type]
        _UnusedService(),
        _UnusedService(),
    )

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    discover_description = tools["discover_task_tools"].description or ""
    invoke_description = tools["invoke_task_tool"].description or ""

    assert "never returns core navigation tools" in discover_description
    assert "call those directly" in discover_description
    assert "Pass the returned action name as tool_name, not action_name" in invoke_description
