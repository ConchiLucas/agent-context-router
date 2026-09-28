#!/usr/bin/env python3
"""Validate locally saved AI result files without reading response bodies."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CLIENTS = {"cursor", "grok-heavy", "antigravity"}
CLASSIFICATIONS = {
    "non_empty_success",
    "valid_empty",
    "parameter_invalid",
    "auth_failed",
    "server_error",
    "timeout",
    "skipped_safety",
    "blocked",
}
FORBIDDEN_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "request_header",
    "request_headers",
    "response_body",
    "session",
    "token",
}


def forbidden_paths(value: object, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key.lower() in FORBIDDEN_KEYS:
                found.append(child)
            found.extend(forbidden_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(forbidden_paths(item, f"{path}[{index}]"))
    return found


def validate(path: Path) -> tuple[list[str], Counter[str]]:
    errors: list[str] = []
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return ["结果文件超过 2 MiB，拒绝加载"], Counter()
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"JSON 无法读取：{exc}"], Counter()
    schema = json.loads((ROOT / "schemas/result.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    for failure in Draft202012Validator(schema).iter_errors(result):
        location = ".".join(map(str, failure.absolute_path)) or "$"
        # Never echo arbitrary values from a malformed or potentially sensitive result.
        errors.append(f"Schema {location}: 不符合 {failure.validator} 约束")
    if errors:
        return errors, Counter()
    batch_id = path.parents[1].name
    input_path = path.parents[1] / "input.json"
    source = json.loads(input_path.read_text(encoding="utf-8"))
    expected = {item["case_id"]: item for item in source["cases"] if isinstance(item, dict)}
    if result.get("schema_version") != "context-router-mtp-query-result-v1":
        errors.append("schema_version 错误")
    if result.get("campaign_id") != "panzhihua-mtp-test-query-2026-09":
        errors.append("campaign_id 错误")
    if result.get("batch_id") != batch_id:
        errors.append("batch_id 与目录不一致")
    if result.get("client") not in CLIENTS:
        errors.append("client 不受支持")
    if path.stem != result.get("client"):
        errors.append("client 与文件名不一致")
    if result.get("environment") != "test":
        errors.append("environment 必须是 test")
    cases = result.get("cases")
    if not isinstance(cases, list):
        return errors + ["cases 必须是数组"], Counter()
    if result.get("case_count") != len(cases) or len(cases) != len(expected):
        errors.append("case_count 或 case 数量与输入不一致")
    seen: set[str] = set()
    classes: Counter[str] = Counter()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"cases[{index}] 不是对象")
            continue
        case_id = case.get("case_id")
        if case_id in seen:
            errors.append(f"case_id 重复：{case_id}")
        seen.add(case_id)
        original = expected.get(case_id)
        if original is None:
            errors.append(f"输入中不存在：{case_id}")
            continue
        for key in ("interface_id", "method", "path"):
            if case.get(key) != original.get(key):
                errors.append(f"{case_id} 的 {key} 与输入不一致")
        classification = case.get("classification")
        if classification not in CLASSIFICATIONS:
            errors.append(f"{case_id} classification 无效")
        else:
            classes[classification] += 1
        attempts = case.get("attempt_count")
        if not isinstance(attempts, int) or not 0 <= attempts <= 2:
            errors.append(f"{case_id} attempt_count 必须为 0..2")
    missing = set(expected) - seen
    if missing:
        errors.append(f"缺少 case：{', '.join(sorted(missing))}")
    leaked = forbidden_paths(result)
    if leaked:
        errors.append("存在禁止保存的字段：" + ", ".join(leaked))
    if path.stat().st_size > 2 * 1024 * 1024:
        errors.append("结果文件超过 2 MiB，疑似保存了大响应")
    return errors, classes


def main() -> int:
    paths = (
        [Path(arg).resolve() for arg in sys.argv[1:]]
        if len(sys.argv) > 1
        else sorted(ROOT.glob("batches/batch-*/results/*.json"))
    )
    if not paths:
        print("尚无结果文件")
        return 0
    failed = 0
    total = Counter()
    for path in paths:
        errors, classes = validate(path)
        total.update(classes)
        relative = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        if errors:
            failed += 1
            print(f"FAIL {relative}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"PASS {relative} {dict(classes)}")
    print(f"files={len(paths)} failed={failed} classifications={dict(total)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
