from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Any

from context_router.database.result import compact_json_bytes, normalize_json_value
from context_router.repositories.database_tool_payload_repository import (
    DatabaseToolPayloadRecord,
    DatabaseToolPayloadRepositoryError,
    DatabaseToolPayloadStatus,
    DatabaseToolPayloadStore,
    DatabaseToolPayloadWrite,
)

logger = logging.getLogger(__name__)

SEARCH_DATABASE_TOOL_NAME = "search_database_objects"
EXECUTE_DATABASE_TOOL_NAME = "execute_database_query"
DATABASE_PAYLOAD_TOOL_NAMES = frozenset(
    {
        SEARCH_DATABASE_TOOL_NAME,
        EXECUTE_DATABASE_TOOL_NAME,
    }
)
_CAPTURE_VERSION = 1
_ABSOLUTE_MAX_BYTES = 4_000_000


class DatabaseToolPayloadServiceError(RuntimeError):
    pass


class DatabaseToolPayloadService:
    def __init__(
        self,
        repository: DatabaseToolPayloadStore,
        *,
        capture_enabled: bool = False,
        request_max_bytes: int = 1_000_000,
        response_max_bytes: int = 1_000_000,
        hard_max_bytes: int = _ABSOLUTE_MAX_BYTES,
        ttl_days: int = 7,
        cleanup_interval_seconds: int = 3_600,
    ) -> None:
        hard_limit = min(max(hard_max_bytes, 1), _ABSOLUTE_MAX_BYTES)
        self._repository = repository
        self._capture_enabled = capture_enabled
        self._request_max_bytes = min(max(request_max_bytes, 1), hard_limit)
        self._response_max_bytes = min(max(response_max_bytes, 1), hard_limit)
        self._ttl = timedelta(days=max(ttl_days, 1))
        self._cleanup_interval_seconds = max(cleanup_interval_seconds, 60)
        self._cleanup_lock = Lock()
        self._last_cleanup_at = 0.0

    @property
    def capture_enabled(self) -> bool:
        return self._capture_enabled

    def capture_request(
        self,
        tool_call_id: int | None,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        if tool_call_id is None or tool_name not in DATABASE_PAYLOAD_TOOL_NAMES:
            return
        if not self._capture_enabled:
            self.cleanup_expired()
            return
        try:
            request = _database_request_payload(tool_name, arguments)
            payload, payload_bytes, truncated = _bounded_payload(
                request,
                self._request_max_bytes,
                collection_key=None,
            )
            self._repository.create_request(
                DatabaseToolPayloadWrite(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    request_payload=payload,
                    request_bytes=payload_bytes,
                    request_truncated=truncated,
                    capture_version=_CAPTURE_VERSION,
                    expires_at=datetime.now(UTC) + self._ttl,
                )
            )
        except Exception:
            logger.warning("Unable to persist database MCP request payload", exc_info=True)
        finally:
            self.cleanup_expired()

    def capture_response(
        self,
        tool_call_id: int | None,
        *,
        tool_name: str,
        status: DatabaseToolPayloadStatus,
        payload: dict[str, Any] | None,
        capture_error_code: str | None = None,
    ) -> None:
        if (
            not self._capture_enabled
            or tool_call_id is None
            or tool_name not in DATABASE_PAYLOAD_TOOL_NAMES
        ):
            return
        try:
            bounded_payload: dict[str, object] | None = None
            response_bytes: int | None = None
            response_truncated = False
            if payload is not None:
                collection_key = "objects" if tool_name == SEARCH_DATABASE_TOOL_NAME else "rows"
                bounded_payload, response_bytes, response_truncated = _bounded_payload(
                    payload,
                    self._response_max_bytes,
                    collection_key=collection_key,
                )
            self._repository.complete_response(
                tool_call_id,
                status=status,
                response_payload=bounded_payload,
                response_bytes=response_bytes,
                response_truncated=response_truncated,
                capture_error_code=capture_error_code,
            )
        except Exception:
            logger.warning("Unable to persist database MCP response payload", exc_info=True)
            self._mark_capture_failed(tool_call_id)

    def metadata_for_calls(
        self,
        tool_call_ids: list[int],
    ) -> dict[int, DatabaseToolPayloadRecord]:
        if not tool_call_ids:
            return {}
        try:
            records = self._repository.list_metadata(tool_call_ids)
            now = datetime.now(UTC)
            if any(
                record.response_status != "expired" and record.expires_at <= now
                for record in records.values()
            ):
                self.cleanup_expired(force=True, now=now)
                records = self._repository.list_metadata(tool_call_ids)
            return records
        except Exception:
            logger.warning("Unable to read database MCP payload metadata", exc_info=True)
            return {}

    def get_payload(self, tool_call_id: int) -> DatabaseToolPayloadRecord | None:
        try:
            record = self._repository.get_payload(tool_call_id)
            if (
                record is not None
                and record.response_status != "expired"
                and record.expires_at <= datetime.now(UTC)
            ):
                self.cleanup_expired(force=True)
                record = self._repository.get_payload(tool_call_id)
            return record
        except DatabaseToolPayloadRepositoryError as exc:
            raise DatabaseToolPayloadServiceError(str(exc)) from exc

    def reconcile_startup(self) -> tuple[int, int]:
        now = datetime.now(UTC)
        try:
            interrupted = self._repository.interrupt_pending(interrupted_at=now)
        except Exception:
            logger.warning("Unable to reconcile interrupted database MCP payloads", exc_info=True)
            interrupted = 0
        expired = self.cleanup_expired(force=True, now=now)
        return interrupted, expired

    def cleanup_expired(
        self,
        *,
        force: bool = False,
        now: datetime | None = None,
    ) -> int:
        current_tick = monotonic()
        with self._cleanup_lock:
            if not force and current_tick - self._last_cleanup_at < self._cleanup_interval_seconds:
                return 0
            self._last_cleanup_at = current_tick
        try:
            return self._repository.expire_payloads(expired_at=now or datetime.now(UTC))
        except Exception:
            logger.warning("Unable to clean expired database MCP payloads", exc_info=True)
            return 0

    def _mark_capture_failed(self, tool_call_id: int) -> None:
        try:
            self._repository.complete_response(
                tool_call_id,
                status="capture_failed",
                response_payload=None,
                response_bytes=None,
                response_truncated=False,
                capture_error_code="payload_capture_failed",
            )
        except Exception:
            logger.warning(
                "Unable to mark database MCP payload capture as failed",
                exc_info=True,
            )


def _database_request_payload(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, object]:
    if tool_name == SEARCH_DATABASE_TOOL_NAME:
        fields = (
            "task_id",
            "database",
            "object_type",
            "pattern",
            "detail",
            "schema",
            "table",
            "limit",
        )
        source = {
            "pattern": "*",
            "detail": "names",
            "schema": None,
            "table": None,
            "limit": 100,
            **{field: arguments[field] for field in fields if field in arguments},
        }
    elif tool_name == EXECUTE_DATABASE_TOOL_NAME:
        fields = ("task_id", "database", "sql")
        source = {field: arguments[field] for field in fields if field in arguments}
    else:
        raise ValueError("database MCP tool is not supported")
    normalized = normalize_json_value(source)
    if not isinstance(normalized, dict):
        raise ValueError("database MCP request payload must be an object")
    return normalized


def _bounded_payload(
    source: dict[str, Any] | dict[str, object],
    max_bytes: int,
    *,
    collection_key: str | None,
) -> tuple[dict[str, object], int, bool]:
    normalized = normalize_json_value(source)
    if not isinstance(normalized, dict):
        raise ValueError("database MCP payload must be an object")
    original_bytes = len(compact_json_bytes(normalized))
    if original_bytes <= max_bytes:
        return normalized, original_bytes, False

    working = dict(normalized)
    original_count: int | None = None
    if collection_key is not None and isinstance(working.get(collection_key), list):
        source_items = list(working[collection_key])
        original_count = len(source_items)
        working[collection_key] = []
        marker = _capture_marker(
            original_bytes=original_bytes,
            collection_key=collection_key,
            original_count=original_count,
            stored_count=0,
        )
        working["_capture"] = marker
        if len(compact_json_bytes(working)) <= max_bytes:
            low = 0
            high = len(source_items)
            while low < high:
                candidate_count = (low + high + 1) // 2
                working[collection_key] = source_items[:candidate_count]
                marker["stored_count"] = candidate_count
                if len(compact_json_bytes(working)) <= max_bytes:
                    low = candidate_count
                else:
                    high = candidate_count - 1
            working[collection_key] = source_items[:low]
            marker["stored_count"] = low

    working["_capture"] = _capture_marker(
        original_bytes=original_bytes,
        collection_key=collection_key if original_count is not None else None,
        original_count=original_count,
        stored_count=(
            len(working.get(collection_key, []))
            if collection_key is not None and original_count is not None
            else None
        ),
    )
    if len(compact_json_bytes(working)) > max_bytes:
        working = _fit_strings(working, max_bytes)
    if len(compact_json_bytes(working)) > max_bytes:
        working = {
            "_capture": _capture_marker(
                original_bytes=original_bytes,
                collection_key=collection_key if original_count is not None else None,
                original_count=original_count,
                stored_count=0 if original_count is not None else None,
            )
        }
    stored_bytes = len(compact_json_bytes(working))
    if stored_bytes > max_bytes:
        raise ValueError("database MCP capture metadata exceeds the configured byte limit")
    return working, stored_bytes, True


def _capture_marker(
    *,
    original_bytes: int,
    collection_key: str | None,
    original_count: int | None,
    stored_count: int | None,
) -> dict[str, object]:
    marker: dict[str, object] = {
        "truncated": True,
        "reason": "capture_bytes",
        "original_bytes": original_bytes,
    }
    if collection_key is not None:
        marker["collection"] = collection_key
    if original_count is not None:
        marker["original_count"] = original_count
    if stored_count is not None:
        marker["stored_count"] = stored_count
    return marker


def _fit_strings(payload: dict[str, object], max_bytes: int) -> dict[str, object]:
    string_lengths = [len(value) for value in _walk_values(payload) if isinstance(value, str)]
    if not string_lengths:
        return payload
    low = 0
    high = max(string_lengths)
    best = _clip_strings(payload, 0)
    while low <= high:
        candidate_length = (low + high) // 2
        candidate = _clip_strings(payload, candidate_length)
        if len(compact_json_bytes(candidate)) <= max_bytes:
            best = candidate
            low = candidate_length + 1
        else:
            high = candidate_length - 1
    return best


def _walk_values(value: object) -> list[object]:
    if isinstance(value, dict):
        values: list[object] = []
        for item in value.values():
            values.extend(_walk_values(item))
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_walk_values(item))
        return values
    return [value]


def _clip_strings(value: object, max_characters: int) -> Any:
    if isinstance(value, str):
        if len(value) <= max_characters:
            return value
        return value[:max_characters]
    if isinstance(value, dict):
        return {
            key: item if key == "_capture" else _clip_strings(item, max_characters)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_clip_strings(item, max_characters) for item in value]
    return value
