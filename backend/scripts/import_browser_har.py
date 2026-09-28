#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_BATCH_SIZE = 200
_DEFAULT_ENVIRONMENT_ENTRY_URLS = {
    "test": "http://192.168.0.222:18080/op/login",
    "uat": "http://192.168.0.222:28080/op/login",
}


def _body(value: object, *, base64_encoded: bool = False) -> object:
    if value is None:
        return None
    text = str(value)
    if base64_encoded:
        try:
            text = base64.b64decode(text, validate=True).decode("utf-8", errors="replace")
        except (ValueError, UnicodeError):
            return "[无法解码的 base64 响应]"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def har_to_captures(payload: dict[str, Any]) -> list[dict[str, Any]]:
    log = payload.get("log")
    entries = log.get("entries") if isinstance(log, dict) else None
    if not isinstance(entries, list):
        raise ValueError("HAR 缺少 log.entries 数组")
    captures: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        request = entry.get("request")
        response = entry.get("response")
        if not isinstance(request, dict) or not isinstance(response, dict):
            continue
        method = str(request.get("method") or "").upper()
        url = str(request.get("url") or "")
        if method not in _METHODS or not url.startswith(("http://", "https://")):
            continue
        post_data = request.get("postData")
        request_text = post_data.get("text") if isinstance(post_data, dict) else None
        content = response.get("content")
        response_text = content.get("text") if isinstance(content, dict) else None
        response_encoding = content.get("encoding") if isinstance(content, dict) else None
        status = response.get("status")
        captures.append(
            {
                "url": url,
                "method": method,
                "request_body": _body(request_text),
                "response_body": _body(
                    response_text,
                    base64_encoded=response_encoding == "base64",
                ),
                "status_code": status if isinstance(status, int) and 100 <= status <= 599 else None,
                "duration_ms": min(600_000, max(0, round(float(entry.get("time") or 0)))),
            }
        )
    return captures


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"无效的环境入口地址：{url}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname.lower(), port


def _capture_path_score(base_url: str, captures: list[dict[str, Any]]) -> int:
    base_path = urlsplit(base_url).path.rstrip("/")
    if not base_path:
        return 0
    return sum(
        1
        for capture in captures
        if (path := urlsplit(str(capture.get("url") or "")).path.rstrip("/")) == base_path
        or path.startswith(f"{base_path}/")
    )


def select_environment_address(
    environments: list[dict[str, Any]],
    *,
    environment_key: str,
    entry_url: str,
    captures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Select one configured forwarding address for a named environment and origin."""
    environment = next(
        (
            item
            for item in environments
            if str(item.get("environment_key") or "").lower() == environment_key.lower()
        ),
        None,
    )
    if environment is None:
        raise ValueError(f"工作空间没有登记 {environment_key} 环境")

    expected_origin = _origin(entry_url)
    candidates = [
        address
        for address in environment.get("addresses") or []
        if _origin(str(address.get("base_url") or "")) == expected_origin
    ]
    if not candidates:
        raise ValueError(f"{environment_key} 环境没有与入口 {entry_url} 同源的接口转发地址")

    # A workspace can have several services on one gateway. Prefer the address whose
    # configured path covers the most captured requests, then use stable metadata so
    # repeated imports make the same choice.
    return min(
        candidates,
        key=lambda address: (
            -_capture_path_score(str(address.get("base_url") or ""), captures),
            str(address.get("service_name") or "").lower(),
            str(address.get("name") or "").lower(),
            str(address.get("id") or ""),
        ),
    )


def resolve_environment_id(
    *,
    api_base: str,
    workspace_id: str,
    environment_key: str,
    entry_url: str,
    captures: list[dict[str, Any]],
) -> str:
    endpoint = f"{api_base.rstrip('/')}/interface-forwarding/environments"
    response = httpx.get(endpoint, params={"workspace_id": workspace_id}, timeout=30)
    response.raise_for_status()
    environments = response.json()
    if not isinstance(environments, list):
        raise ValueError("接口转发环境响应格式不正确")
    selected = select_environment_address(
        environments,
        environment_key=environment_key,
        entry_url=entry_url,
        captures=captures,
    )
    environment_id = selected.get("id")
    if not isinstance(environment_id, str) or not environment_id:
        raise ValueError("选中的接口转发地址缺少 ID")
    return environment_id


def import_captures(
    *,
    api_base: str,
    workspace_id: str,
    environment_id: str,
    identity_id: str | None,
    allow_origin_mismatch: bool,
    captures: list[dict[str, Any]],
) -> dict[str, Any]:
    totals: dict[str, Any] = {
        "captured_count": len(captures),
        "imported_count": 0,
        "skipped_count": 0,
        "imported": [],
        "skipped": [],
    }
    endpoint = f"{api_base.rstrip('/')}/interface-forwarding/browser-captures"
    with httpx.Client(timeout=60) as client:
        for offset in range(0, len(captures), _BATCH_SIZE):
            response = client.post(
                endpoint,
                json={
                    "workspace_id": workspace_id,
                    "environment_id": environment_id,
                    "identity_id": identity_id,
                    "allow_origin_mismatch": allow_origin_mismatch,
                    "captures": captures[offset : offset + _BATCH_SIZE],
                },
            )
            response.raise_for_status()
            result = response.json()
            totals["imported_count"] += int(result.get("imported_count") or 0)
            totals["skipped_count"] += int(result.get("skipped_count") or 0)
            totals["imported"].extend(result.get("imported") or [])
            totals["skipped"].extend(result.get("skipped") or [])
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(
        description="导入 Chrome DevTools HAR，并写入 Context Router 接口请求日志"
    )
    parser.add_argument("har", type=Path, help="Chrome DevTools 导出的 HAR 文件")
    parser.add_argument("--workspace-id", required=True)
    environment = parser.add_mutually_exclusive_group(required=True)
    environment.add_argument("--environment-id", help="接口转发地址 ID（兼容原用法）")
    environment.add_argument(
        "--environment",
        choices=sorted(_DEFAULT_ENVIRONMENT_ENTRY_URLS),
        help="按已登记的环境和入口地址自动选择接口转发地址",
    )
    parser.add_argument(
        "--environment-url",
        help="覆盖所选环境的默认入口地址；只能与 --environment 一起使用",
    )
    parser.add_argument("--identity-id")
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:49173/api",
        help="Context Router 本机 API 根地址",
    )
    parser.add_argument(
        "--allow-origin-mismatch",
        action="store_true",
        help="开发代理导致浏览器请求 Origin 与转发地址不同时显式启用",
    )
    arguments = parser.parse_args()
    payload = json.loads(arguments.har.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("HAR 根节点必须是 JSON 对象")
    captures = har_to_captures(payload)
    if not captures:
        raise ValueError("HAR 中没有可导入的 HTTP 请求")
    if arguments.environment_url and not arguments.environment:
        parser.error("--environment-url 只能与 --environment 一起使用")
    environment_id = arguments.environment_id
    entry_url = None
    if arguments.environment:
        entry_url = (
            arguments.environment_url or _DEFAULT_ENVIRONMENT_ENTRY_URLS[arguments.environment]
        )
        environment_id = resolve_environment_id(
            api_base=arguments.api_base,
            workspace_id=arguments.workspace_id,
            environment_key=arguments.environment,
            entry_url=entry_url,
            captures=captures,
        )
    assert environment_id is not None
    result = import_captures(
        api_base=arguments.api_base,
        workspace_id=arguments.workspace_id,
        environment_id=environment_id,
        identity_id=arguments.identity_id,
        allow_origin_mismatch=arguments.allow_origin_mismatch,
        captures=captures,
    )
    if arguments.environment:
        result["environment"] = arguments.environment
        result["environment_entry_url"] = entry_url
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
