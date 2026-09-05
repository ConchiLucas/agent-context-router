from __future__ import annotations

import re

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _safe_browser_post_patterns(api_prefix: str) -> tuple[re.Pattern[str], ...]:
    prefix = re.escape(api_prefix.rstrip("/"))
    return (
        re.compile(rf"^{prefix}/data-sources/[^/]+/reveal-password$"),
        re.compile(rf"^{prefix}/data-sources/[^/]+/test$"),
        re.compile(rf"^{prefix}/mcp/integration/tests$"),
        re.compile(rf"^{prefix}/workspaces/[^/]+/prepare-preview$"),
        re.compile(rf"^{prefix}/workspaces/[^/]+/refresh$"),
        re.compile(rf"^{prefix}/workspaces/reload-local-mapping$"),
        re.compile(rf"^{prefix}/workspaces/[^/]+/shared-files/(restore|publish)$"),
        re.compile(rf"^{prefix}/workspaces/[^/]+/containers/bulk-action$"),
        re.compile(rf"^{prefix}/workspaces/[^/]+/host-runtime/actions$"),
        re.compile(rf"^{prefix}/workspaces/[^/]+/relation-records/search$"),
        re.compile(rf"^{prefix}/projects/[^/]+/runtime-config/(fast|full)/execute$"),
        re.compile(rf"^{prefix}/interface-forwarding/(import|environments|identities)$"),
        re.compile(rf"^{prefix}/interface-forwarding/interfaces/[^/]+/execute$"),
        re.compile(rf"^{prefix}/value-mappings$"),
        re.compile(rf"^{prefix}/value-mappings/[^/]+/preview$"),
        re.compile(rf"^{prefix}/shared-config/ai/refresh$"),
    )


def browser_request_allowed(
    *,
    method: str,
    path: str,
    api_prefix: str,
) -> bool:
    normalized_method = method.upper()
    if normalized_method in _READ_METHODS:
        return True
    if normalized_method == "POST":
        return any(pattern.fullmatch(path) for pattern in _safe_browser_post_patterns(api_prefix))
    if normalized_method == "PUT":
        prefix = re.escape(api_prefix.rstrip("/"))
        if re.fullmatch(
            rf"{prefix}/interface-forwarding/interfaces/[^/]+/semantics",
            path,
        ):
            return True
        if re.fullmatch(
            rf"{prefix}/interface-forwarding/(services|environments|identities)/[^/]+",
            path,
        ):
            return True
        if re.fullmatch(rf"{prefix}/value-mappings/[^/]+", path):
            return True
        if re.fullmatch(rf"{prefix}/shared-config/ai/default", path):
            return True
        return re.fullmatch(rf"{prefix}/system-guides/[^/]+/content", path) is not None
    if normalized_method == "DELETE":
        prefix = re.escape(api_prefix.rstrip("/"))
        if re.fullmatch(
            rf"{prefix}/interface-forwarding/(services|interfaces|environments|identities)/[^/]+",
            path,
        ):
            return True
        return re.fullmatch(rf"{prefix}/value-mappings/[^/]+", path) is not None
    return False


class BrowserReadOnlyMiddleware:
    """Keep browser writes limited to explicitly managed surfaces.

    Browsers identify themselves through Origin or Fetch Metadata headers.
    Local AI and operations clients without those browser headers can continue
    to use the validated command endpoints. Browser requests are limited to
    reads, an explicit diagnostic/read-sensitive POST allowlist, and validated
    updates to existing system-guide content.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_prefix: str,
    ) -> None:
        self._app = app
        self._api_prefix = api_prefix

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        is_browser_request = any(
            headers.get(name) is not None for name in ("origin", "sec-fetch-mode", "sec-fetch-site")
        )
        method = str(scope.get("method", "GET"))
        path = str(scope.get("path", ""))
        if (
            is_browser_request
            and path.startswith(self._api_prefix.rstrip("/") + "/")
            and not browser_request_allowed(
                method=method,
                path=path,
                api_prefix=self._api_prefix,
            )
        ):
            response = JSONResponse(
                status_code=405,
                content={
                    "detail": (
                        "management_read_only: 管理界面只提供查看；"
                        "配置变更请由本机 AI 或运维命令执行"
                    )
                },
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)
