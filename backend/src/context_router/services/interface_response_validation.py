from __future__ import annotations

import json
from typing import Any


class InterfaceResponseValidator:
    """Bounded structural and business-envelope validation for forwarding responses."""

    @classmethod
    def validate(
        cls,
        *,
        status_code: int | None,
        response_body: str,
        response_schema: dict[str, Any] | None,
        response_rule: dict[str, Any] | None,
        response_truncated: bool,
        error_type: str | None,
    ) -> dict[str, object]:
        transport = cls._transport(status_code, error_type)
        payload, parse_status = cls._payload(response_body)
        schema = cls._schema(payload, response_schema or {}, parse_status)
        business = cls._business(payload, response_rule or {}, parse_status)
        checks: dict[str, object] = {
            "transport": transport,
            "parse": parse_status,
            "schema": schema,
            "business": business,
        }
        failures = [
            name
            for name, item in checks.items()
            if isinstance(item, dict) and item.get("status") == "failed"
        ]
        warnings: list[str] = []
        if response_truncated:
            warnings.append("响应已截断，结构验证只覆盖已保存部分")
        if failures:
            status = "failed"
        elif response_truncated or any(
            isinstance(item, dict) and item.get("status") in {"warning", "not_configured"}
            for item in checks.values()
        ):
            status = "warning"
        else:
            status = "passed"
        return {
            "status": status,
            "checks": checks,
            "warnings": warnings,
            "failure_checks": failures,
        }

    @staticmethod
    def _transport(status_code: int | None, error_type: str | None) -> dict[str, object]:
        if error_type:
            return {"status": "failed", "message": f"请求错误：{error_type}"}
        if status_code is None:
            return {"status": "failed", "message": "没有 HTTP 状态码"}
        if not 200 <= status_code < 300:
            return {"status": "failed", "message": f"HTTP {status_code}"}
        return {"status": "passed", "status_code": status_code}

    @staticmethod
    def _payload(response_body: str) -> tuple[Any, dict[str, object]]:
        if not response_body.strip():
            return None, {"status": "warning", "message": "响应正文为空"}
        try:
            return json.loads(response_body), {"status": "passed", "format": "json"}
        except json.JSONDecodeError:
            return response_body, {"status": "warning", "format": "text"}

    @classmethod
    def _schema(
        cls,
        payload: Any,
        schema: dict[str, Any],
        parse_status: dict[str, object],
    ) -> dict[str, object]:
        if not schema:
            return {"status": "not_configured", "message": "接口未声明响应 Schema"}
        if parse_status.get("format") != "json":
            return {"status": "warning", "message": "非 JSON 响应无法校验 Schema"}
        expected_type = str(schema.get("type") or "object")
        if not cls._matches_type(payload, expected_type):
            return {
                "status": "failed",
                "message": f"响应类型不匹配，期望 {expected_type}",
            }
        if not isinstance(payload, dict):
            return {"status": "passed", "checked_fields": 0}
        missing = [
            str(name)
            for name in schema.get("required") or []
            if isinstance(name, str) and name not in payload
        ]
        if missing:
            return {"status": "failed", "missing_required": missing}
        properties = schema.get("properties")
        invalid: list[dict[str, str]] = []
        checked = 0
        if isinstance(properties, dict):
            for name, raw_field in list(properties.items())[:200]:
                if name not in payload or not isinstance(raw_field, dict):
                    continue
                field_type = raw_field.get("type")
                if not isinstance(field_type, str):
                    continue
                checked += 1
                if not cls._matches_type(payload[name], field_type):
                    invalid.append({"name": str(name), "expected_type": field_type})
        if invalid:
            return {"status": "failed", "invalid_fields": invalid}
        return {"status": "passed", "checked_fields": checked}

    @classmethod
    def _business(
        cls,
        payload: Any,
        rule: dict[str, Any],
        parse_status: dict[str, object],
    ) -> dict[str, object]:
        if parse_status.get("format") != "json" or not isinstance(payload, dict):
            return {"status": "not_configured", "message": "没有可校验的 JSON 业务状态"}
        if rule:
            paths = cls._string_list(rule.get("success_code_paths"))
            success_values = rule.get("success_values")
            allowed = success_values if isinstance(success_values, list) else []
            for path in paths:
                found, value = cls._path_value(payload, path)
                if not found:
                    continue
                if (
                    allowed
                    and value not in allowed
                    and str(value) not in {str(item) for item in allowed}
                ):
                    return {
                        "status": "failed",
                        "path": path,
                        "actual": value,
                        "expected": allowed[:20],
                    }
                return {"status": "passed", "path": path, "actual": value}
            return {"status": "warning", "message": "响应中没有找到已配置的业务状态字段"}
        if payload.get("success") is False:
            return {"status": "failed", "path": "success", "actual": False}
        if "code" in payload and str(payload["code"]).casefold() not in {
            "0",
            "200",
            "success",
            "ok",
        }:
            return {"status": "failed", "path": "code", "actual": payload["code"]}
        if "success" in payload or "code" in payload:
            return {"status": "passed", "source": "common_envelope"}
        return {"status": "not_configured", "message": "未配置业务成功规则"}

    @staticmethod
    def _matches_type(value: Any, expected: str) -> bool:
        if value is None:
            return True
        return {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }.get(expected, True)

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        return [str(item) for item in value if str(item)] if isinstance(value, list) else []

    @staticmethod
    def _path_value(payload: dict[str, Any], path: str) -> tuple[bool, Any]:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return False, None
            current = current[part]
        return True, current
