from __future__ import annotations

import re
from typing import Any

from context_router.interface_search.contracts import extract_schema_field_paths
from context_router.interface_search.domain import (
    BusinessIdentifier,
    RequiredInput,
    SchemaFieldPath,
)
from context_router.interface_search.workspaces import WorkspaceProfile


def infer_resource(
    text: str,
    domains: list[str] | None = None,
    profile: WorkspaceProfile | None = None,
) -> str:
    if profile:
        matches = profile.match(text, "resource")
        if domains:
            domain_set = set(domains)
            compatible = [
                value
                for value in matches
                if not (
                    term_domains := set(
                        (profile.term("resource", value) or _EMPTY_TERM).metadata.get("domains", [])
                    )
                )
                or bool(domain_set & term_domains)
            ]
            matches = compatible
        if matches:
            return matches[0]
    class_match = re.search(r"([A-Za-z_$][\w$]*Controller)(?:\.|\b)", text)
    if class_match:
        name = class_match.group(1).removesuffix("Controller")
        name = re.sub(r"(?:Admin|Portal|Internal|External)$", "", name)
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower().strip("_")
        if snake:
            return snake
    return ""


def infer_lookup_keys(text: str, profile: WorkspaceProfile | None = None) -> list[str]:
    lowered = text.lower().replace("_", "").replace("-", "")
    keys = profile.match(text, "lookup_key") if profile else []
    if (re.search(r"(?:\{|\b)(?:id)(?:\}|\b)", lowered) or "主键" in lowered) and not any(
        item.endswith("ID") for item in keys
    ):
        keys.append("ID")
    technical_names = re.findall(r"(?<![./])\b[a-z][A-Za-z0-9]*(?:Id|No|Code)\b", text)
    keys.extend(technical_names)
    return list(dict.fromkeys(keys))[:30]


def infer_cardinality(text: str, actions: list[str]) -> str:
    lowered = text.lower().replace("_", "").replace("-", "")
    if "page" in actions:
        return "many"
    if "list" in actions:
        return "many"
    if "detail" in actions:
        return "one"
    if any(term in lowered for term in ("汇总", "合计", "统计", "概览", "指标卡", "卡片")):
        return "one"
    if "批量" in lowered:
        return "many"
    if any(
        term in lowered
        for term in (
            "集合",
            "多个",
            "多条",
            "若干条",
            "几条",
            "几张",
            "几份",
            "一批",
            "数组",
            "一组",
        )
    ):
        return "many"
    if re.search(
        r"(?:[二两三四五六七八九十百]+|[2-9]|[1-9]\d+)(?:条|张|份|个)",
        lowered,
    ):
        return "many"
    if any(term in lowered for term in ("分页", "/page", "page(")):
        return "many"
    if any(term in lowered for term in ("列表", "清单", "/list", "list(")):
        return "many"
    if any(term in lowered for term in ("详情", "getbyid", "getinfo", "findone", "{id}")):
        return "one"
    if any(term in lowered for term in ("单条", "一条", "指定一条", "某一条")):
        return "one"
    return "unknown"


def infer_ownership(text: str) -> str:
    lowered = text.lower().replace("_", "").replace("-", "")
    if any(term in lowered for term in ("当前登录用户", "当前用户", "本人", "我的", "currentuser")):
        return "self"
    if any(term in lowered for term in ("byid", "按id", "根据id", "{id}")):
        return "by_id"
    if any(term in lowered for term in ("admin", "all", "全部", "全量")):
        return "all"
    return "unknown"


def infer_required_inputs(
    request_schema: dict[str, Any], profile: WorkspaceProfile | None = None
) -> list[RequiredInput]:
    inputs: list[RequiredInput] = []
    properties = request_schema.get("properties")
    required = set(request_schema.get("required") or [])
    if isinstance(properties, dict):
        for name, schema in properties.items():
            inputs.append(
                RequiredInput(
                    name=name,
                    zh_name=_input_label(name, profile),
                    location="body",
                    required=name in required,
                    schema_type=(schema.get("type", "") if isinstance(schema, dict) else ""),
                )
            )
    signature = request_schema.get("java_signature")
    if isinstance(signature, str):
        for raw_parameter in _split_parameters(signature):
            names = re.findall(r"\b([a-z_$][\w$]*)\s*$", raw_parameter)
            if not names:
                continue
            name = names[-1]
            location = "body"
            if "@PathVariable" in raw_parameter:
                location = "path"
            elif "@RequestParam" in raw_parameter:
                location = "query"
            inputs.append(
                RequiredInput(
                    name=name,
                    zh_name=_input_label(name, profile),
                    location=location,
                    required="required = false" not in raw_parameter,
                    schema_type="java",
                )
            )
    for field in extract_schema_field_paths(request_schema, default_location="body"):
        if field.location not in {"path", "query", "header", "body"}:
            continue
        if not field.required and field.location == "body":
            continue
        inputs.append(
            RequiredInput(
                name=field.path,
                zh_name=field.meaning or _input_label(field.path.rsplit(".", 1)[-1], profile),
                location=field.location,
                required=field.required,
                schema_type=field.data_type,
            )
        )
    unique = {item.name: item for item in inputs}
    return list(unique.values())[:50]


def infer_business_identifiers(
    *,
    resource: str,
    request_fields: list[SchemaFieldPath],
    response_fields: list[SchemaFieldPath],
    required_inputs: list[RequiredInput],
) -> list[BusinessIdentifier]:
    candidates: list[tuple[str, str, str, str, float]] = []
    for item in required_inputs:
        name = item.name.rsplit(".", 1)[-1]
        if (_is_identifier_name(name) or item.location == "path") and (
            item.required or item.location in {"path", "query", "header"}
        ):
            candidates.append(
                (
                    name,
                    item.zh_name or _identifier_label(name, resource),
                    item.location,
                    "required_input",
                    0.97,
                )
            )
    for field in request_fields:
        name = field.path.removesuffix("[]").rsplit(".", 1)[-1]
        if _is_identifier_name(name) and (
            field.required or field.location in {"path", "query", "header"}
        ):
            candidates.append(
                (
                    name,
                    field.meaning or _identifier_label(name, resource),
                    field.location,
                    "request_schema",
                    max(0.9, field.confidence),
                )
            )
    for field in response_fields:
        name = field.path.removesuffix("[]").rsplit(".", 1)[-1]
        if _is_identifier_name(name):
            candidates.append(
                (
                    name,
                    field.meaning or _identifier_label(name, resource),
                    "response",
                    "response_schema",
                    min(0.78, field.confidence),
                )
            )

    merged: dict[str, BusinessIdentifier] = {}
    for name, display_name, _location, source, confidence in candidates:
        normalized = _snake_case(name)
        canonical = f"{resource}:{normalized}" if resource else normalized
        existing = merged.get(canonical)
        technical_names = list(
            dict.fromkeys([*(existing.technical_names if existing else []), name, normalized])
        )
        aliases = list(
            dict.fromkeys(
                [
                    *(existing.aliases if existing else []),
                    display_name,
                    _input_label(name),
                ]
            )
        )
        merged[canonical] = BusinessIdentifier(
            canonical=canonical,
            display_name=display_name,
            technical_names=technical_names[:20],
            aliases=[item for item in aliases if item][:30],
            resource=resource,
            source=source
            if existing is None or confidence >= existing.confidence
            else existing.source,
            confidence=max(confidence, existing.confidence if existing else 0),
        )
    return list(merged.values())[:50]


def lookup_keys_from_identifiers(
    identifiers: list[BusinessIdentifier], *, include_response: bool = False
) -> list[str]:
    values: list[str] = []
    for item in identifiers:
        if item.source == "response_schema" and not include_response:
            continue
        values.extend([item.canonical, item.display_name, *item.technical_names, *item.aliases])
    return list(dict.fromkeys(value for value in values if value))[:30]


def build_discriminators(
    *,
    audiences: list[str],
    actions: list[str],
    lookup_keys: list[str],
    cardinality: str,
    ownership: str,
) -> list[str]:
    values: list[str] = []
    values.extend(f"属于{item}" for item in audiences)
    values.extend(f"执行{item}动作" for item in actions if item != "query")
    values.extend(f"根据{item}定位" for item in lookup_keys if not re.search(r"[a-z]", item, re.I))
    if cardinality == "one":
        values.append("返回单条结果")
    elif cardinality == "many":
        values.append("返回多条结果")
    if ownership == "self":
        values.append("仅处理当前主体数据")
    elif ownership == "all":
        values.append("处理全量范围数据")
    return list(dict.fromkeys(values))[:30]


def _split_parameters(signature: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for character in signature:
        if character in "<([":
            depth += 1
        elif character in ">)]":
            depth = max(0, depth - 1)
        if character == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if current:
        parts.append("".join(current).strip())
    return parts


def _input_label(name: str, profile: WorkspaceProfile | None = None) -> str:
    if profile:
        matches = profile.match(name, "lookup_key")
        if matches:
            return matches[0]
    return name


def _is_identifier_name(name: str) -> bool:
    compact = name.lower().replace("_", "").replace("-", "")
    return bool(re.search(r"(?:id|no|code|number|key|uuid)$", compact))


def _identifier_label(name: str, resource: str) -> str:
    direct = _input_label(name)
    if direct != name:
        return direct
    suffix = "ID" if name.lower().replace("_", "").endswith("id") else "编号"
    return f"{resource}{suffix}" if resource else name


class _EmptyTerm:
    metadata: dict[str, Any] = {}


_EMPTY_TERM = _EmptyTerm()


def _snake_case(value: str) -> str:
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", value).replace("-", "_")
    return re.sub(r"_+", "_", normalized).strip("_").lower()
