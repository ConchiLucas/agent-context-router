from pathlib import Path

from context_router.scripts.refresh_interface_request_contracts import (
    _path_contract,
    parse_controller,
)


def test_parse_controller_reads_path_and_query_annotations(tmp_path: Path) -> None:
    controller = tmp_path / "OrderController.java"
    controller.write_text(
        """
        @RequestMapping("/order-api/admin/order")
        public class OrderController {
            @GetMapping("/{orderId}")
            public Response get(
                @Parameter(description = "订单主键")
                @PathVariable("orderId") Long orderId,
                @RequestParam(value = "detail", required = false) Boolean detail) {
                return null;
            }
        }
        """,
        encoding="utf-8",
    )

    endpoints = parse_controller(controller)

    assert endpoints == [
        {
            "controller": "OrderController",
            "method": "GET",
            "path": "/order-api/admin/order/{orderId}",
            "method_name": "get",
            "parameters": {
                "path": [
                    {
                        "name": "orderId",
                        "required": True,
                        "schema": {"type": "integer", "description": "订单主键"},
                    }
                ],
                "query": [
                    {
                        "name": "detail",
                        "required": False,
                        "schema": {"type": "boolean"},
                    }
                ],
            },
        }
    ]


def test_path_contract_falls_back_for_imported_paths() -> None:
    assert _path_contract("/orders/{id}/{codes}", None) == {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "codes": {"type": "string"},
        },
        "required": ["id", "codes"],
    }
