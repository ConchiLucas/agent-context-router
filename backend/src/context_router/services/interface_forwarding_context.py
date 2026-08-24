from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote, urljoin, urlsplit
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from context_router.repositories.database_environment_repository import (
    DatabaseEnvironmentRepositoryError,
    DatabaseEnvironmentStore,
)
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
from context_router.services.mcp_trace import current_tool_call_id
from context_router.services.value_mapping import ValueMappingError, ValueMappingService

OperationKind = Literal["read", "write", "destructive", "unknown"]
ValueStrategy = Literal[
    "reuse_successful",
    "refresh_selected",
    "refresh_mapped",
    "ignore_history",
]
_MAX_RESPONSE_BYTES = 1_048_576
_MAX_REQUEST_BYTES = 262_144
_PLAN_TTL = timedelta(minutes=10)
_SAFE_RESPONSE_HEADERS = {"content-type", "x-request-id", "trace-id", "x-trace-id"}
_FORBIDDEN_REQUEST_HEADERS = {
    "connection",
    "content-length",
    "forwarded",
    "host",
    "proxy-authorization",
    "te",
    "transfer-encoding",
    "upgrade",
    "via",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
}
_PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")
_VOLATILE_HISTORY_KEYS = {
    "accesstoken",
    "captcha",
    "nonce",
    "refreshtoken",
    "smscode",
    "timestamp",
    "verificationcode",
    "verifycode",
}
_PAGE_NUMBER_KEYS = {"current", "currentpage", "page", "pagenum", "pagenumber"}
_PAGE_SIZE_KEYS = {"limit", "pagesize"}


class InterfaceForwardingContextError(ValueError):
    def __init__(self, message: str, *, code: str = "interface_forwarding_failed") -> None:
        super().__init__(message)
        self.code = code


class InterfaceForwardingContextService:
    """Task-bound, plan-before-execute interface forwarding for MCP callers."""

    def __init__(
        self,
        *,
        database_url: str | None,
        task_repository: TaskReader,
        database_environment_repository: DatabaseEnvironmentStore,
        value_mapping_service: ValueMappingService | None = None,
        host_runner_available: Callable[[], bool] | None = None,
        host_execution_timeout_seconds: float = 40,
    ) -> None:
        self._database_url = database_url
        self._tasks = task_repository
        self._environments = database_environment_repository
        self._value_mappings = value_mapping_service
        self._host_runner_available = host_runner_available
        self._host_execution_timeout_seconds = max(5.0, host_execution_timeout_seconds)

    def search(
        self,
        *,
        task_id: int,
        query: str,
        service: str | None = None,
        role: str | None = None,
        limit: int = 10,
    ) -> dict[str, object]:
        workspace_id, environment = self._task_scope(task_id, None)
        normalized = query.strip()
        if not normalized:
            raise InterfaceForwardingContextError("query 不能为空", code="invalid_query")
        like = f"%{normalized}%"
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT interface.id, interface.name, interface.controller_name,
                       interface.controller_description, interface.path, interface.method,
                       interface.operation_kind, source.name AS service_name,
                       source.invocation_mode, route.name AS route_service_name,
                       count(DISTINCT address.id)::int AS address_count,
                       count(DISTINCT identity.id)::int AS identity_count,
                       max(log.created_at) AS last_requested_at,
                       count(DISTINCT log.id)::int AS request_count
                FROM interface_forwarding_interfaces AS interface
                JOIN interface_forwarding_services AS source ON source.id=interface.service_id
                LEFT JOIN interface_forwarding_services AS route
                  ON route.id=CASE WHEN source.invocation_mode='gateway'
                                   THEN source.gateway_service_id ELSE source.id END
                LEFT JOIN interface_forwarding_environments AS address
                  ON address.workspace_id=interface.workspace_id
                 AND address.environment_key=%s
                 AND address.service_id=route.id
                LEFT JOIN interface_forwarding_identities AS identity
                  ON identity.environment_id=address.id
                 AND (%s::text IS NULL OR identity.role_name ILIKE %s)
                LEFT JOIN interface_forwarding_logs AS log ON log.interface_id=interface.id
                WHERE interface.workspace_id=%s
                  AND (%s::text IS NULL OR source.name ILIKE %s)
                  AND (interface.name ILIKE %s OR interface.path ILIKE %s
                       OR interface.controller_name ILIKE %s
                       OR interface.controller_description ILIKE %s)
                GROUP BY interface.id, source.id, route.id
                ORDER BY
                  CASE WHEN lower(interface.name)=lower(%s) THEN 0
                       WHEN lower(interface.path)=lower(%s) THEN 1
                       WHEN interface.name ILIKE %s THEN 2 ELSE 3 END,
                  max(log.created_at) DESC NULLS LAST, lower(interface.path), interface.method
                LIMIT %s
                """,
                (
                    environment,
                    role,
                    f"%{role}%" if role else None,
                    workspace_id,
                    service,
                    f"%{service}%" if service else None,
                    like,
                    like,
                    like,
                    like,
                    normalized,
                    normalized,
                    f"{normalized}%",
                    max(1, min(limit, 50)),
                ),
            )
            rows = list(cursor.fetchall())
        results: list[dict[str, object]] = []
        for row in rows:
            callable_now = (
                row["operation_kind"] == "read"
                and row["invocation_mode"] != "disabled"
                and row["address_count"] > 0
            )
            results.append(
                {
                    "interface_id": row["id"],
                    "name": row["name"],
                    "controller": row["controller_name"],
                    "controller_description": row["controller_description"],
                    "method": row["method"],
                    "path": row["path"],
                    "service": row["service_name"],
                    "route_service": row["route_service_name"],
                    "operation_kind": row["operation_kind"],
                    "callable": callable_now,
                    "address_count": row["address_count"],
                    "identity_count": row["identity_count"],
                    "request_count": row["request_count"],
                    "last_requested_at": self._iso(row["last_requested_at"]),
                }
            )
        return {
            "status": "ok",
            "environment": environment,
            "query": normalized,
            "returned_count": len(results),
            "results": results,
        }

    def prepare(
        self,
        *,
        task_id: int,
        interface_id: str,
        environment: str | None = None,
        address_id: str | None = None,
        login_account: str | None = None,
        role_name: str | None = None,
        path: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        value_strategy: ValueStrategy = "reuse_successful",
        refresh_value_keys: list[str] | None = None,
    ) -> dict[str, object]:
        if value_strategy != "refresh_selected" and refresh_value_keys:
            raise InterfaceForwardingContextError(
                "refresh_value_keys 只用于 refresh_selected 策略",
                code="invalid_refresh_value_keys",
            )
        intent: dict[str, object] = {
            "value_strategy": value_strategy,
            "refresh_value_keys": refresh_value_keys or [],
        }
        workspace_id, environment_key = self._task_scope(task_id, environment)
        with self._connect() as connection, connection.cursor() as cursor:
            interface = self._load_interface(cursor, workspace_id, interface_id)
            if interface["operation_kind"] != "read":
                return {
                    "status": "operation_not_allowed",
                    **intent,
                    "operation_kind": interface["operation_kind"],
                    "message": "MCP 首期只允许执行明确分类为只读的接口",
                }
            if interface["invocation_mode"] == "disabled" or not interface["route_service_id"]:
                return {
                    "status": "route_unavailable",
                    **intent,
                    "message": "接口服务尚未配置可调用路由",
                }
            addresses = self._addresses(
                cursor,
                workspace_id=workspace_id,
                environment=environment_key,
                route_service_id=str(interface["route_service_id"]),
                address_id=address_id,
            )
            if not addresses:
                return {
                    "status": "route_unavailable",
                    **intent,
                    "message": "当前环境没有匹配的转发地址",
                }
            if not address_id and (login_account or role_name):
                compatible_address_ids = self._address_ids_for_identity(
                    cursor,
                    address_ids=[str(item["id"]) for item in addresses],
                    login_account=login_account,
                    role_name=role_name,
                )
                addresses = [
                    item for item in addresses if str(item["id"]) in compatible_address_ids
                ]
                if not addresses:
                    return {
                        "status": "identity_unavailable",
                        **intent,
                        "message": "当前环境没有包含该登录账号和角色的转发地址",
                    }
            successful_selection = self._latest_successful_selection(
                cursor,
                interface_id=interface_id,
                environment=environment_key,
                address_ids=[str(item["id"]) for item in addresses],
                identity_ids=None,
                login_account=login_account,
                role_name=role_name,
            )
            address, address_evidence = self._choose_selection_candidate(
                addresses,
                explicit=address_id is not None,
                historic_id=(
                    str(successful_selection["address_id"])
                    if successful_selection and successful_selection["address_id"]
                    else None
                ),
                history=successful_selection,
            )
            if address is None:
                return {
                    "status": "needs_selection",
                    **intent,
                    "selection": "address",
                    "candidates": [self._public_address(item) for item in addresses],
                }
            identities = self._identities(
                cursor,
                address_id=str(address["id"]),
                login_account=login_account,
                role_name=role_name,
            )
            if (login_account or role_name) and not identities:
                return {
                    "status": "identity_unavailable",
                    **intent,
                    "message": "没有匹配的登录账号和角色",
                }
            identity: dict[str, Any] | None = None
            identity_evidence: dict[str, object] | None = None
            if identities:
                identity_history = successful_selection
                historic_identity_id = (
                    str(identity_history["identity_id"])
                    if identity_history and identity_history["identity_id"]
                    else None
                )
                if not any(str(item["id"]) == historic_identity_id for item in identities):
                    identity_history = self._latest_successful_selection(
                        cursor,
                        interface_id=interface_id,
                        environment=environment_key,
                        address_ids=[str(address["id"])],
                        identity_ids=[str(item["id"]) for item in identities],
                        login_account=login_account,
                        role_name=role_name,
                    )
                    historic_identity_id = (
                        str(identity_history["identity_id"])
                        if identity_history and identity_history["identity_id"]
                        else None
                    )
                identity, identity_evidence = self._choose_selection_candidate(
                    identities,
                    explicit=login_account is not None or role_name is not None,
                    historic_id=historic_identity_id,
                    history=identity_history,
                )
            if identities and identity is None:
                return {
                    "status": "needs_selection",
                    **intent,
                    "selection": "identity",
                    "selection_evidence": {"address": address_evidence, "identity": None},
                    "candidates": [self._public_identity(item) for item in identities],
                }
            selection_evidence = {
                "address": address_evidence,
                "identity": identity_evidence,
            }
            values: dict[str, Any] = {"path": {}, "query": {}, "body": {}}
            sources: dict[str, dict[str, str]] = {"path": {}, "query": {}, "body": {}}
            evidence: dict[str, dict[str, dict[str, object]]] = {
                "path": {},
                "query": {},
                "body": {},
            }
            history: dict[str, object] | None = None
            normalizations: list[dict[str, object]] = []
            if value_strategy != "ignore_history":
                historic, history = self._history_values(
                    cursor,
                    interface_id=interface_id,
                    environment=environment_key,
                    address_id=str(address["id"]),
                    identity_id=str(identity["id"]) if identity else None,
                )
                historic, normalizations = self._sanitize_history_values(historic)
                self._merge_values(
                    values,
                    sources,
                    evidence,
                    historic,
                    "successful_history",
                    context=history,
                )
            contract = self._normalize_contract(
                interface["request_contract"] or {},
                self._route_path(interface),
            )
            self._apply_defaults(values, sources, evidence, contract)
            value_resolutions: list[dict[str, object]] = []
            resolution_issues: list[dict[str, object]] = []
            if value_strategy != "reuse_successful":
                value_resolutions, resolution_issues = self._refresh_mapped_values(
                    task_id=task_id,
                    interface_id=interface_id,
                    strategy=value_strategy,
                    refresh_value_keys=refresh_value_keys or [],
                    values=values,
                    sources=sources,
                    evidence=evidence,
                    caller_values={"path": path or {}, "query": query or {}, "body": body or {}},
                )
            self._merge_values(
                values,
                sources,
                evidence,
                {"path": path or {}, "query": query or {}, "body": body or {}},
                "caller",
            )
            warnings = self._parameter_warnings(values, evidence)
            if resolution_issues:
                return {
                    "status": "needs_value_resolution",
                    **intent,
                    "selection_evidence": selection_evidence,
                    "value_resolutions": value_resolutions,
                    "resolution_issues": resolution_issues,
                    "request": values,
                    "sources": sources,
                    "parameter_evidence": evidence,
                    "history": history,
                    "normalizations": normalizations,
                    "warnings": warnings,
                    "request_contract": self._contract_summary(contract),
                }
            missing = self._missing_required(contract, values)
            if missing:
                return {
                    "status": "needs_parameters",
                    **intent,
                    "selection_evidence": selection_evidence,
                    "value_resolutions": value_resolutions,
                    "missing": missing,
                    "request": values,
                    "sources": sources,
                    "parameter_evidence": evidence,
                    "history": history,
                    "normalizations": normalizations,
                    "warnings": warnings,
                    "request_contract": self._contract_summary(contract),
                }
            request_bytes = len(json.dumps(values, ensure_ascii=False, default=str).encode("utf-8"))
            if request_bytes > _MAX_REQUEST_BYTES:
                return {
                    "status": "invalid_parameters",
                    **intent,
                    "selection_evidence": selection_evidence,
                    "message": "请求参数超过 256 KiB 上限",
                    "request_bytes": request_bytes,
                }
            request_payload = {
                "method": interface["method"],
                "path_template": self._route_path(interface),
                "values": values,
            }
            request_sha256 = self._hash(request_payload)
            fingerprint = self._fingerprint(interface, address, identity)
            plan_id = str(uuid4())
            expires_at = datetime.now(UTC) + _PLAN_TTL
            cursor.execute(
                """DELETE FROM interface_forwarding_request_plans
                   WHERE executed_at IS NULL
                     AND expires_at < CURRENT_TIMESTAMP - INTERVAL '1 day'"""
            )
            cursor.execute(
                """INSERT INTO interface_forwarding_request_plans
                (id, task_id, workspace_id, interface_id, environment_key, address_id,
                 identity_id, operation_kind, request_sha256, configuration_fingerprint,
                 request_payload, parameter_evidence, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    plan_id,
                    task_id,
                    workspace_id,
                    interface_id,
                    environment_key,
                    address["id"],
                    identity["id"] if identity else None,
                    interface["operation_kind"],
                    request_sha256,
                    fingerprint,
                    Jsonb(request_payload),
                    Jsonb(evidence),
                    expires_at,
                ),
            )
        return {
            "status": "ready",
            **intent,
            "selection_evidence": selection_evidence,
            "value_resolutions": value_resolutions,
            "plan_id": plan_id,
            "request_sha256": request_sha256,
            "expires_at": expires_at.isoformat(),
            "environment": environment_key,
            "interface": {
                "id": interface["id"],
                "name": interface["name"],
                "service": interface["service_name"],
                "route_service": interface["route_service_name"],
                "method": interface["method"],
                "path": interface["path"],
            },
            "address": self._public_address(address),
            "identity": self._public_identity(identity) if identity else None,
            "request": values,
            "sources": sources,
            "parameter_evidence": evidence,
            "history": history,
            "normalizations": normalizations,
            "warnings": warnings,
            "request_contract": self._contract_summary(contract),
            "injected_header_names": self._header_names(identity),
        }

    def execute(
        self,
        *,
        task_id: int,
        plan_id: str,
        request_sha256: str,
    ) -> dict[str, object]:
        workspace_id, environment = self._task_scope(task_id, None)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT plan.*, interface.name, interface.path, interface.method,
                          interface.operation_kind AS current_operation_kind,
                          source.name AS service_name, source.invocation_mode,
                          source.gateway_path_prefix, source.updated_at AS service_updated_at,
                          route.id AS route_service_id, route.name AS route_service_name,
                          interface.updated_at AS interface_updated_at,
                          address.name AS address_name, address.base_url,
                          address.updated_at AS address_updated_at,
                          identity.login_account, identity.role_name, identity.request_header,
                          identity.updated_at AS identity_updated_at,
                          workspace_environment.display_name AS workspace_environment_name
                   FROM interface_forwarding_request_plans AS plan
                   JOIN interface_forwarding_interfaces AS interface
                     ON interface.id=plan.interface_id
                   JOIN interface_forwarding_services AS source ON source.id=interface.service_id
                   LEFT JOIN interface_forwarding_services AS route
                     ON route.id=CASE WHEN source.invocation_mode='gateway'
                                      THEN source.gateway_service_id ELSE source.id END
                   JOIN interface_forwarding_environments AS address ON address.id=plan.address_id
                   LEFT JOIN interface_forwarding_identities AS identity
                     ON identity.id=plan.identity_id
                   JOIN workspace_environments AS workspace_environment
                     ON workspace_environment.workspace_id=plan.workspace_id
                    AND workspace_environment.environment_key=plan.environment_key
                   WHERE plan.id=%s AND plan.task_id=%s AND plan.workspace_id=%s""",
                (plan_id, task_id, workspace_id),
            )
            plan = cursor.fetchone()
            if not plan:
                raise InterfaceForwardingContextError("执行计划不存在", code="plan_not_found")
            if plan["environment_key"] != environment:
                raise InterfaceForwardingContextError(
                    "执行计划环境与任务环境不一致", code="environment_mismatch"
                )
            if plan["executed_at"] is not None:
                raise InterfaceForwardingContextError(
                    "执行计划已经使用", code="plan_already_executed"
                )
            if plan["expires_at"] <= datetime.now(UTC):
                raise InterfaceForwardingContextError(
                    "执行计划已过期，请重新准备", code="plan_expired"
                )
            if plan["request_sha256"] != request_sha256:
                raise InterfaceForwardingContextError(
                    "请求摘要不匹配", code="request_hash_mismatch"
                )
            if plan["operation_kind"] != "read" or plan["current_operation_kind"] != "read":
                raise InterfaceForwardingContextError(
                    "接口不再属于只读操作", code="operation_not_allowed"
                )
            if (
                self._fingerprint(plan, plan, plan if plan["identity_id"] else None)
                != plan["configuration_fingerprint"]
            ):
                raise InterfaceForwardingContextError(
                    "转发配置已变化，请重新准备", code="configuration_changed"
                )
            payload = plan["request_payload"]
            headers = self._request_headers(plan)
            url, query_values, body_values = self._materialize_request(plan["base_url"], payload)
            cursor.execute(
                """UPDATE interface_forwarding_request_plans
                   SET executed_at=CURRENT_TIMESTAMP
                   WHERE id=%s AND executed_at IS NULL
                   RETURNING executed_at""",
                (plan_id,),
            )
            if not cursor.fetchone():
                raise InterfaceForwardingContextError(
                    "执行计划已经使用", code="plan_already_executed"
                )
            host_job_id: str | None = None
            if self._host_runner_ready() and str(payload["method"]).upper() in {"GET", "POST"}:
                host_job_id = str(uuid4())
                cursor.execute(
                    """INSERT INTO interface_forwarding_host_jobs (id, plan_id)
                       VALUES (%s, %s)""",
                    (host_job_id, plan_id),
                )

        if host_job_id:
            result = self._await_host_job(host_job_id)
            execution_mode = "host_runner"
        else:
            result = self._execute_direct(
                method=str(payload["method"]),
                url=url,
                headers=headers,
                query_values=query_values,
                body_values=body_values,
            )
            execution_mode = "direct"
        status_code = result["status_code"]
        response_bytes = result["response_bytes"]
        response_truncated = result["response_truncated"]
        response_body = result["response_body"]
        response_headers = result["response_headers"]
        error_type = result["error_type"]
        duration_ms = result["duration_ms"]
        success = self._response_success(status_code, response_body)
        log_id = str(uuid4())
        log_request = json.dumps(
            payload.get("values", {}), ensure_ascii=False, separators=(",", ":")
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO interface_forwarding_logs
                (id, workspace_id, interface_id, environment_name, identity_name,
                 identity_role, request_url, request_body, response_body, status_code,
                 success, duration_ms, task_id, tool_call_id, plan_id, environment_key,
                 address_id, identity_id, request_sha256, response_bytes, response_truncated)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    log_id,
                    workspace_id,
                    plan["interface_id"],
                    f"{plan['workspace_environment_name']} · {plan['address_name']}",
                    plan["login_account"],
                    plan["role_name"] or "",
                    url,
                    log_request,
                    response_body,
                    status_code,
                    success,
                    duration_ms,
                    task_id,
                    current_tool_call_id(),
                    plan_id,
                    environment,
                    plan["address_id"],
                    plan["identity_id"],
                    request_sha256,
                    response_bytes,
                    response_truncated,
                ),
            )
            if host_job_id:
                cursor.execute(
                    "DELETE FROM interface_forwarding_host_jobs WHERE id=%s",
                    (host_job_id,),
                )
        return {
            "status": "completed" if error_type is None else "request_failed",
            "execution_mode": execution_mode,
            "execution_id": log_id,
            "success": success,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "response_body": response_body,
            "response_headers": response_headers,
            "response_bytes": response_bytes,
            "truncated": response_truncated,
            "error_type": error_type,
        }

    def _execute_direct(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        query_values: dict[str, Any],
        body_values: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        status_code: int | None = None
        response_bytes = 0
        response_truncated = False
        response_body = ""
        response_headers: dict[str, str] = {}
        error_type: str | None = None
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                with client.stream(
                    method,
                    url,
                    headers=headers,
                    params=query_values or None,
                    json=(
                        body_values or None
                        if method.upper() not in {"GET", "HEAD"}
                        else None
                    ),
                ) as response:
                    status_code = response.status_code
                    response_headers = {
                        key: value
                        for key, value in response.headers.items()
                        if key.lower() in _SAFE_RESPONSE_HEADERS
                    }
                    chunks: list[bytes] = []
                    retained = 0
                    for chunk in response.iter_bytes():
                        response_bytes += len(chunk)
                        if retained < _MAX_RESPONSE_BYTES:
                            piece = chunk[: _MAX_RESPONSE_BYTES - retained]
                            chunks.append(piece)
                            retained += len(piece)
                        if response_bytes > _MAX_RESPONSE_BYTES:
                            response_truncated = True
                            break
                    response_body = b"".join(chunks).decode("utf-8", errors="replace")
        except httpx.HTTPError as exc:
            error_type = exc.__class__.__name__
            response_body = f"请求失败：{error_type}"
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        return {
            "status_code": status_code,
            "duration_ms": duration_ms,
            "response_body": response_body,
            "response_headers": response_headers,
            "response_bytes": response_bytes,
            "response_truncated": response_truncated,
            "error_type": error_type,
        }

    def _host_runner_ready(self) -> bool:
        if self._host_runner_available is None:
            return False
        try:
            return self._host_runner_available()
        except Exception:
            return False

    def _await_host_job(self, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._host_execution_timeout_seconds
        while time.monotonic() < deadline:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """SELECT status, status_code, response_body, response_headers,
                              response_bytes, response_truncated, error_type, duration_ms
                       FROM interface_forwarding_host_jobs WHERE id=%s""",
                    (job_id,),
                )
                row = cursor.fetchone()
            if not row:
                raise InterfaceForwardingContextError(
                    "宿主机转发任务不存在", code="host_job_not_found"
                )
            if row["status"] in {"completed", "failed"}:
                return dict(row)
            time.sleep(0.1)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE interface_forwarding_host_jobs
                   SET status='failed', error_type='HostRunnerTimeout',
                       completed_at=CURRENT_TIMESTAMP
                   WHERE id=%s AND status IN ('queued', 'leased')""",
                (job_id,),
            )
            cursor.execute(
                """SELECT status, status_code, response_body, response_headers,
                          response_bytes, response_truncated, error_type, duration_ms
                   FROM interface_forwarding_host_jobs WHERE id=%s""",
                (job_id,),
            )
            row = cursor.fetchone()
        if not row:
            raise InterfaceForwardingContextError(
                "宿主机转发任务不存在", code="host_job_not_found"
            )
        return dict(row)

    def lease_host_job(
        self, *, runner_id: str, lease_seconds: int
    ) -> dict[str, object] | None:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE interface_forwarding_host_jobs
                   SET status='failed', error_type='HostRunnerLeaseExpired',
                       completed_at=CURRENT_TIMESTAMP
                   WHERE status='leased' AND lease_expires_at < CURRENT_TIMESTAMP"""
            )
            cursor.execute(
                """SELECT id, plan_id FROM interface_forwarding_host_jobs
                   WHERE status='queued' ORDER BY created_at, id
                   FOR UPDATE SKIP LOCKED LIMIT 1"""
            )
            job = cursor.fetchone()
            if not job:
                return None
            cursor.execute(
                """SELECT plan.*, interface.name, interface.path, interface.method,
                          interface.operation_kind AS current_operation_kind,
                          source.name AS service_name, source.invocation_mode,
                          source.gateway_path_prefix, source.updated_at AS service_updated_at,
                          route.id AS route_service_id, route.name AS route_service_name,
                          interface.updated_at AS interface_updated_at,
                          address.name AS address_name, address.base_url,
                          address.updated_at AS address_updated_at,
                          identity.login_account, identity.role_name, identity.request_header,
                          identity.updated_at AS identity_updated_at
                   FROM interface_forwarding_request_plans AS plan
                   JOIN interface_forwarding_interfaces AS interface
                     ON interface.id=plan.interface_id
                   JOIN interface_forwarding_services AS source ON source.id=interface.service_id
                   LEFT JOIN interface_forwarding_services AS route
                     ON route.id=CASE WHEN source.invocation_mode='gateway'
                                      THEN source.gateway_service_id ELSE source.id END
                   JOIN interface_forwarding_environments AS address ON address.id=plan.address_id
                   LEFT JOIN interface_forwarding_identities AS identity
                     ON identity.id=plan.identity_id
                   WHERE plan.id=%s""",
                (job["plan_id"],),
            )
            plan = cursor.fetchone()
            invalid = (
                not plan
                or plan["operation_kind"] != "read"
                or plan["current_operation_kind"] != "read"
                or plan["expires_at"] <= datetime.now(UTC)
                or self._fingerprint(plan, plan, plan if plan["identity_id"] else None)
                != plan["configuration_fingerprint"]
            )
            if invalid:
                cursor.execute(
                    """UPDATE interface_forwarding_host_jobs
                       SET status='failed', error_type='HostRunnerPlanInvalid',
                           completed_at=CURRENT_TIMESTAMP WHERE id=%s""",
                    (job["id"],),
                )
                return None
            payload = plan["request_payload"]
            url, query_values, body_values = self._materialize_request(
                plan["base_url"], payload
            )
            headers = self._request_headers(plan)
            cursor.execute(
                """UPDATE interface_forwarding_host_jobs
                   SET status='leased', runner_id=%s, lease_token_hash=%s,
                       leased_at=CURRENT_TIMESTAMP,
                       lease_expires_at=CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')
                   WHERE id=%s AND status='queued'""",
                (runner_id, token_hash, max(45, lease_seconds), job["id"]),
            )
        return {
            "job_id": job["id"],
            "lease_token": token,
            "request": {
                "method": str(payload["method"]).upper(),
                "url": url,
                "headers": headers,
                "query": query_values,
                "body": body_values,
                "timeout_seconds": 30,
                "max_response_bytes": _MAX_RESPONSE_BYTES,
            },
        }

    def complete_host_job(
        self,
        *,
        job_id: str,
        runner_id: str,
        lease_token: str,
        status_code: int | None,
        response_body: str,
        response_headers: dict[str, str],
        response_bytes: int,
        response_truncated: bool,
        error_type: str | None,
        duration_ms: int,
    ) -> None:
        encoded = response_body.encode("utf-8")
        if len(encoded) > _MAX_RESPONSE_BYTES:
            encoded = encoded[:_MAX_RESPONSE_BYTES]
            response_body = encoded.decode("utf-8", errors="replace")
            response_truncated = True
        safe_headers = {
            key.lower(): value
            for key, value in response_headers.items()
            if key.lower() in _SAFE_RESPONSE_HEADERS
        }
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT status, runner_id, lease_token_hash
                   FROM interface_forwarding_host_jobs WHERE id=%s FOR UPDATE""",
                (job_id,),
            )
            job = cursor.fetchone()
            supplied_hash = hashlib.sha256(lease_token.encode()).hexdigest()
            if (
                not job
                or job["status"] != "leased"
                or job["runner_id"] != runner_id
                or not job["lease_token_hash"]
                or not hmac.compare_digest(job["lease_token_hash"], supplied_hash)
            ):
                raise InterfaceForwardingContextError(
                    "宿主机转发租约无效", code="host_job_lease_invalid"
                )
            cursor.execute(
                """UPDATE interface_forwarding_host_jobs
                   SET status=%s, status_code=%s, response_body=%s,
                       response_headers=%s, response_bytes=%s,
                       response_truncated=%s, error_type=%s, duration_ms=%s,
                       completed_at=CURRENT_TIMESTAMP
                   WHERE id=%s""",
                (
                    "failed" if error_type else "completed",
                    status_code,
                    response_body,
                    Jsonb(safe_headers),
                    max(0, response_bytes),
                    response_truncated,
                    error_type,
                    max(0, duration_ms),
                    job_id,
                ),
            )

    def _connect(self):
        if not self._database_url:
            raise InterfaceForwardingContextError(
                "控制面数据库尚未配置", code="database_unavailable"
            )
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def _task_scope(self, task_id: int, explicit_environment: str | None) -> tuple[str, str]:
        try:
            task = self._tasks.get_task(task_id)
        except TaskRepositoryError as exc:
            raise InterfaceForwardingContextError(
                "任务不存在，请重新 prepare", code="task_not_found"
            ) from exc
        if task.scope != "workspace" or not task.workspace_id:
            raise InterfaceForwardingContextError(
                "接口转发需要工作空间任务", code="workspace_task_required"
            )
        task_environment = task.database_environment or "local"
        if explicit_environment is not None and explicit_environment != task_environment:
            raise InterfaceForwardingContextError(
                "显式环境必须与 prepare_task_context 绑定的任务环境一致",
                code="environment_mismatch",
            )
        try:
            if not self._environments.has_environment(task.workspace_id, task_environment):
                raise InterfaceForwardingContextError(
                    "任务环境已不存在，请重新 prepare", code="environment_unavailable"
                )
            if task.database_environment_revision is not None:
                revision = self._environments.get_environment_snapshot(
                    task.workspace_id
                ).config.revision
                if revision != task.database_environment_revision:
                    raise InterfaceForwardingContextError(
                        "环境配置已变化，请重新 prepare", code="environment_changed"
                    )
        except DatabaseEnvironmentRepositoryError as exc:
            raise InterfaceForwardingContextError(
                "无法读取工作空间环境", code="environment_unavailable"
            ) from exc
        return task.workspace_id, task_environment

    @staticmethod
    def _load_interface(cursor: Any, workspace_id: str, interface_id: str) -> dict[str, Any]:
        cursor.execute(
            """SELECT interface.*, source.name AS service_name, source.invocation_mode,
                      source.gateway_path_prefix, source.updated_at AS service_updated_at,
                      route.id AS route_service_id, route.name AS route_service_name
               FROM interface_forwarding_interfaces AS interface
               JOIN interface_forwarding_services AS source ON source.id=interface.service_id
               LEFT JOIN interface_forwarding_services AS route
                 ON route.id=CASE WHEN source.invocation_mode='gateway'
                                  THEN source.gateway_service_id ELSE source.id END
               WHERE interface.id=%s AND interface.workspace_id=%s""",
            (interface_id, workspace_id),
        )
        row = cursor.fetchone()
        if not row:
            raise InterfaceForwardingContextError("接口不存在", code="interface_not_found")
        return row

    @staticmethod
    def _addresses(
        cursor: Any,
        *,
        workspace_id: str,
        environment: str,
        route_service_id: str,
        address_id: str | None,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """SELECT id, name, base_url, service_id, updated_at
               FROM interface_forwarding_environments
               WHERE workspace_id=%s AND environment_key=%s AND service_id=%s
                 AND (%s::text IS NULL OR id=%s)
               ORDER BY lower(name), id""",
            (workspace_id, environment, route_service_id, address_id, address_id),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _identities(
        cursor: Any, *, address_id: str, login_account: str | None, role_name: str | None
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """SELECT id, login_account, role_name, request_header, updated_at
               FROM interface_forwarding_identities
               WHERE environment_id=%s
                 AND (%s::text IS NULL OR lower(login_account)=lower(%s))
                 AND (%s::text IS NULL OR lower(role_name)=lower(%s))
               ORDER BY lower(login_account), lower(role_name), id""",
            (address_id, login_account, login_account, role_name, role_name),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _address_ids_for_identity(
        cursor: Any,
        *,
        address_ids: list[str],
        login_account: str | None,
        role_name: str | None,
    ) -> set[str]:
        if not address_ids:
            return set()
        cursor.execute(
            """SELECT DISTINCT environment_id
               FROM interface_forwarding_identities
               WHERE environment_id::text = ANY(%s)
                 AND (%s::text IS NULL OR lower(login_account)=lower(%s))
                 AND (%s::text IS NULL OR lower(role_name)=lower(%s))""",
            (address_ids, login_account, login_account, role_name, role_name),
        )
        return {str(row["environment_id"]) for row in cursor.fetchall()}

    @staticmethod
    def _latest_successful_selection(
        cursor: Any,
        *,
        interface_id: str,
        environment: str,
        address_ids: list[str],
        identity_ids: list[str] | None,
        login_account: str | None,
        role_name: str | None,
    ) -> dict[str, Any] | None:
        if not address_ids:
            return None
        cursor.execute(
            """SELECT log.id AS log_id, log.address_id, log.identity_id,
                      log.created_at, log.status_code
               FROM interface_forwarding_logs AS log
               JOIN interface_forwarding_environments AS address
                 ON address.id=log.address_id
               LEFT JOIN interface_forwarding_identities AS identity
                 ON identity.id=log.identity_id
                AND identity.environment_id=address.id
               WHERE log.interface_id=%s AND log.success=true
                 AND log.environment_key=%s
                 AND address.id::text = ANY(%s)
                 AND (%s::text[] IS NULL OR identity.id::text = ANY(%s))
                 AND (%s::text IS NULL OR lower(identity.login_account)=lower(%s))
                 AND (%s::text IS NULL OR lower(identity.role_name)=lower(%s))
               ORDER BY log.created_at DESC, log.id DESC
               LIMIT 1""",
            (
                interface_id,
                environment,
                address_ids,
                identity_ids,
                identity_ids,
                login_account,
                login_account,
                role_name,
                role_name,
            ),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @classmethod
    def _choose_selection_candidate(
        cls,
        candidates: list[dict[str, Any]],
        *,
        explicit: bool,
        historic_id: str | None,
        history: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, dict[str, object] | None]:
        if len(candidates) == 1:
            return candidates[0], {"source": "caller" if explicit else "single_candidate"}
        if historic_id:
            candidate = next(
                (item for item in candidates if str(item["id"]) == historic_id),
                None,
            )
            if candidate is not None:
                evidence: dict[str, object] = {"source": "successful_history"}
                if history:
                    evidence.update(
                        {
                            "log_id": str(history["log_id"]),
                            "created_at": cls._iso(history["created_at"]),
                            "status_code": history["status_code"],
                        }
                    )
                return candidate, evidence
        return None, None

    def _refresh_mapped_values(
        self,
        *,
        task_id: int,
        interface_id: str,
        strategy: ValueStrategy,
        refresh_value_keys: list[str],
        values: dict[str, Any],
        sources: dict[str, dict[str, str]],
        evidence: dict[str, dict[str, dict[str, object]]],
        caller_values: dict[str, Any],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        requested_keys = list(dict.fromkeys(item.strip().casefold() for item in refresh_value_keys))
        if strategy == "refresh_selected" and not requested_keys:
            return [], [
                {
                    "code": "refresh_value_keys_required",
                    "message": "refresh_selected 必须指定至少一个 refresh_value_keys",
                }
            ]
        if self._value_mappings is None:
            return [], [
                {
                    "code": "value_mapping_disabled",
                    "message": "业务值映射服务当前不可用",
                }
            ]
        try:
            search_result = self._value_mappings.search_for_task(
                task_id=task_id,
                query=None,
                interface_id=interface_id,
                location=None,
                parameter_path=None,
                limit=20,
            )
        except ValueMappingError as exc:
            return [], [{"code": exc.code, "message": str(exc)}]

        raw_mappings = search_result.get("mappings", [])
        mappings = [item for item in raw_mappings if isinstance(item, dict)]
        available_keys = {
            str(item.get("value_key") or "").casefold(): item
            for item in mappings
            if item.get("value_key")
        }
        if strategy == "refresh_selected":
            missing_keys = [key for key in requested_keys if key not in available_keys]
            if missing_keys:
                return [], [
                    {
                        "code": "value_mapping_unavailable",
                        "message": "指定业务值没有绑定到当前接口",
                        "value_keys": missing_keys,
                        "available_value_keys": sorted(available_keys),
                    }
                ]
            selected_mappings = [available_keys[key] for key in requested_keys]
        else:
            selected_mappings = list(available_keys.values())

        resolutions: list[dict[str, object]] = []
        issues: list[dict[str, object]] = []
        for mapping in selected_mappings:
            value_key = str(mapping["value_key"])
            mapping_id = str(mapping["mapping_id"])
            bindings = [
                item
                for item in mapping.get("bindings", [])
                if isinstance(item, dict)
                and item.get("location") in {"path", "query", "body"}
                and isinstance(item.get("parameter_path"), str)
            ]
            refresh_bindings: list[dict[str, Any]] = []
            caller_bindings: list[dict[str, str]] = []
            previous_values: list[object] = []
            for binding in bindings:
                location = str(binding["location"])
                parameter_path = str(binding["parameter_path"])
                if self._path_exists(caller_values.get(location, {}), parameter_path):
                    caller_bindings.append(
                        {"location": location, "parameter_path": parameter_path}
                    )
                    continue
                exists, previous = self._path_value(values.get(location, {}), parameter_path)
                if exists and previous not in (None, ""):
                    previous_values.append(previous)
                self._remove_path_value(values.get(location, {}), parameter_path)
                sources[location].pop(parameter_path, None)
                evidence[location].pop(parameter_path, None)
                refresh_bindings.append(binding)

            if not refresh_bindings:
                resolutions.append(
                    {
                        "mapping_id": mapping_id,
                        "value_key": value_key,
                        "status": "caller_override",
                        "fields": caller_bindings,
                    }
                )
                continue
            if any("[]" in str(item["parameter_path"]) for item in refresh_bindings):
                issues.append(
                    {
                        "code": "unsupported_mapping_path",
                        "mapping_id": mapping_id,
                        "value_key": value_key,
                        "message": "自动刷新暂不支持数组参数路径",
                    }
                )
                continue
            try:
                result = self._value_mappings.resolve_for_task(
                    mapping_id,
                    task_id=task_id,
                    environment=None,
                    keyword="",
                    limit=10,
                )
            except ValueMappingError as exc:
                issues.append(
                    {
                        "code": exc.code,
                        "mapping_id": mapping_id,
                        "value_key": value_key,
                        "message": str(exc),
                    }
                )
                continue
            candidates = [
                item
                for item in result.get("candidates", [])
                if isinstance(item, dict) and item.get("value") not in (None, "")
            ]
            selected = next(
                (
                    item
                    for item in candidates
                    if all(item.get("value") != previous for previous in previous_values)
                ),
                None,
            )
            if selected is None:
                issues.append(
                    {
                        "code": (
                            "no_alternative_candidate"
                            if candidates and previous_values
                            else "value_candidate_not_found"
                        ),
                        "mapping_id": mapping_id,
                        "value_key": value_key,
                        "message": (
                            "没有找到不同于成功历史的候选值"
                            if candidates and previous_values
                            else "当前映射没有查到可用候选值"
                        ),
                    }
                )
                continue

            selected_value = selected["value"]
            field_summaries: list[dict[str, str]] = []
            for binding in refresh_bindings:
                location = str(binding["location"])
                parameter_path = str(binding["parameter_path"])
                self._set_path_value(values[location], parameter_path, selected_value)
                sources[location][parameter_path] = "value_mapping"
                evidence[location][parameter_path] = {
                    "source": "value_mapping",
                    "confidence": "high",
                    "action": "refreshed",
                    "evidence": {
                        "mapping_id": mapping_id,
                        "value_key": value_key,
                        "selection": "first_deterministic_candidate",
                        "previous_value_excluded": bool(previous_values),
                    },
                }
                field_summaries.append(
                    {"location": location, "parameter_path": parameter_path}
                )
            resolutions.append(
                {
                    "mapping_id": mapping_id,
                    "value_key": value_key,
                    "status": "refreshed",
                    "fields": field_summaries,
                    "candidate_count": len(candidates),
                    "previous_value_excluded": bool(previous_values),
                }
            )
        return resolutions, issues

    @classmethod
    def _path_exists(cls, values: object, parameter_path: str) -> bool:
        return cls._path_value(values, parameter_path)[0]

    @staticmethod
    def _path_value(values: object, parameter_path: str) -> tuple[bool, object]:
        current = values
        for part in parameter_path.split("."):
            if not isinstance(current, dict) or part not in current:
                return False, None
            current = current[part]
        return True, current

    @staticmethod
    def _set_path_value(values: dict[str, Any], parameter_path: str, value: object) -> None:
        parts = parameter_path.split(".")
        current = values
        for part in parts[:-1]:
            nested = current.get(part)
            if not isinstance(nested, dict):
                nested = {}
                current[part] = nested
            current = nested
        current[parts[-1]] = value

    @staticmethod
    def _remove_path_value(values: object, parameter_path: str) -> None:
        if not isinstance(values, dict):
            return
        parts = parameter_path.split(".")
        current = values
        for part in parts[:-1]:
            nested = current.get(part)
            if not isinstance(nested, dict):
                return
            current = nested
        current.pop(parts[-1], None)

    @staticmethod
    def _history_values(
        cursor: Any,
        *,
        interface_id: str,
        environment: str,
        address_id: str,
        identity_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, object] | None]:
        cursor.execute(
            """SELECT id, request_body, created_at, status_code
               FROM interface_forwarding_logs
               WHERE interface_id=%s AND success=true
                 AND (environment_key=%s OR environment_key IS NULL)
                 AND (address_id=%s OR address_id IS NULL)
                 AND identity_id::text IS NOT DISTINCT FROM %s::text
               ORDER BY created_at DESC LIMIT 1""",
            (interface_id, environment, address_id, identity_id),
        )
        row = cursor.fetchone()
        if not row:
            return {}, None
        try:
            parsed = json.loads(row["request_body"])
        except (TypeError, json.JSONDecodeError):
            return {}, None
        if not isinstance(parsed, dict):
            return {}, None
        history = {
            "log_id": str(row["id"]),
            "created_at": InterfaceForwardingContextService._iso(row["created_at"]),
            "status_code": row["status_code"],
            "selection": "latest_success_same_environment_address_identity",
        }
        if any(key in parsed for key in ("path", "query", "body")):
            return parsed, history
        return {"body": parsed}, history

    @staticmethod
    def _merge_values(
        target: dict[str, Any],
        sources: dict[str, dict[str, str]],
        evidence: dict[str, dict[str, dict[str, object]]],
        incoming: dict[str, Any],
        source: str,
        *,
        context: dict[str, object] | None = None,
    ) -> None:
        confidence = {
            "caller": "high",
            "successful_history": "medium",
        }.get(source, "low")
        for location in ("path", "query", "body"):
            values = incoming.get(location, {})
            if not isinstance(values, dict):
                continue
            target[location].update(values)
            sources[location].update({str(key): source for key in values})
            for key in values:
                item: dict[str, object] = {
                    "source": source,
                    "confidence": confidence,
                }
                if context:
                    item["evidence"] = context
                evidence[location][str(key)] = item

    @staticmethod
    def _apply_defaults(
        values: dict[str, Any],
        sources: dict[str, dict[str, str]],
        evidence: dict[str, dict[str, dict[str, object]]],
        contract: dict[str, Any],
    ) -> None:
        for location in ("path", "query", "body"):
            schema = contract.get(location, {})
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            if not isinstance(properties, dict):
                continue
            for name, field in properties.items():
                if name in values[location] or not isinstance(field, dict):
                    continue
                if "default" in field:
                    values[location][name] = field["default"]
                    sources[location][name] = "schema_default"
                    evidence[location][name] = {
                        "source": "schema_default",
                        "confidence": "high",
                    }
                elif "example" in field:
                    values[location][name] = field["example"]
                    sources[location][name] = "schema_example"
                    evidence[location][name] = {
                        "source": "schema_example",
                        "confidence": "low",
                    }
                elif name in {"pageNumber", "pageNum", "page"}:
                    values[location][name] = 1
                    sources[location][name] = "safe_pagination_default"
                    evidence[location][name] = {
                        "source": "safe_pagination_default",
                        "confidence": "high",
                    }
                elif name in {"pageSize", "size", "limit"}:
                    values[location][name] = 10
                    sources[location][name] = "safe_pagination_default"
                    evidence[location][name] = {
                        "source": "safe_pagination_default",
                        "confidence": "high",
                    }

    @classmethod
    def _sanitize_history_values(
        cls, incoming: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, object]]]:
        sanitized: dict[str, Any] = {}
        changes: list[dict[str, object]] = []
        for location in ("path", "query", "body"):
            raw_values = incoming.get(location, {})
            if not isinstance(raw_values, dict):
                continue
            values = cls._strip_volatile_history_values(
                raw_values,
                location=location,
                path=(),
                changes=changes,
            )
            for key, value in list(values.items()):
                normalized = cls._normalized_parameter_name(str(key))
                if normalized in _PAGE_NUMBER_KEYS and isinstance(value, (int, float)):
                    if value != 1:
                        changes.append(
                            {
                                "location": location,
                                "parameter": str(key),
                                "action": "reset_page_number",
                            }
                        )
                    values[key] = 1
                elif normalized in _PAGE_SIZE_KEYS:
                    safe_size = (
                        value
                        if isinstance(value, int) and not isinstance(value, bool)
                        else 10
                    )
                    safe_size = max(1, min(safe_size, 20))
                    if safe_size != value:
                        changes.append(
                            {
                                "location": location,
                                "parameter": str(key),
                                "action": "clamp_page_size",
                                "maximum": 20,
                            }
                        )
                    values[key] = safe_size
            sanitized[location] = values
        return sanitized, changes

    @classmethod
    def _strip_volatile_history_values(
        cls,
        incoming: dict[str, Any],
        *,
        location: str,
        path: tuple[str, ...],
        changes: list[dict[str, object]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for raw_key, raw_value in incoming.items():
            key = str(raw_key)
            current_path = (*path, key)
            if cls._normalized_parameter_name(key) in _VOLATILE_HISTORY_KEYS:
                changes.append(
                    {
                        "location": location,
                        "parameter": ".".join(current_path),
                        "action": "remove_volatile_history_value",
                    }
                )
                continue
            if isinstance(raw_value, dict):
                result[key] = cls._strip_volatile_history_values(
                    raw_value,
                    location=location,
                    path=current_path,
                    changes=changes,
                )
            elif isinstance(raw_value, list):
                result[key] = [
                    cls._strip_volatile_history_values(
                        item,
                        location=location,
                        path=(*current_path, str(index)),
                        changes=changes,
                    )
                    if isinstance(item, dict)
                    else item
                    for index, item in enumerate(raw_value)
                ]
            else:
                result[key] = raw_value
        return result

    @staticmethod
    def _normalized_parameter_name(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.casefold())

    @classmethod
    def _parameter_warnings(
        cls,
        values: dict[str, Any],
        evidence: dict[str, dict[str, dict[str, object]]],
    ) -> list[dict[str, object]]:
        unchecked_ids: list[dict[str, str]] = []
        for location in ("path", "query", "body"):
            location_values = values.get(location, {})
            if not isinstance(location_values, dict):
                continue
            for name, value in location_values.items():
                normalized = cls._normalized_parameter_name(str(name))
                if not normalized.endswith("id") or value in (None, ""):
                    continue
                item = evidence[location].get(str(name))
                if not item or item.get("source") != "successful_history":
                    continue
                item["database_validation"] = "not_checked"
                unchecked_ids.append({"location": location, "name": str(name)})
        if not unchecked_ids:
            return []
        return [
            {
                "code": "historical_id_not_database_validated",
                "message": (
                    "历史 ID 尚未绑定明确的数据表字段；需要当前数据时先用数据库工具验证，"
                    "再作为 caller 参数重新 prepare。"
                ),
                "fields": unchecked_ids,
            }
        ]

    @staticmethod
    def _missing_required(contract: dict[str, Any], values: dict[str, Any]) -> list[dict[str, str]]:
        missing: list[dict[str, str]] = []
        for location in ("path", "query", "body"):
            schema = contract.get(location, {})
            required = schema.get("required", []) if isinstance(schema, dict) else []
            for name in required if isinstance(required, list) else []:
                if name not in values[location] or values[location][name] in (None, ""):
                    missing.append({"location": location, "name": str(name)})
        return missing

    @staticmethod
    def _normalize_contract(contract: dict[str, Any], path_template: str) -> dict[str, Any]:
        normalized = dict(contract)
        path_schema = dict(normalized.get("path") or {})
        properties = dict(path_schema.get("properties") or {})
        required = list(path_schema.get("required") or [])
        for name in _PATH_PARAMETER.findall(path_template):
            properties.setdefault(name, {"type": "string"})
            if name not in required:
                required.append(name)
        path_schema.update({"type": "object", "properties": properties})
        if required:
            path_schema["required"] = required
        normalized["path"] = path_schema
        for location in ("query", "body"):
            normalized.setdefault(location, {"type": "object", "properties": {}})
        return normalized

    @staticmethod
    def _contract_summary(contract: dict[str, Any]) -> dict[str, object]:
        result: dict[str, object] = {}
        total_fields = 0
        truncated = False
        for location in ("path", "query", "body"):
            schema = contract.get(location, {})
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            required = set(schema.get("required", [])) if isinstance(schema, dict) else set()
            fields: list[dict[str, object]] = []
            if isinstance(properties, dict):
                for name, raw_field in properties.items():
                    if total_fields >= 200:
                        truncated = True
                        break
                    field = raw_field if isinstance(raw_field, dict) else {}
                    summary: dict[str, object] = {
                        "name": str(name),
                        "type": str(field.get("type") or "unknown"),
                        "required": name in required,
                    }
                    description = field.get("description")
                    if isinstance(description, str) and description:
                        summary["description"] = description[:240]
                    for key in ("default", "example"):
                        if key in field:
                            encoded = json.dumps(
                                field[key], ensure_ascii=False, default=str
                            ).encode("utf-8")
                            if len(encoded) <= 2_048:
                                summary[key] = field[key]
                    enum = field.get("enum")
                    if isinstance(enum, list):
                        summary["enum"] = enum[:20]
                    fields.append(summary)
                    total_fields += 1
            result[location] = fields
        result["truncated"] = truncated
        return result

    @staticmethod
    def _response_success(status_code: int | None, response_body: str) -> bool:
        if status_code is None or not 200 <= status_code < 300:
            return False
        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError:
            return True
        if not isinstance(payload, dict):
            return True
        if payload.get("success") is False:
            return False
        code = payload.get("code")
        if code is not None and str(code).lower() not in {"0", "200", "success", "ok"}:
            return False
        return True

    @staticmethod
    def _route_path(interface: dict[str, Any]) -> str:
        prefix = str(interface.get("gateway_path_prefix") or "").strip("/")
        path = str(interface["path"]).lstrip("/")
        return f"/{prefix}/{path}" if prefix else f"/{path}"

    @staticmethod
    def _materialize_request(
        base_url: str, payload: dict[str, Any]
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        values = payload.get("values", {})
        path_values = values.get("path", {}) if isinstance(values, dict) else {}
        route_path = str(payload["path_template"])
        for name in _PATH_PARAMETER.findall(route_path):
            if name not in path_values:
                raise InterfaceForwardingContextError(
                    f"缺少路径参数 {name}", code="missing_path_parameter"
                )
            route_path = route_path.replace(
                "{" + name + "}", quote(str(path_values[name]), safe="")
            )
        base = base_url.rstrip("/") + "/"
        url = urljoin(base, route_path.lstrip("/"))
        base_parts, url_parts = urlsplit(base), urlsplit(url)
        if (base_parts.scheme, base_parts.netloc) != (url_parts.scheme, url_parts.netloc):
            raise InterfaceForwardingContextError(
                "生成的请求地址越过转发地址边界", code="unsafe_request_url"
            )
        query_values = values.get("query", {}) if isinstance(values, dict) else {}
        body_values = values.get("body", {}) if isinstance(values, dict) else {}
        return url, query_values, body_values

    @staticmethod
    def _request_headers(identity: dict[str, Any]) -> dict[str, str]:
        headers: dict[str, str] = {}
        raw = str(identity.get("request_header") or "").strip()
        if not raw:
            return {"Accept": "application/json"}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            headers["Authorization"] = raw
            return headers
        if not isinstance(parsed, dict):
            raise InterfaceForwardingContextError(
                "账号请求头配置不是 JSON 对象", code="invalid_identity_header"
            )
        for key, value in parsed.items():
            name = str(key).strip()
            header_value = str(value)
            if name.lower() in _FORBIDDEN_REQUEST_HEADERS:
                continue
            if "\r" in name or "\n" in name or "\r" in header_value or "\n" in header_value:
                raise InterfaceForwardingContextError(
                    "账号请求头包含非法换行", code="invalid_identity_header"
                )
            headers[name] = header_value
        if not any(name.lower() == "accept" for name in headers):
            headers["Accept"] = "application/json"
        return headers

    @staticmethod
    def _header_names(identity: dict[str, Any] | None) -> list[str]:
        if not identity:
            return ["Accept"]
        try:
            parsed = json.loads(str(identity.get("request_header") or "{}"))
        except json.JSONDecodeError:
            return ["Accept", "Authorization"]
        names = (
            [
                str(name).lower()
                for name in parsed
                if str(name).lower() not in _FORBIDDEN_REQUEST_HEADERS
            ]
            if isinstance(parsed, dict)
            else []
        )
        return sorted(set(["accept", *names]))

    @staticmethod
    def _fingerprint(
        interface: dict[str, Any], address: dict[str, Any], identity: dict[str, Any] | None
    ) -> str:
        data = {
            "interface_id": interface.get("interface_id") or interface.get("id"),
            "interface_updated_at": str(
                interface.get("updated_at") or interface.get("interface_updated_at")
            ),
            "service_updated_at": str(interface.get("service_updated_at")),
            "route_service_id": interface.get("route_service_id"),
            "address_id": address.get("address_id") or address.get("id"),
            "address_updated_at": str(
                address.get("updated_at") or address.get("address_updated_at")
            ),
            "identity_id": (identity.get("identity_id") or identity.get("id"))
            if identity
            else None,
            "identity_updated_at": str(
                identity.get("updated_at") or identity.get("identity_updated_at")
            )
            if identity
            else None,
            "identity_header_sha256": hashlib.sha256(
                str(identity.get("request_header") or "").encode()
            ).hexdigest()
            if identity
            else None,
        }
        return InterfaceForwardingContextService._hash(data)

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()

    @staticmethod
    def _public_address(row: dict[str, Any]) -> dict[str, object]:
        return {"id": row["id"], "name": row["name"], "base_url": row["base_url"]}

    @staticmethod
    def _public_identity(row: dict[str, Any]) -> dict[str, object]:
        return {
            "id": row["id"],
            "login_account": row["login_account"],
            "role_name": row["role_name"],
        }

    @staticmethod
    def _iso(value: Any) -> str | None:
        return value.isoformat() if isinstance(value, datetime) else None
