from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

VISUALIZATION_RETENTION_DAYS = 30
REDACTED = "[REDACTED]"

_SENSITIVE_FIELD_PATTERN = re.compile(
    r"(?i)(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password|passwd|secret|cookie|session|credential|private[_-]?key|"
    r"phone|mobile|id[_-]?card|identity[_-]?number)"
)
_SENSITIVE_KEY_VALUE_PATTERN = re.compile(
    r"(?i)(\b(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password|passwd|secret|cookie|session|credential|private[_-]?key|"
    r"phone|mobile|id[_-]?card|identity[_-]?number)\b\s*[:=]\s*)"
    r"([^\s,;]+|\"[^\"]*\")"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIAL_PATTERN = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^\s:/]+:)([^@\s]+)(@)")


def is_sensitive_field(name: str) -> bool:
    normalized = name.strip().lower().replace(" ", "_")
    return normalized == "token" or bool(_SENSITIVE_FIELD_PATTERN.search(normalized))


def redact_text(value: str) -> str:
    value = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", value)
    value = _SENSITIVE_KEY_VALUE_PATTERN.sub(
        lambda match: f"{match.group(1)}{REDACTED}",
        value,
    )
    return _URL_CREDENTIAL_PATTERN.sub(rf"\1{REDACTED}\3", value)


def redact_value(value: Any, *, field_name: str | None = None) -> Any:
    if field_name and is_sensitive_field(field_name):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(key): redact_value(item, field_name=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_table_rows(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[list[Any]]:
    sensitive_indexes = {
        index for index, column in enumerate(columns) if is_sensitive_field(column)
    }
    return [
        [
            REDACTED if index in sensitive_indexes else redact_value(value)
            for index, value in enumerate(row)
        ]
        for row in rows
    ]
