from __future__ import annotations

import re
from collections.abc import Iterable

_SERVICE_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+)(?![A-Za-z0-9])"
)

_SIGNAL_ALIASES: dict[str, tuple[str, ...]] = {
    "role:portal": ("门户", "portal", "web端", "前台"),
    "role:admin": ("运营端", "管理端", "后台", "admin", "console", "backoffice"),
    "role:internal": ("内部", "internal", "private"),
    "role:remote": ("远程", "remote"),
    "auth:no_auth": ("免登录", "免鉴权", "无需鉴权", "noauth", "no-auth", "anonymous"),
    "layer:gateway": ("聚合入口", "聚合接口", "网关入口", "网关接口", "gateway", "bff", "facade"),
    "layer:direct": ("下游直连", "直连接口", "直接调用下游", "direct"),
    "transport:railway": ("铁路", "railway", "rail"),
    "transport:highway": ("公路", "highway", "road"),
    "transport:shipping": ("海运", "水运", "水路", "shipping", "ocean", "sea"),
    "operation:preview": ("预览", "preview"),
    "operation:track": ("轨迹", "跟踪", "track", "tracking"),
    "operation:detail": (
        "详情",
        "明细",
        "detail",
        "getdetail",
        "getinfo",
        "finddetail",
    ),
    "operation:page": ("分页", "page"),
    "operation:confirm": ("确认", "confirm"),
    "operation:arrive": ("到达", "抵达", "到港", "进场", "arrive", "arrival"),
    "operation:generate": ("生成", "generate", "createby"),
    "operation:reject": ("驳回", "拒绝", "reject"),
    "output:url": ("访问地址", "预览地址", "文件地址", "下载地址", "url"),
    "output:content": ("文件内容", "文件流", "流式响应", "binary", "stream"),
}

_SERVICE_ROLE_TOKENS: dict[str, tuple[str, ...]] = {
    "role:portal": ("portal", "web", "frontend"),
    "role:admin": ("admin", "console", "management", "backoffice"),
    "role:internal": ("internal", "private"),
    "role:remote": ("remote", "external"),
    "layer:gateway": ("gateway", "bff", "edge", "facade", "proxy", "portal"),
}


def extract_service_hints(text: str, existing: Iterable[str] = ()) -> list[str]:
    """Return explicit service selectors plus conventional service-role hints.

    The extraction is deliberately workspace-neutral. It recognizes technical
    service identifiers and common architectural roles, but never maps a
    business path or a concrete workspace service name.
    """

    hints = [value for value in existing if value]
    hints.extend(match.group(1).lower() for match in _SERVICE_TOKEN_RE.finditer(text))
    return list(dict.fromkeys(hints))[:30]


def infer_query_route_signals(text: str) -> list[str]:
    lowered = _compact(text)
    signals = [
        signal
        for signal, aliases in _SIGNAL_ALIASES.items()
        if any(_compact(alias) in lowered for alias in aliases)
    ]
    explicit_layer = any(signal.startswith("layer:") for signal in signals)
    explicit_service = bool(_SERVICE_TOKEN_RE.search(text))
    # A caller-facing portal request may prefer a portal/BFF entry, but the
    # actor alone is not proof of the call layer. Keep this as a weak preference
    # so direct service endpoints remain viable candidates.
    lower_layer_role = bool({"role:internal", "role:remote"} & set(signals))
    if (
        "role:portal" in signals
        and not explicit_layer
        and not explicit_service
        and not lower_layer_role
    ):
        signals.append("preference:gateway")
    return list(dict.fromkeys(signals))


def infer_query_call_layer(text: str) -> str:
    signals = set(infer_query_route_signals(text))
    if "layer:gateway" in signals:
        return "frontend_gateway"
    if "layer:direct" in signals:
        return "service_direct"
    return "unknown"


def infer_endpoint_route_signals(
    *,
    project: str,
    service: str,
    path: str,
    operation_id: str,
    title: str,
    actions: Iterable[str] = (),
    semantic_terms: Iterable[str] = (),
) -> list[str]:
    identity_text = " ".join(
        (project, service, path, operation_id, title, *actions, *semantic_terms)
    )
    lowered = _compact(identity_text)
    service_tokens = set(_technical_tokens(" ".join((project, service))))
    path_tokens = set(_technical_tokens(path))
    signals: list[str] = []
    for signal, aliases in _SIGNAL_ALIASES.items():
        if signal.startswith(("operation:", "transport:", "output:")) and any(
            _compact(alias) in lowered for alias in aliases
        ):
            signals.append(signal)
    for signal, tokens in _SERVICE_ROLE_TOKENS.items():
        if service_tokens & set(tokens):
            signals.append(signal)
    if path_tokens & {"portal", "admin", "internal", "private", "remote", "external"}:
        for token in path_tokens:
            mapped = {
                "portal": "role:portal",
                "admin": "role:admin",
                "internal": "role:internal",
                "private": "role:internal",
                "remote": "role:remote",
                "external": "role:remote",
            }.get(token)
            if mapped:
                signals.append(mapped)
    if path_tokens & {"noauth", "no-auth", "anonymous", "public"}:
        signals.append("auth:no_auth")
    if "layer:gateway" not in signals:
        signals.append("layer:direct")
    return list(dict.fromkeys(signals))


def infer_endpoint_call_layer(
    *,
    project: str,
    service: str,
    path: str,
    operation_id: str,
    title: str,
    actions: Iterable[str] = (),
) -> str:
    signals = set(
        infer_endpoint_route_signals(
            project=project,
            service=service,
            path=path,
            operation_id=operation_id,
            title=title,
            actions=actions,
        )
    )
    if "layer:gateway" in signals:
        return "frontend_gateway"
    if "layer:direct" in signals:
        return "service_direct"
    return "unknown"


def route_identity_score(
    *,
    query: str,
    project: str,
    service: str,
    path: str,
    operation_id: str,
    title: str,
    actions: Iterable[str] = (),
    semantic_terms: Iterable[str] = (),
) -> float:
    query_lower = query.lower()
    service_selected = _contains_identifier(query_lower, service) or _contains_identifier(
        query_lower, project
    )
    operation_selectors = set(_query_operation_selectors(query))
    endpoint_selectors = {
        path.rstrip("/").rsplit("/", 1)[-1].lower(),
        operation_id.rsplit(".", 1)[-1].lower(),
    }
    operation_selected = bool(operation_selectors & endpoint_selectors)
    if service_selected and operation_selected:
        return 1.0
    query_signals = set(infer_query_route_signals(query))
    endpoint_signals = set(
        infer_endpoint_route_signals(
            project=project,
            service=service,
            path=path,
            operation_id=operation_id,
            title=title,
            actions=actions,
            semantic_terms=semantic_terms,
        )
    )
    matched = query_signals & endpoint_signals
    implicit_gateway_preference = (
        "preference:gateway" in query_signals and "layer:gateway" in endpoint_signals
    )
    if not matched:
        if service_selected:
            return 0.94
        if operation_selected:
            return 0.9
        return 0.6 if implicit_gateway_preference else 0.0
    weights = {
        "layer:": 0.92,
        "auth:": 0.88,
        "transport:": 0.82,
        "role:portal": 0.56,
        "role:admin": 0.56,
        "role:internal": 0.72,
        "role:remote": 0.78,
        "operation:": 0.66,
        "output:": 0.62,
    }
    scores: list[float] = []
    signal_groups: set[str] = set()
    for signal in matched:
        signal_groups.add(signal.split(":", 1)[0])
        if signal in weights:
            scores.append(weights[signal])
            continue
        scores.extend(weight for prefix, weight in weights.items() if signal.startswith(prefix))
    base = max(scores, default=0.0)
    multi_signal_bonus = min(0.12, max(0, len(signal_groups) - 1) * 0.04)
    if service_selected:
        return min(0.99, max(0.94, base) + min(0.05, len(signal_groups) * 0.02))
    if operation_selected:
        return min(0.98, max(0.9, base) + min(0.04, len(signal_groups) * 0.02))
    score = base + multi_signal_bonus
    if implicit_gateway_preference:
        score = max(score, 0.6)
    return min(0.98, score)


def service_hint_score(service: str, hints: Iterable[str]) -> float:
    normalized_service = service.strip().lower()
    if not normalized_service:
        return 0.0
    service_tokens = set(_technical_tokens(normalized_service))
    for hint in hints:
        normalized_hint = hint.strip().lower()
        if not normalized_hint:
            continue
        if normalized_service == normalized_hint:
            return 1.0
        if normalized_hint in service_tokens:
            return 0.9
    return 0.0


def describe_endpoint_route(
    *, project: str, service: str, path: str, operation_id: str, title: str, actions: Iterable[str]
) -> str:
    signals = infer_endpoint_route_signals(
        project=project,
        service=service,
        path=path,
        operation_id=operation_id,
        title=title,
        actions=actions,
    )
    return " ".join(signals)


def _technical_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", value.lower()) if token]


def _query_operation_selectors(value: str) -> list[str]:
    selectors = re.findall(
        r"(?:的|调用|操作(?:标识)?[:：]?|operation(?:_id)?[:=]?)\s*"
        r"(?<![A-Za-z0-9_$-])([A-Za-z][A-Za-z0-9_$]{2,})(?![A-Za-z0-9_$-])",
        value,
        re.I,
    )
    selectors.extend(
        re.findall(
            r"(?<![A-Za-z0-9_$])[a-z][A-Za-z0-9_$]*[A-Z][A-Za-z0-9_$]*"
            r"(?![A-Za-z0-9_$])",
            value,
        )
    )
    return list(dict.fromkeys(item.lower() for item in selectors))


def _contains_identifier(query: str, identifier: str) -> bool:
    normalized = identifier.strip().lower()
    if len(normalized) < 3:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", query))


def _compact(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value).lower()
