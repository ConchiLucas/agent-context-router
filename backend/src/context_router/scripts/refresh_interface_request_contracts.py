from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from context_router.config import Settings

_MAPPING = re.compile(r"@(Get|Post|Put|Patch|Delete|Request)Mapping\s*\(", re.MULTILINE)
_CLASS = re.compile(r"\bclass\s+(\w+Controller)\b")
_PATH_VALUE = re.compile(r'["\']([^"\']*)["\']')
_PATH_VARIABLE = re.compile(r"@PathVariable(?:\s*\((.*?)\))?", re.DOTALL)
_REQUEST_PARAM = re.compile(r"@RequestParam(?:\s*\((.*?)\))?", re.DOTALL)
_PARAMETER_DESCRIPTION = re.compile(
    r'@Parameter\s*\([^)]*description\s*=\s*["\']([^"\']+)', re.DOTALL
)
_QUOTED_NAME = re.compile(r'(?:value|name)?\s*=*\s*["\']([^"\']+)["\']')
_PATH_TEMPLATE = re.compile(r"\{([^{}:]+)(?::[^{}]+)?\}")
_HTTP_BY_MAPPING = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Patch": "PATCH",
    "Delete": "DELETE",
}


def _balanced(text: str, opening: int) -> tuple[str, int]:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index], index + 1
    return "", opening


def _mapping_path(arguments: str) -> str:
    match = _PATH_VALUE.search(arguments)
    return match.group(1) if match else ""


def _join_path(base: str, child: str) -> str:
    parts = [part.strip("/") for part in (base, child) if part.strip("/")]
    return "/" + "/".join(parts) if parts else "/"


def _split_parameters(signature: str) -> list[str]:
    result: list[str] = []
    start = 0
    parentheses = 0
    angles = 0
    for index, char in enumerate(signature):
        if char == "(":
            parentheses += 1
        elif char == ")":
            parentheses = max(0, parentheses - 1)
        elif char == "<":
            angles += 1
        elif char == ">":
            angles = max(0, angles - 1)
        elif char == "," and parentheses == 0 and angles == 0:
            result.append(signature[start:index].strip())
            start = index + 1
    tail = signature[start:].strip()
    if tail:
        result.append(tail)
    return result


def _java_name(segment: str, annotation_arguments: str | None) -> str:
    if annotation_arguments:
        explicit = _QUOTED_NAME.search(annotation_arguments)
        if explicit:
            return explicit.group(1)
    cleaned = re.sub(r"@\w+(?:\s*\([^)]*\))?", " ", segment, flags=re.DOTALL)
    tokens = re.findall(r"[A-Za-z_$][\w$]*", cleaned)
    return tokens[-1] if tokens else ""


def _java_schema(segment: str) -> dict[str, Any]:
    lowered = segment.lower()
    if "..." in segment or "[]" in segment or re.search(r"\b(list|set|collection)\s*<", lowered):
        return {"type": "array", "items": {"type": "string"}}
    if re.search(r"\b(long|integer|int|short|byte|biginteger)\b", lowered):
        return {"type": "integer"}
    if re.search(r"\b(double|float|bigdecimal)\b", lowered):
        return {"type": "number"}
    if re.search(r"\b(boolean|bool)\b", lowered):
        return {"type": "boolean"}
    return {"type": "string"}


def _parameter_contract(signature: str) -> dict[str, list[dict[str, Any]]]:
    contract: dict[str, list[dict[str, Any]]] = {"path": [], "query": []}
    for segment in _split_parameters(signature):
        location = ""
        annotation: re.Match[str] | None = _PATH_VARIABLE.search(segment)
        if annotation:
            location = "path"
        else:
            annotation = _REQUEST_PARAM.search(segment)
            if annotation:
                location = "query"
        if not location or annotation is None:
            continue
        arguments = annotation.group(1)
        name = _java_name(segment, arguments)
        if not name:
            continue
        required = location == "path" or not (
            arguments and re.search(r"required\s*=\s*false", arguments, re.IGNORECASE)
        )
        schema = _java_schema(segment)
        description = _PARAMETER_DESCRIPTION.search(segment)
        if description:
            schema["description"] = description.group(1)
        default = re.search(r'defaultValue\s*=\s*["\']([^"\']*)', arguments or "")
        if default:
            schema["default"] = default.group(1)
            required = False
        contract[location].append({"name": name, "required": required, "schema": schema})
    return contract


def parse_controller(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    class_match = _CLASS.search(text)
    if not class_match:
        return []
    class_name = class_match.group(1)
    class_prefix = text[: class_match.start()]
    class_mapping = list(_MAPPING.finditer(class_prefix))
    base_path = ""
    if class_mapping:
        opening = class_mapping[-1].end() - 1
        arguments, _ = _balanced(text, opening)
        base_path = _mapping_path(arguments)

    endpoints: list[dict[str, Any]] = []
    for mapping in _MAPPING.finditer(text, class_match.end()):
        arguments, mapping_end = _balanced(text, mapping.end() - 1)
        public = re.search(r"\bpublic\s+[\s\S]{0,800}?\b(\w+)\s*\(", text[mapping_end:])
        if not public:
            continue
        method_opening = mapping_end + public.end() - 1
        signature, signature_end = _balanced(text, method_opening)
        if not signature_end:
            continue
        mapping_kind = mapping.group(1)
        http_method = _HTTP_BY_MAPPING.get(mapping_kind)
        if http_method is None:
            method_match = re.search(r"RequestMethod\.(GET|POST|PUT|PATCH|DELETE)", arguments)
            http_method = method_match.group(1) if method_match else ""
        if not http_method:
            continue
        endpoints.append(
            {
                "controller": class_name,
                "method": http_method,
                "path": _join_path(base_path, _mapping_path(arguments)),
                "method_name": public.group(1),
                "parameters": _parameter_contract(signature),
            }
        )
    return endpoints


def _object_schema(parameters: list[dict[str, Any]]) -> dict[str, Any]:
    properties = {item["name"]: item["schema"] for item in parameters}
    required = [item["name"] for item in parameters if item["required"]]
    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required
    return result


def _path_contract(path: str, source: dict[str, Any] | None) -> dict[str, Any]:
    source_parameters = {
        item["name"]: item for item in (source or {}).get("parameters", {}).get("path", [])
    }
    parameters: list[dict[str, Any]] = []
    for name in _PATH_TEMPLATE.findall(path):
        parameters.append(
            source_parameters.get(
                name,
                {"name": name, "required": True, "schema": {"type": "string"}},
            )
        )
    return _object_schema(parameters)


def refresh(
    *, database_url: str, workspace_id: str, service_roots: dict[str, Path]
) -> dict[str, Any]:
    source_by_controller: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = {}
    parsed_files = 0
    for service, root in service_roots.items():
        index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for controller in root.rglob("*Controller.java"):
            parsed_files += 1
            for endpoint in parse_controller(controller):
                index[(endpoint["controller"], endpoint["method"])].append(endpoint)
        source_by_controller[service] = index

    updated = 0
    source_matched = 0
    query_fields = 0
    path_fields = 0
    by_service: dict[str, int] = defaultdict(int)
    with (
        psycopg.connect(database_url, row_factory=dict_row) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """SELECT interface.id, interface.path, interface.method,
                      interface.controller_name, interface.request_contract,
                      interface.request_schema, service.name AS service_name
               FROM interface_forwarding_interfaces AS interface
               JOIN interface_forwarding_services AS service ON service.id=interface.service_id
               WHERE interface.workspace_id=%s AND service.name=ANY(%s)""",
            (workspace_id, list(service_roots)),
        )
        for row in cursor.fetchall():
            candidates = source_by_controller.get(row["service_name"], {}).get(
                (row["controller_name"], row["method"]), []
            )
            exact = [item for item in candidates if item["path"] == row["path"]]
            if len(exact) != 1:
                suffix = [
                    item
                    for item in candidates
                    if row["path"].endswith(item["path"]) or item["path"].endswith(row["path"])
                ]
                exact = suffix if len(suffix) == 1 else []
            source = exact[0] if exact else None
            if source:
                source_matched += 1
            contract = dict(row["request_contract"] or {})
            contract["path"] = _path_contract(row["path"], source)
            contract["query"] = _object_schema(
                (source or {}).get("parameters", {}).get("query", [])
            )
            contract.setdefault("header", {"type": "object", "properties": {}})
            contract["body"] = row["request_schema"] or contract.get("body") or {}
            path_fields += len(contract["path"].get("properties", {}))
            query_fields += len(contract["query"].get("properties", {}))
            cursor.execute(
                """UPDATE interface_forwarding_interfaces
                   SET request_contract=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                (Jsonb(contract), row["id"]),
            )
            updated += 1
            by_service[row["service_name"]] += 1
    return {
        "workspace_id": workspace_id,
        "parsed_controller_files": parsed_files,
        "updated_interfaces": updated,
        "source_matched_interfaces": source_matched,
        "path_fields": path_fields,
        "query_fields": query_fields,
        "services": dict(sorted(by_service.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh forwarding contracts from Java Controllers"
    )
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument(
        "--service-root",
        action="append",
        default=[],
        metavar="SERVICE=PATH",
        help=(
            "Optional explicit service root. Repeat for multiple services; "
            "otherwise every direct child directory of --backend-root is discovered."
        ),
    )
    args = parser.parse_args()
    database_url = Settings().database_url
    if not database_url:
        raise SystemExit("CONTEXT_ROUTER_DATABASE_URL is required")
    roots: dict[str, Path] = {}
    for value in args.service_root:
        service, separator, raw_path = value.partition("=")
        if not separator or not service.strip() or not raw_path.strip():
            raise SystemExit("--service-root must use SERVICE=PATH")
        roots[service.strip()] = Path(raw_path).expanduser().resolve()
    if not roots:
        roots = {
            path.name: path
            for path in sorted(args.backend_root.iterdir())
            if path.is_dir() and not path.name.startswith(".")
        }
    if not roots:
        raise SystemExit("no service roots were discovered")
    missing = [str(path) for path in roots.values() if not path.is_dir()]
    if missing:
        raise SystemExit(f"service roots do not exist: {', '.join(missing)}")
    print(
        json.dumps(
            refresh(
                database_url=database_url,
                workspace_id=args.workspace_id,
                service_roots=roots,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
