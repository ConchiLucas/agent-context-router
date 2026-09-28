"""Conservative display classification of an existing, bounded request log."""

import json
from typing import Any


def request_status(
    *,
    requested: bool,
    operation_kind: str,
    status_code: int | None,
    success: bool | None,
    response_body: str | None,
    truncated: bool = False,
) -> str:
    if not requested:
        return "not_requested"
    if status_code == 404:
        return "not_found"
    if status_code is None or not 200 <= status_code < 300:
        return "error"
    try:
        payload = json.loads(response_body or "")
    except (ValueError, RecursionError):
        if truncated:
            return "error" if success is False else "requested"
        if success is False:
            return "error"
        # A 2xx HTML login page is not evidence of business success.
        return (
            "no_data"
            if status_code == 204 and operation_kind == "read"
            else (
                "succeeded"
                if status_code == 204 and operation_kind in {"write", "destructive"}
                else "requested"
            )
        )
    if isinstance(payload, dict):
        if payload.get("_capture_error") or payload.get("_capture_kind") == "incomplete":
            return "error"
        if payload.get("_truncated") or payload.get("_capture_kind") in {
            "missing",
            "binary",
            "text",
            "truncated",
        }:
            return "requested"
    if truncated:
        return "error" if success is False else "requested"
    if isinstance(payload, dict):
        code = payload.get("code")
        if payload.get("success") is False or (
            code is not None and str(code).lower() not in {"0", "200", "ok", "success"}
        ):
            return "business_error" if status_code == 200 else "error"
    # Stored success alone cannot tell a transport failure from a business rejection.
    if success is False:
        return "error"
    if operation_kind in {"write", "destructive"}:
        return "succeeded"
    if operation_kind != "read":
        return "requested"
    return _data_status(payload)


def _data_status(payload: Any, depth: int = 0) -> str:
    if depth > 8:
        return "requested"
    if payload is None or payload == "":
        return "no_data"
    if isinstance(payload, list):
        return "has_data" if payload else "no_data"
    if isinstance(payload, dict):
        if not payload:
            return "no_data"
        # Prefer actual rows over pagination totals (a later page may be empty).
        for key in ("rows", "records", "items", "list", "content"):
            if isinstance(payload.get(key), list):
                return _data_status(payload[key], depth + 1)
        if "data" in payload:
            return _data_status(payload["data"], depth + 1)
        if any(key in payload for key in ("total", "totalCount", "pageNumber")):
            return "requested"
        # A materialized detail DTO can exist even though no business field was populated.
        # Its code/success fields may be null business fields, not response metadata.
        # Do not use truthiness: zero and false are valid values.
        if all(value is None for value in payload.values()):
            return "no_data"
        if any(key in payload for key in ("code", "success")):
            # Inside data, code can be a domain code rather than response metadata.
            # Require another populated business field; metadata-only envelopes
            # remain ambiguous. Outer failures were checked before this traversal.
            metadata = {"code", "success", "msg", "message", "timestamp"}
            if depth > 0 and any(
                key not in metadata and value is not None for key, value in payload.items()
            ):
                return "has_data"
            return "requested"
        return "has_data"
    # 0 and false can be meaningful query results, not missing data.
    return "has_data"
