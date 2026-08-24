from __future__ import annotations

from datetime import UTC, datetime

import pytest

from context_router.services.visualization_pagination import (
    VisualizationCursorError,
    decode_visualization_cursor,
    encode_visualization_cursor,
)
from context_router.services.visualization_security import (
    redact_table_rows,
    redact_text,
    redact_value,
)


def test_redacts_nested_payload_text_and_sensitive_table_columns() -> None:
    payload = {
        "user": {
            "password": "plain-password",
            "profile": {"mobile": "13800000000", "name": "张三"},
        },
        "message": "authorization=plain-token",
    }

    assert redact_value(payload) == {
        "user": {
            "password": "[REDACTED]",
            "profile": {"mobile": "[REDACTED]", "name": "张三"},
        },
        "message": "authorization=[REDACTED]",
    }
    assert redact_text("Bearer abc.def") == "Bearer [REDACTED]"
    assert redact_table_rows(
        ["id", "phone", "name"],
        [[1, "13800000000", "张三"]],
    ) == [[1, "[REDACTED]", "张三"]]


def test_visualization_cursor_is_opaque_and_rejects_invalid_values() -> None:
    timestamp = datetime(2026, 8, 24, 8, 30, tzinfo=UTC)
    cursor = encode_visualization_cursor(timestamp, "record-1")

    assert decode_visualization_cursor(cursor) == (timestamp, "record-1")
    with pytest.raises(VisualizationCursorError):
        decode_visualization_cursor("not-a-cursor")
