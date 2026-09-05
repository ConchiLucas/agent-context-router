#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

PROHIBITED_TOOLS = {
    "apply_workspace_changes",
    "execute_forwarding_request",
    "prepare_forwarding_request",
    "start_workspace",
}
BASE_REQUIRED_TOOLS = {"prepare_task_context", "search_forwarding_interfaces"}


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 必须是 JSON 对象")
    return payload


def _identity(value: dict[str, Any] | None) -> tuple[str, str, str, str] | None:
    if value is None:
        return None
    interface_id = str(value.get("interface_id", "")).strip()
    service = str(value.get("service", "")).strip()
    method = str(value.get("method", "")).strip().upper()
    path = str(value.get("path", "")).strip()
    if not interface_id or not service or not method or not path:
        raise ValueError("接口必须同时包含 interface_id、service、method 和 path")
    return interface_id, service, method, path


def _tool_name(value: str) -> str:
    return value.rsplit("__", 1)[-1].rsplit(".", 1)[-1]


def _unique_cases(payload: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError(f"{label} 缺少 cases 数组")
    cases: dict[str, dict[str, Any]] = {}
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError(f"{label} cases 元素必须是对象")
        case_id = str(raw.get("case_id", "")).strip()
        if not case_id or case_id in cases:
            raise ValueError(f"{label} 存在空或重复 case_id: {case_id!r}")
        cases[case_id] = raw
    return cases


def _category_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    counts: dict[str, Counter[str]] = {}
    for row in rows:
        category = str(row.get("category") or "unknown")
        current = counts.setdefault(category, Counter())
        current["total"] += 1
        current["ready"] += int(row["retrieval_ready"])
        current["correct"] += int(row["final_correct"])
    return {
        category: {
            "total": values["total"],
            "ready": values["ready"],
            "correct": values["correct"],
            "recall": round(values["ready"] / values["total"], 4),
            "accuracy": round(values["correct"] / values["total"], 4),
        }
        for category, values in sorted(counts.items())
    }


def score_client(
    gold_payload: dict[str, Any],
    result_payload: dict[str, Any],
) -> dict[str, Any]:
    gold = _unique_cases(gold_payload, "gold")
    results = _unique_cases(result_payload, "result")
    if set(gold) != set(results):
        raise ValueError(
            "结果题号与金标不一致: "
            f"missing={sorted(set(gold) - set(results))}, "
            f"unexpected={sorted(set(results) - set(gold))}"
        )

    rows: list[dict[str, Any]] = []
    for case_id, expected in gold.items():
        actual = results[case_id]
        query = str(expected.get("query", ""))
        if actual.get("query") != query:
            raise ValueError(f"{case_id}: 结果 query 与金标不一致")
        expected_decision = expected.get("expected_decision")
        if expected_decision not in {"selected", "clarify"}:
            raise ValueError(f"{case_id}: expected_decision 非法")
        acceptable_raw = expected.get("acceptable_interfaces")
        if not isinstance(acceptable_raw, list) or not acceptable_raw:
            raise ValueError(f"{case_id}: acceptable_interfaces 不能为空")
        acceptable = {_identity(item) for item in acceptable_raw}
        candidates_raw = actual.get("candidate_interfaces")
        if not isinstance(candidates_raw, list):
            raise ValueError(f"{case_id}: candidate_interfaces 必须是数组")
        candidates = [_identity(item) for item in candidates_raw]
        candidate_set = set(candidates)
        selected = _identity(actual.get("selected_interface"))
        decision = actual.get("decision")
        status = actual.get("status")
        tools = actual.get("tool_calls")
        if not isinstance(tools, list) or not all(isinstance(item, str) for item in tools):
            raise ValueError(f"{case_id}: tool_calls 必须是字符串数组")
        normalized_tools = {_tool_name(item) for item in tools}
        required_tools = set(BASE_REQUIRED_TOOLS)
        if decision == "selected":
            required_tools.add("read_forwarding_interface_detail")
        missing_required_tools = sorted(required_tools - normalized_tools)
        prohibited = sorted(PROHIBITED_TOOLS & normalized_tools)
        out_of_candidates = selected is not None and selected not in candidate_set
        retrieval_ready = (
            acceptable <= candidate_set
            if expected_decision == "clarify"
            else bool(acceptable & candidate_set)
        )
        final_correct = (
            decision == "clarify"
            if expected_decision == "clarify"
            else decision == "selected" and selected in acceptable
        )
        rows.append(
            {
                "case_id": case_id,
                "category": expected.get("category"),
                "query": query,
                "expected_decision": expected_decision,
                "acceptable_interfaces": [
                    {
                        "interface_id": interface_id,
                        "service": service,
                        "method": method,
                        "path": path,
                    }
                    for interface_id, service, method, path in sorted(
                        item for item in acceptable if item is not None
                    )
                ],
                "status": status,
                "decision": decision,
                "selected_interface": (
                    {
                        "interface_id": selected[0],
                        "service": selected[1],
                        "method": selected[2],
                        "path": selected[3],
                    }
                    if selected
                    else None
                ),
                "retrieval_ready": retrieval_ready,
                "final_correct": final_correct,
                "prohibited_tools": prohibited,
                "missing_required_tools": missing_required_tools,
                "out_of_candidate_selection": out_of_candidates,
                "error": actual.get("error"),
            }
        )

    case_count = len(rows)
    if case_count == 0:
        raise ValueError("测评题集不能为空")
    completed = sum(
        row["status"] == "completed"
        and not row["error"]
        and not row["missing_required_tools"]
        for row in rows
    )
    ready = sum(row["retrieval_ready"] for row in rows)
    correct = sum(row["final_correct"] for row in rows)
    selected_rows = [row for row in rows if row["decision"] == "selected"]
    selected_correct = sum(row["final_correct"] for row in selected_rows)
    metrics = {
        "case_count": case_count,
        "mcp_success_count": completed,
        "mcp_success_rate": round(completed / case_count, 4),
        "candidate_ready_count": ready,
        "candidate_recall_at_k": round(ready / case_count, 4),
        "retrieval_miss_count": case_count - ready,
        "final_correct": correct,
        "final_accuracy": round(correct / case_count, 4),
        "selected_count": len(selected_rows),
        "selected_correct": selected_correct,
        "selection_accuracy": (
            round(selected_correct / len(selected_rows), 4) if selected_rows else None
        ),
        "protocol_violation_count": sum(bool(row["missing_required_tools"]) for row in rows),
        "prohibited_tool_call_count": sum(len(row["prohibited_tools"]) for row in rows),
        "out_of_candidate_selection_count": sum(
            row["out_of_candidate_selection"] for row in rows
        ),
    }
    return {
        "client": result_payload.get("client"),
        "metrics": metrics,
        "category_metrics": _category_metrics(rows),
        "errors": [row for row in rows if not row["final_correct"]],
        "case_results": rows,
    }


def _gate(result: dict[str, Any], gates: dict[str, Any]) -> dict[str, Any]:
    metrics = result["metrics"]
    definitions = [
        ("case_count", ">=", "minimum_case_count"),
        ("mcp_success_rate", ">=", "minimum_mcp_success_rate"),
        ("candidate_recall_at_k", ">=", "minimum_candidate_recall_at_k"),
        ("final_accuracy", ">=", "minimum_final_accuracy"),
        ("selection_accuracy", ">=", "minimum_selection_accuracy"),
        ("protocol_violation_count", "<=", "maximum_protocol_violation_count"),
        ("prohibited_tool_call_count", "<=", "maximum_prohibited_tool_call_count"),
        (
            "out_of_candidate_selection_count",
            "<=",
            "maximum_out_of_candidate_selection_count",
        ),
    ]
    checks = []
    for metric, operator, gate_name in definitions:
        actual = metrics[metric]
        threshold = gates[gate_name]
        passed = actual is not None and (
            actual >= threshold if operator == ">=" else actual <= threshold
        )
        checks.append(
            {
                "metric": metric,
                "actual": actual,
                "operator": operator,
                "threshold": threshold,
                "passed": passed,
            }
        )
    return {"passed": all(item["passed"] for item in checks), "checks": checks}


def _comparison(client_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(client_results) != 2:
        return None
    left, right = client_results
    left_cases = {item["case_id"]: item for item in left["case_results"]}
    right_cases = {item["case_id"]: item for item in right["case_results"]}
    agreements = 0
    correctness_divergences = []
    for case_id, left_item in left_cases.items():
        right_item = right_cases[case_id]
        same = (
            left_item["decision"] == right_item["decision"]
            and left_item["selected_interface"] == right_item["selected_interface"]
        )
        agreements += int(same)
        if left_item["final_correct"] != right_item["final_correct"]:
            correctness_divergences.append(case_id)
    count = len(left_cases)
    return {
        "clients": [left["client"], right["client"]],
        "exact_decision_agreement_count": agreements,
        "exact_decision_agreement_rate": round(agreements / count, 4),
        "correctness_divergence_count": len(correctness_divergences),
        "correctness_divergence_case_ids": correctness_divergences,
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = ["# Context Router 双客户端验收报告", ""]
    for result in payload["clients"]:
        metrics = result["metrics"]
        gate = result["quality_gate"]
        selection_accuracy = metrics["selection_accuracy"]
        lines.extend(
            [
                f"## {result['client']}",
                "",
                f"- 验收：{'通过' if gate['passed'] else '未通过'}",
                f"- MCP成功率：{metrics['mcp_success_rate']:.2%}",
                f"- Top15召回率：{metrics['candidate_recall_at_k']:.2%}",
                f"- 最终正确率：{metrics['final_accuracy']:.2%}",
                "- 已选择接口准确率："
                + (f"{selection_accuracy:.2%}" if selection_accuracy is not None else "无"),
                f"- 禁止工具调用：{metrics['prohibited_tool_call_count']}",
                "",
            ]
        )
    comparison = payload.get("comparison")
    if comparison:
        lines.extend(
            [
                "## 客户端对比",
                "",
                f"- 完全一致率：{comparison['exact_decision_agreement_rate']:.2%}",
                f"- 正确性分歧题数：{comparison['correctness_divergence_count']}",
                "",
            ]
        )
    lines.extend([f"总体结论：{'通过' if payload['passed'] else '未通过'}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="评分 Context Router 双客户端接口检索验收")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument(
        "--result",
        action="append",
        required=True,
        help="CLIENT=/absolute/path/to/result.json，可重复传入",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--gates",
        type=Path,
        default=Path(__file__).parents[1]
        / "evaluations"
        / "client-acceptance-v1"
        / "quality-gates.json",
    )
    arguments = parser.parse_args()
    gold = _load_object(arguments.gold)
    gates = _load_object(arguments.gates)
    results = []
    for value in arguments.result:
        client, separator, raw_path = value.partition("=")
        if not separator or not client or not raw_path:
            raise ValueError("--result 必须使用 CLIENT=/absolute/path.json 格式")
        result = score_client(gold, _load_object(Path(raw_path)))
        if result["client"] != client:
            raise ValueError(f"结果 client={result['client']!r} 与参数 {client!r} 不一致")
        result["quality_gate"] = _gate(result, gates)
        results.append(result)
    payload = {
        "schema_version": "context-router-client-acceptance-score-v1",
        "suite_id": gold.get("suite_id"),
        "passed": all(result["quality_gate"]["passed"] for result in results),
        "clients": results,
        "comparison": _comparison(results),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    arguments.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps({"output": str(arguments.output), "passed": payload["passed"]}))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
