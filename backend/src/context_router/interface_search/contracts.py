from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from context_router.interface_search.domain import SchemaFieldPath

CONTRACT_HASH_VERSION = "v2"
IGNORED_SCHEMA_KEYS = {
    "description",
    "title",
    "example",
    "examples",
    "deprecated",
    "externalDocs",
}


def _normalize_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_schema(item)
            for key, item in sorted(value.items())
            if key not in IGNORED_SCHEMA_KEYS
        }
    if isinstance(value, list):
        return [_normalize_schema(item) for item in value]
    return value


def calculate_contract_hash(endpoint: Any) -> str:
    payload = {
        "method": endpoint.method,
        "path": endpoint.path,
        "operation_id": endpoint.operation_id,
        "request_schema": _normalize_schema(endpoint.request_schema),
        "response_schema": _normalize_schema(endpoint.response_schema),
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def extract_schema_paths(
    schema: dict[str, Any], *, max_depth: int = 3, max_fields: int = 24
) -> list[str]:
    fields = extract_schema_field_paths(
        schema,
        default_location="unknown",
        max_depth=max_depth,
        max_fields=max_fields,
    )
    return [f"{item.path}:{item.data_type}" if item.data_type else item.path for item in fields]


def extract_schema_field_paths(
    schema: dict[str, Any],
    *,
    default_location: str,
    max_depth: int = 5,
    max_fields: int = 120,
) -> list[SchemaFieldPath]:
    """Extract stable searchable field paths from OpenAPI-like and plain JSON schemas."""

    paths: list[SchemaFieldPath] = []
    seen: set[tuple[str, str]] = set()

    def add(
        path: str,
        node: Any,
        *,
        location: str,
        required: bool,
        description: str = "",
    ) -> None:
        if not path or len(paths) >= max_fields:
            return
        normalized_location = (
            location
            if location
            in {
                "path",
                "query",
                "header",
                "body",
                "response",
            }
            else "unknown"
        )
        key = (path, normalized_location)
        if key in seen:
            return
        seen.add(key)
        node = node if isinstance(node, dict) else {}
        field_name = path.removesuffix("[]").rsplit(".", 1)[-1]
        meaning = str(description or node.get("description") or node.get("title") or "")
        paths.append(
            SchemaFieldPath(
                path=path,
                normalized_name=_snake_case(field_name),
                meaning=" ".join(meaning.split())[:500],
                data_type=str(node.get("type") or _ref_name(node.get("$ref")) or "")[:120],
                required=required,
                location=normalized_location,
                source="exact_contract",
                confidence=0.98 if normalized_location in {"path", "query", "header"} else 0.92,
            )
        )

    def walk(
        node: Any,
        prefix: str,
        depth: int,
        *,
        location: str,
        inherited_required: bool = False,
    ) -> None:
        if len(paths) >= max_fields or depth > max_depth or not isinstance(node, dict):
            return

        parameters = node.get("parameters")
        if isinstance(parameters, list):
            for parameter in parameters:
                if not isinstance(parameter, dict):
                    continue
                name = str(parameter.get("name") or "").strip()
                parameter_schema = parameter.get("schema")
                add(
                    name,
                    parameter_schema,
                    location=str(parameter.get("in") or "unknown"),
                    required=bool(parameter.get("required")),
                    description=str(parameter.get("description") or ""),
                )
                walk(
                    parameter_schema,
                    name,
                    depth + 1,
                    location=str(parameter.get("in") or "unknown"),
                    inherited_required=bool(parameter.get("required")),
                )

        request_body = node.get("requestBody")
        if isinstance(request_body, dict):
            walk(
                request_body,
                prefix,
                depth + 1,
                location="body",
                inherited_required=bool(request_body.get("required")),
            )

        content = node.get("content")
        if isinstance(content, dict):
            for media in content.values():
                if isinstance(media, dict):
                    walk(
                        media.get("schema", media),
                        prefix,
                        depth + 1,
                        location=location,
                        inherited_required=inherited_required,
                    )

        wrapped_schema = node.get("schema")
        if isinstance(wrapped_schema, dict):
            walk(
                wrapped_schema,
                prefix,
                depth + 1,
                location=location,
                inherited_required=inherited_required,
            )

        required_names = set(node.get("required") or [])
        properties = node.get("properties")
        if isinstance(properties, dict):
            for name, child in properties.items():
                path = f"{prefix}.{name}" if prefix else name
                add(
                    path,
                    child,
                    location=location,
                    required=inherited_required or name in required_names,
                )
                walk(
                    child,
                    path,
                    depth + 1,
                    location=location,
                    inherited_required=name in required_names,
                )

        items = node.get("items")
        if isinstance(items, dict):
            array_prefix = f"{prefix}[]" if prefix else "[]"
            walk(
                items,
                array_prefix,
                depth + 1,
                location=location,
                inherited_required=inherited_required,
            )

        for branch in ("allOf", "oneOf", "anyOf"):
            variants = node.get(branch)
            if isinstance(variants, list):
                for variant in variants:
                    walk(
                        variant,
                        prefix,
                        depth + 1,
                        location=location,
                        inherited_required=inherited_required,
                    )

        if location == "response" and not any(
            key in node for key in ("content", "schema", "properties", "items", "allOf")
        ):
            for key, value in node.items():
                if str(key).startswith("2") and isinstance(value, dict):
                    walk(value, prefix, depth + 1, location=location)

    walk(schema, "", 0, location=default_location)
    return paths


def _snake_case(value: str) -> str:
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", value).replace("-", "_")
    return re.sub(r"_+", "_", normalized).strip("_").lower()


def _ref_name(value: Any) -> str:
    return str(value).rsplit("/", 1)[-1] if value else ""
