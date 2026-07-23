from __future__ import annotations

import base64
import ipaddress
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from .models import (
    DatabaseObject,
    EffectiveQueryPolicy,
    FormattedQueryResult,
    FormattedSearchObjectsResult,
    QueryResult,
    SearchObjectsResult,
    TruncationReason,
)

_JS_SAFE_INTEGER_MAX = (1 << 53) - 1
_RESERVED_QUERY_FIELDS = {
    "columns",
    "rows",
    "returned_rows",
    "truncated",
    "truncation_reason",
    "elapsed_ms",
    "result_bytes",
}
_RESERVED_SEARCH_FIELDS = {
    "objects",
    "returned_count",
    "truncated",
    "truncation_reason",
    "elapsed_ms",
    "result_bytes",
}


class ResultFormattingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_json_value(value: Any, *, _seen: set[int] | None = None) -> Any:
    """Convert database values to deterministic, standards-compliant JSON values."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value if -_JS_SAFE_INTEGER_MAX <= value <= _JS_SAFE_INTEGER_MAX else str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (UUID, ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, Enum):
        return normalize_json_value(value.value, _seen=_seen)

    seen = _seen if _seen is not None else set()
    value_id = id(value)
    if isinstance(value, Mapping):
        if value_id in seen:
            raise ResultFormattingError("query_failed", "cyclic database result value")
        seen.add(value_id)
        try:
            return {str(key): normalize_json_value(item, _seen=seen) for key, item in value.items()}
        finally:
            seen.remove(value_id)
    if isinstance(value, (list, tuple, set, frozenset)):
        if value_id in seen:
            raise ResultFormattingError("query_failed", "cyclic database result value")
        seen.add(value_id)
        try:
            items = value
            if isinstance(value, (set, frozenset)):
                items = sorted(value, key=repr)
            return [normalize_json_value(item, _seen=seen) for item in items]
        finally:
            seen.remove(value_id)

    # Drivers occasionally expose custom scalar wrappers. A string is safer and
    # more portable than leaking a non-serializable Python object into MCP JSON.
    return str(value)


def compact_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


class DatabaseResultFormatter:
    def format_query(
        self,
        result: QueryResult,
        policy: EffectiveQueryPolicy,
        *,
        envelope: Mapping[str, Any] | None = None,
    ) -> FormattedQueryResult:
        normalized_envelope = self._normalize_envelope(envelope, _RESERVED_QUERY_FIELDS)
        columns = tuple(
            {"name": str(column.name), "type": str(column.type)} for column in result.columns
        )
        if result.elapsed_ms < 0:
            raise ResultFormattingError("query_failed", "query elapsed time is invalid")

        self._ensure_metadata_fits(
            self._query_payload(
                columns=columns,
                rows=(),
                truncated=True,
                truncation_reason=TruncationReason.BYTES,
                elapsed_ms=result.elapsed_ms,
            ),
            normalized_envelope,
            policy.max_result_bytes,
        )

        rows: list[tuple[Any, ...]] = []
        truncated = result.truncated
        truncation_reason = result.truncation_reason
        if truncated and truncation_reason is None:
            truncation_reason = TruncationReason.ROWS

        for raw_row in result.rows:
            if len(rows) >= policy.max_rows:
                truncated = True
                truncation_reason = TruncationReason.ROWS
                break
            if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes, bytearray)):
                raise ResultFormattingError("query_failed", "database row has an invalid shape")
            if len(raw_row) != len(columns):
                raise ResultFormattingError(
                    "query_failed",
                    "database row does not match the returned columns",
                )
            normalized_row = tuple(
                self._normalize_cell(item, policy.max_result_bytes) for item in raw_row
            )
            candidate_rows = (*rows, normalized_row)
            candidate_payload = self._query_payload(
                columns=columns,
                rows=candidate_rows,
                truncated=truncated,
                truncation_reason=truncation_reason,
                elapsed_ms=result.elapsed_ms,
            )
            if self._payload_size(candidate_payload, normalized_envelope) > policy.max_result_bytes:
                truncated = True
                truncation_reason = TruncationReason.BYTES
                break
            rows.append(normalized_row)

        payload = self._query_payload(
            columns=columns,
            rows=tuple(rows),
            truncated=truncated,
            truncation_reason=truncation_reason,
            elapsed_ms=result.elapsed_ms,
        )
        while rows and self._payload_size(payload, normalized_envelope) > policy.max_result_bytes:
            rows.pop()
            truncated = True
            truncation_reason = TruncationReason.BYTES
            payload = self._query_payload(
                columns=columns,
                rows=tuple(rows),
                truncated=truncated,
                truncation_reason=truncation_reason,
                elapsed_ms=result.elapsed_ms,
            )

        result_bytes = self._payload_size(payload, normalized_envelope)
        if result_bytes > policy.max_result_bytes:
            raise ResultFormattingError(
                "result_metadata_too_large",
                "query result metadata exceeds the response budget",
            )
        return FormattedQueryResult(
            columns=columns,
            rows=tuple(rows),
            returned_rows=len(rows),
            truncated=truncated,
            truncation_reason=truncation_reason,
            elapsed_ms=result.elapsed_ms,
            result_bytes=result_bytes,
        )

    def format_search(
        self,
        result: SearchObjectsResult,
        *,
        max_objects: int,
        max_result_bytes: int,
        envelope: Mapping[str, Any] | None = None,
    ) -> FormattedSearchObjectsResult:
        if min(max_objects, max_result_bytes) < 1:
            raise ValueError("search result limits must be positive")
        if result.elapsed_ms < 0:
            raise ResultFormattingError("catalog_query_failed", "search elapsed time is invalid")
        normalized_envelope = self._normalize_envelope(envelope, _RESERVED_SEARCH_FIELDS)
        self._ensure_metadata_fits(
            self._search_payload(
                objects=(),
                truncated=True,
                truncation_reason=TruncationReason.BYTES,
                elapsed_ms=result.elapsed_ms,
            ),
            normalized_envelope,
            max_result_bytes,
        )

        objects: list[dict[str, Any]] = []
        truncated = result.truncated
        truncation_reason = result.truncation_reason
        if truncated and truncation_reason is None:
            truncation_reason = TruncationReason.OBJECTS

        for raw_object in result.objects:
            if len(objects) >= max_objects:
                truncated = True
                truncation_reason = TruncationReason.OBJECTS
                break
            source = (
                raw_object.as_mapping() if isinstance(raw_object, DatabaseObject) else raw_object
            )
            if not isinstance(source, Mapping):
                raise ResultFormattingError(
                    "catalog_query_failed",
                    "database object has an invalid shape",
                )
            normalized_object = normalize_json_value(source)
            if len(compact_json_bytes(normalized_object)) > max_result_bytes:
                raise ResultFormattingError(
                    "result_cell_too_large",
                    "one database object exceeds the response budget",
                )
            candidate_objects = (*objects, normalized_object)
            candidate_payload = self._search_payload(
                objects=candidate_objects,
                truncated=truncated,
                truncation_reason=truncation_reason,
                elapsed_ms=result.elapsed_ms,
            )
            if self._payload_size(candidate_payload, normalized_envelope) > max_result_bytes:
                truncated = True
                truncation_reason = TruncationReason.BYTES
                break
            objects.append(normalized_object)

        payload = self._search_payload(
            objects=tuple(objects),
            truncated=truncated,
            truncation_reason=truncation_reason,
            elapsed_ms=result.elapsed_ms,
        )
        while objects and self._payload_size(payload, normalized_envelope) > max_result_bytes:
            objects.pop()
            truncated = True
            truncation_reason = TruncationReason.BYTES
            payload = self._search_payload(
                objects=tuple(objects),
                truncated=truncated,
                truncation_reason=truncation_reason,
                elapsed_ms=result.elapsed_ms,
            )

        result_bytes = self._payload_size(payload, normalized_envelope)
        if result_bytes > max_result_bytes:
            raise ResultFormattingError(
                "result_metadata_too_large",
                "object search metadata exceeds the response budget",
            )
        return FormattedSearchObjectsResult(
            objects=tuple(objects),
            returned_count=len(objects),
            truncated=truncated,
            truncation_reason=truncation_reason,
            elapsed_ms=result.elapsed_ms,
            result_bytes=result_bytes,
        )

    @staticmethod
    def _normalize_cell(value: Any, max_result_bytes: int) -> Any:
        normalized = normalize_json_value(value)
        if len(compact_json_bytes(normalized)) > max_result_bytes:
            raise ResultFormattingError(
                "result_cell_too_large",
                "one database result value exceeds the response budget",
            )
        return normalized

    @staticmethod
    def _normalize_envelope(
        envelope: Mapping[str, Any] | None,
        reserved_fields: set[str],
    ) -> dict[str, Any]:
        if envelope is None:
            return {}
        collisions = reserved_fields.intersection(envelope)
        if collisions:
            raise ValueError(
                f"result envelope uses reserved fields: {', '.join(sorted(collisions))}"
            )
        normalized = normalize_json_value(envelope)
        if not isinstance(normalized, dict):
            raise ValueError("result envelope must be a mapping")
        return normalized

    def _ensure_metadata_fits(
        self,
        payload: dict[str, Any],
        envelope: Mapping[str, Any],
        max_result_bytes: int,
    ) -> None:
        if self._payload_size(payload, envelope) > max_result_bytes:
            raise ResultFormattingError(
                "result_metadata_too_large",
                "result metadata exceeds the response budget",
            )

    @staticmethod
    def _query_payload(
        *,
        columns: Sequence[dict[str, str]],
        rows: Sequence[Sequence[Any]],
        truncated: bool,
        truncation_reason: TruncationReason | None,
        elapsed_ms: int,
    ) -> dict[str, Any]:
        return {
            "columns": list(columns),
            "rows": [list(row) for row in rows],
            "returned_rows": len(rows),
            "truncated": truncated,
            "truncation_reason": truncation_reason,
            "elapsed_ms": elapsed_ms,
            "result_bytes": 0,
        }

    @staticmethod
    def _search_payload(
        *,
        objects: Sequence[dict[str, Any]],
        truncated: bool,
        truncation_reason: TruncationReason | None,
        elapsed_ms: int,
    ) -> dict[str, Any]:
        return {
            "objects": list(objects),
            "returned_count": len(objects),
            "truncated": truncated,
            "truncation_reason": truncation_reason,
            "elapsed_ms": elapsed_ms,
            "result_bytes": 0,
        }

    @staticmethod
    def _payload_size(payload: dict[str, Any], envelope: Mapping[str, Any]) -> int:
        sized_payload = {**envelope, **payload}
        previous = -1
        size = 0
        for _ in range(8):
            sized_payload["result_bytes"] = size
            size = len(compact_json_bytes(sized_payload))
            if size == previous:
                return size
            previous = size
        return size
