import asyncio

from context_router.mcp_server import create_context_router_mcp


class UnusedService:
    def prepare(self, **_: object) -> None:
        raise AssertionError("tools/list must not call prepare")

    def read(self, **_: object) -> None:
        raise AssertionError("tools/list must not call read")


def test_mcp_exposes_prepare_and_read_tools() -> None:
    service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        service,
        service,
    )

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == [
        "prepare_task_context",
        "read_context_document",
    ]
