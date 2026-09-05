from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "score_interface_search_clients.py"
SPEC = importlib.util.spec_from_file_location("score_interface_search_clients", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
SCORER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCORER)


def _gold() -> dict[str, object]:
    return {
        "cases": [
            {
                "case_id": "case-1",
                "category": "common",
                "query": "按一组主键查询组件，不分页",
                "expected_decision": "selected",
                "acceptable_interfaces": [
                    {
                        "interface_id": "interface-a",
                        "service": "widget-service",
                        "method": "POST",
                        "path": "/widgets/by-ids",
                    }
                ],
            },
            {
                "case_id": "case-2",
                "category": "intentional_ambiguity",
                "query": "查询组件分页",
                "expected_decision": "clarify",
                "acceptable_interfaces": [
                    {
                        "interface_id": "interface-admin",
                        "service": "widget-service",
                        "method": "POST",
                        "path": "/admin/widgets/page",
                    },
                    {
                        "interface_id": "interface-portal",
                        "service": "widget-service",
                        "method": "POST",
                        "path": "/portal/widgets/page",
                    },
                ],
            },
        ]
    }


def _result() -> dict[str, object]:
    return {
        "client": "codex",
        "cases": [
            {
                "case_id": "case-1",
                "query": "按一组主键查询组件，不分页",
                "status": "completed",
                "error": None,
                "decision": "selected",
                "selected_interface": {
                    "interface_id": "interface-a",
                    "service": "widget-service",
                    "method": "post",
                    "path": "/widgets/by-ids",
                },
                "candidate_interfaces": [
                    {
                        "interface_id": "interface-a",
                        "service": "widget-service",
                        "method": "POST",
                        "path": "/widgets/by-ids",
                    },
                    {
                        "interface_id": "interface-page",
                        "service": "widget-service",
                        "method": "POST",
                        "path": "/widgets/page",
                    },
                ],
                "tool_calls": [
                    "prepare_task_context",
                    "search_forwarding_interfaces",
                    "read_forwarding_interface_detail",
                ],
            },
            {
                "case_id": "case-2",
                "query": "查询组件分页",
                "status": "completed",
                "error": None,
                "decision": "clarify",
                "selected_interface": None,
                "candidate_interfaces": [
                    {
                        "interface_id": "interface-admin",
                        "service": "widget-service",
                        "method": "POST",
                        "path": "/admin/widgets/page",
                    },
                    {
                        "interface_id": "interface-portal",
                        "service": "widget-service",
                        "method": "POST",
                        "path": "/portal/widgets/page",
                    },
                ],
                "tool_calls": [
                    "prepare_task_context",
                    "search_forwarding_interfaces",
                    "compare_forwarding_interfaces",
                ],
            },
        ],
    }


def test_score_client_counts_retrieval_selection_and_clarification() -> None:
    scored = SCORER.score_client(_gold(), _result())

    assert scored["metrics"] == {
        "case_count": 2,
        "mcp_success_count": 2,
        "mcp_success_rate": 1.0,
        "candidate_ready_count": 2,
        "candidate_recall_at_k": 1.0,
        "retrieval_miss_count": 0,
        "final_correct": 2,
        "final_accuracy": 1.0,
        "selected_count": 1,
        "selected_correct": 1,
        "selection_accuracy": 1.0,
        "protocol_violation_count": 0,
        "prohibited_tool_call_count": 0,
        "out_of_candidate_selection_count": 0,
    }


def test_score_client_detects_prohibited_and_out_of_candidate_selection() -> None:
    result = _result()
    selected = result["cases"][0]  # type: ignore[index]
    selected["selected_interface"] = {
        "interface_id": "invented-interface",
        "service": "widget-service",
        "method": "DELETE",
        "path": "/widgets/1",
    }
    selected["tool_calls"].append("mcp__context_router__execute_forwarding_request")

    scored = SCORER.score_client(_gold(), result)

    assert scored["metrics"]["final_accuracy"] == 0.5
    assert scored["metrics"]["prohibited_tool_call_count"] == 1
    assert scored["metrics"]["out_of_candidate_selection_count"] == 1


def test_score_client_treats_missing_progressive_step_as_protocol_failure() -> None:
    result = _result()
    selected = result["cases"][0]  # type: ignore[index]
    selected["tool_calls"] = ["prepare_task_context", "search_forwarding_interfaces"]

    scored = SCORER.score_client(_gold(), result)

    assert scored["metrics"]["mcp_success_rate"] == 0.5
    assert scored["metrics"]["protocol_violation_count"] == 1
    assert scored["case_results"][0]["missing_required_tools"] == [
        "read_forwarding_interface_detail"
    ]
