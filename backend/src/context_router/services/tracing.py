from datetime import UTC, datetime
from uuid import uuid4


def new_trace_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    suffix = uuid4().hex[:8]
    return f"ctx_{timestamp}_{suffix}"
