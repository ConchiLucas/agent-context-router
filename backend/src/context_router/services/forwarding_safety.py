"""Protocol exclusions from ordinary completed-response forwarding."""

import re
from urllib.parse import unquote, urlsplit


def is_sse_control(path: str) -> bool:
    normalized = re.sub(r"/+", "/", unquote(urlsplit(path).path)).rstrip("/").lower()
    return bool(re.search(r"/sse/(connect|disconnect|subscribe|unsubscribe)$", normalized))
