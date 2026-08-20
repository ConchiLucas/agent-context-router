"""在指定 Java 模块上跑关联基数分析，输出可人工校准的报告。

索引范围要大于分析范围，否则跨模块引用的实体解析不出来：

    MTP=/workspace/company_workforce/panzhihua_dev_workforce/backend/c12-mtp
    docker compose exec backend uv run --extra dev python \\
        -m context_router.scripts.analyze_java_relations \\
        --index-root $MTP \\
        --analyze-root $MTP/c12-mtp-shipping-service
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from context_router.scripts.java_relation_analyzer import (
    Verdict,
    analyze,
    build_index,
    build_verdicts,
)

__all__ = ["main", "render", "to_json"]

# 标注方向统一为「子表侧 : 父表侧」。N : 1 从父表方向读就是 1 : N，是同一条边的两个视角，
# 所以判定阶段只需要区分外键唯一与不唯一两种情况。
CARDINALITY_LABEL = {
    "one_to_one": "1 : 1",
    "many_to_one": "N : 1",
    "unknown": "未定",
}
CONFIDENCE_LABEL = {
    "confirmed": "已确认",
    "runtime": "运行时验证",
    "upper_bound": "仅上界",
    "intent": "仅意图",
    "low": "待人工",
    "none": "无证据",
}
LOOP_SHAPE_LABEL = {
    "single": "单次写入",
    "per_parent_iteration": "循环父集合，每轮建一个子",
    "writes_loop_collection": "写入被遍历的集合",
    "unknown_loop": "循环内但形态不明",
}


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return path.name


def render(verdicts: list[Verdict], analyze_root: Path, verbose: bool) -> str:
    lines: list[str] = []
    counter = Counter((item.cardinality, item.confidence) for item in verdicts)
    tables = sorted({item.table for item in verdicts})

    lines.append("=" * 96)
    lines.append(f"分析范围 {analyze_root}")
    lines.append(f"覆盖 {len(tables)} 张表，{len(verdicts)} 个外键列")
    lines.append("=" * 96)
    lines.append("")
    lines.append("判定分布：")
    for (cardinality, confidence), count in sorted(counter.items(), key=lambda kv: -kv[1]):
        label = CARDINALITY_LABEL.get(cardinality, cardinality)
        conf = CONFIDENCE_LABEL.get(confidence, confidence)
        lines.append(f"  {label:<6} {conf:<6} {count:>4}")
    lines.append("")

    current_table = ""
    for item in verdicts:
        if item.table != current_table:
            current_table = item.table
            lines.append("")
            lines.append("-" * 96)
            lines.append(f"表 {current_table}")
            lines.append("-" * 96)
        label = CARDINALITY_LABEL.get(item.cardinality, item.cardinality)
        conf = CONFIDENCE_LABEL.get(item.confidence, item.confidence)
        target = " | ".join(item.target_tables) if item.target_tables else "目标表未解析"
        lines.append("")
        lines.append(f"  {item.column}  ->  {target}")
        lines.append(f"    判定 {label}  置信 {conf}")
        for reason in item.reasons:
            lines.append(f"    · {reason}")
        if verbose and item.write_sites:
            lines.append(f"    写入入口 {len(item.write_sites)} 处：")
            for site in item.write_sites:
                flag = "批量" if site.is_batch else "单体"
                shape = LOOP_SHAPE_LABEL.get(site.loop_shape, site.loop_shape)
                lines.append(
                    f"      {_relative(site.path, analyze_root)}:{site.line} "
                    f"{site.receiver}.{site.method}({site.argument}) [{flag} / {shape}]"
                )
        if verbose and item.evidence:
            lines.append(f"    基数证据 {len(item.evidence)} 条：")
            for evidence in item.evidence:
                lines.append(
                    f"      {evidence.kind:<15} "
                    f"{_relative(evidence.path, analyze_root)}:{evidence.line} {evidence.detail}"
                )
    return "\n".join(lines)


def to_json(verdicts: list[Verdict]) -> list[dict[str, object]]:
    return [
        {
            "table": item.table,
            "column": item.column,
            "java_field": item.java_field,
            "target_tables": item.target_tables,
            "cardinality": item.cardinality,
            "confidence": item.confidence,
            "reasons": item.reasons,
            "write_sites": [
                {
                    "path": str(site.path),
                    "line": site.line,
                    "method": site.method,
                    "receiver": site.receiver,
                    "argument": site.argument,
                    "is_batch": site.is_batch,
                    "loop_shape": site.loop_shape,
                    "enclosing_method": site.enclosing_method,
                }
                for site in item.write_sites
            ],
            "evidence": [
                {
                    "kind": evidence.kind,
                    "dto": evidence.dto,
                    "accessor": evidence.accessor,
                    "detail": evidence.detail,
                    "path": str(evidence.path),
                    "line": evidence.line,
                }
                for evidence in item.evidence
            ],
        }
        for item in verdicts
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-root", required=True, type=Path)
    parser.add_argument("--analyze-root", required=True, type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--report-out", type=Path)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--only",
        default="",
        help="只输出表名包含该子串的结果，便于聚焦单表核对",
    )
    args = parser.parse_args()

    index = build_index(args.index_root)
    result = analyze(index, args.analyze_root)
    tables = {site.table for site in result.writes}
    tables |= {
        info.table for info in index.entities.values() if str(args.analyze_root) in str(info.source)
    }
    verdicts = build_verdicts(index, result, tables)
    if args.only:
        verdicts = [item for item in verdicts if args.only in item.table]

    report = render(verdicts, args.analyze_root, args.verbose)
    print(report)
    print("")
    print(
        f"索引：实体 {len(index.entities)} 个 / DAO {len(index.dao_to_entity)} 个 / "
        f"Service {len(index.service_to_entity)} 个"
    )
    print(f"抽取：写入入口 {len(result.writes)} 处 / 基数证据 {len(result.evidence)} 条")

    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(report, encoding="utf-8")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(to_json(verdicts), ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
