from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "check_interface_search_quality.py"
SPEC = importlib.util.spec_from_file_location("check_interface_search_quality", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
QUALITY_GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALITY_GATE)


def _baseline() -> dict[str, object]:
    return {
        "quality_gates": {
            "minimum_case_count": 200,
            "minimum_final_accuracy": 0.95,
            "minimum_candidate_recall_at_k": 1.0,
            "minimum_selection_accuracy": 0.98,
            "maximum_retrieval_miss_count": 0,
        }
    }


def test_quality_gate_accepts_frozen_or_better_result() -> None:
    result = QUALITY_GATE.evaluate_quality_gate(
        {
            "metrics": {
                "case_count": 200,
                "final_accuracy": 0.955,
                "candidate_recall_at_k": 1.0,
                "selection_accuracy": 0.9891,
                "retrieval_miss_count": 0,
            }
        },
        _baseline(),
    )

    assert result["passed"] is True
    assert all(check["passed"] for check in result["checks"])


def test_quality_gate_reports_every_regression() -> None:
    result = QUALITY_GATE.evaluate_quality_gate(
        {
            "metrics": {
                "case_count": 199,
                "final_accuracy": 0.94,
                "candidate_recall_at_k": 0.995,
                "selection_accuracy": 0.97,
                "retrieval_miss_count": 1,
            }
        },
        _baseline(),
    )

    assert result["passed"] is False
    assert {check["metric"] for check in result["checks"] if not check["passed"]} == {
        "case_count",
        "final_accuracy",
        "candidate_recall_at_k",
        "selection_accuracy",
        "retrieval_miss_count",
    }
