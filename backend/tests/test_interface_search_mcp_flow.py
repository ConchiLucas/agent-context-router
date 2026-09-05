from __future__ import annotations

import asyncio

from context_router.mcp_server import create_context_router_mcp


class _Result:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self, **_: object) -> dict[str, object]:
        return self._payload


class _PreparationService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def prepare(self, **arguments: object) -> _Result:
        self.calls.append(arguments)
        return _Result(
            {
                "task_id": 1081,
                "execution_contract": {
                    "intent_type": "interface_search",
                    "mutation_policy": "forbidden",
                    "required_steps": ["search_forwarding_interfaces"],
                },
            }
        )


class _UnusedDocumentService:
    pass


class _InterfaceSearchService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def search(self, **arguments: object) -> dict[str, object]:
        self.calls.append(("search", arguments))
        return {
            "status": "ok",
            "mode": "ai_candidates",
            "results": [
                {
                    "interface_id": "interface-a",
                    "method": "POST",
                    "path": "/api/widgets/page",
                },
                {
                    "interface_id": "interface-b",
                    "method": "POST",
                    "path": "/api/widgets/by-ids",
                },
            ],
        }

    def compare(self, **arguments: object) -> dict[str, object]:
        self.calls.append(("compare", arguments))
        return {
            "items": [
                {"interface_id": "interface-a", "cardinality": "many", "action": "page"},
                {"interface_id": "interface-b", "cardinality": "many", "action": "list"},
            ]
        }

    def detail(self, **arguments: object) -> dict[str, object]:
        self.calls.append(("detail", arguments))
        return {
            "interface_id": arguments["interface_id"],
            "method": "POST",
            "path": "/api/widgets/by-ids",
            "required_inputs": [{"name": "ids", "location": "body", "required": True}],
        }

    def prepare(self, **_: object) -> dict[str, object]:
        raise AssertionError("只读接口检索不得准备接口请求")

    def execute(self, **_: object) -> dict[str, object]:
        raise AssertionError("只读接口检索不得执行接口请求")


def test_interface_search_mcp_progressive_read_only_flow() -> None:
    async def scenario() -> None:
        preparation = _PreparationService()
        forwarding = _InterfaceSearchService()
        server = create_context_router_mcp(  # type: ignore[arg-type]
            preparation,
            _UnusedDocumentService(),
            interface_forwarding_context_service=forwarding,  # type: ignore[arg-type]
        )

        _, prepared = await server.call_tool(
            "prepare_task_context",
            {
                "task": "按一组主键批量查询组件，不要分页",
                "cwd": "/workspace/example",
                "agent_name": "codex",
                "intent_type": "interface_search",
            },
        )
        _, searched = await server.call_tool(
            "search_forwarding_interfaces",
            {"task_id": 1081, "query": "按一组主键批量查询组件，不要分页", "limit": 10},
        )
        candidate_ids = [item["interface_id"] for item in searched["results"]]
        _, compared = await server.call_tool(
            "compare_forwarding_interfaces",
            {"task_id": 1081, "interface_ids": candidate_ids},
        )
        _, detail = await server.call_tool(
            "read_forwarding_interface_detail",
            {"task_id": 1081, "interface_id": "interface-b"},
        )

        assert prepared["execution_contract"] == {
            "intent_type": "interface_search",
            "mutation_policy": "forbidden",
            "required_steps": ["search_forwarding_interfaces"],
        }
        assert len(compared["items"]) == 2
        assert detail["path"] == "/api/widgets/by-ids"
        assert forwarding.calls == [
            (
                "search",
                {
                    "task_id": 1081,
                    "query": "按一组主键批量查询组件，不要分页",
                    "service": None,
                    "role": None,
                    "limit": 10,
                },
            ),
            (
                "compare",
                {"task_id": 1081, "interface_ids": ["interface-a", "interface-b"]},
            ),
            ("detail", {"task_id": 1081, "interface_id": "interface-b"}),
        ]

    asyncio.run(scenario())
