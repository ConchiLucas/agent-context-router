from __future__ import annotations

import base64
import json
from datetime import datetime


class VisualizationCursorError(ValueError):
    pass


def encode_visualization_cursor(timestamp: datetime, record_id: str) -> str:
    payload = json.dumps(
        {"timestamp": timestamp.isoformat(), "id": record_id},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_visualization_cursor(value: str) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(f"{value}{padding}").decode())
        timestamp = datetime.fromisoformat(str(payload["timestamp"]))
        record_id = str(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise VisualizationCursorError("分页游标无效，请重新加载列表") from exc
    if not record_id or timestamp.tzinfo is None:
        raise VisualizationCursorError("分页游标无效，请重新加载列表")
    return timestamp, record_id
