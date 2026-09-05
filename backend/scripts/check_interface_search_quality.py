#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 必须是 JSON 对象")
    return payload


def evaluate_quality_gate(
    report: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    metrics = report.get("metrics")
    gates = baseline.get("quality_gates")
    if not isinstance(metrics, dict):
        raise ValueError("测评报告缺少 metrics 对象")
    if not isinstance(gates, dict):
        raise ValueError("基线文件缺少 quality_gates 对象")

    checks = [
        (
            "case_count",
            int(metrics.get("case_count", 0)),
            ">=",
            int(gates["minimum_case_count"]),
        ),
        (
            "final_accuracy",
            float(metrics.get("final_accuracy", 0.0)),
            ">=",
            float(gates["minimum_final_accuracy"]),
        ),
        (
            "candidate_recall_at_k",
            float(metrics.get("candidate_recall_at_k", 0.0)),
            ">=",
            float(gates["minimum_candidate_recall_at_k"]),
        ),
        (
            "selection_accuracy",
            float(metrics.get("selection_accuracy", 0.0)),
            ">=",
            float(gates["minimum_selection_accuracy"]),
        ),
        (
            "retrieval_miss_count",
            int(metrics.get("retrieval_miss_count", 0)),
            "<=",
            int(gates["maximum_retrieval_miss_count"]),
        ),
    ]
    results = [
        {
            "metric": name,
            "actual": actual,
            "operator": operator,
            "threshold": threshold,
            "passed": actual >= threshold if operator == ">=" else actual <= threshold,
        }
        for name, actual, operator, threshold in checks
    ]
    return {"passed": all(item["passed"] for item in results), "checks": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="检查接口语义检索报告是否达到冻结基线")
    parser.add_argument("--report", type=Path, required=True, help="待验收的测评报告 JSON")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path(__file__).parents[1]
        / "evaluations"
        / "interface-search-baseline-v1.json",
        help="质量门槛 JSON",
    )
    arguments = parser.parse_args()
    result = evaluate_quality_gate(
        _load_json(arguments.report),
        _load_json(arguments.baseline),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
