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
from context_router.services.interface_intent_matching import InterfaceIntentMatcher
from context_router.services.interface_response_validation import InterfaceResponseValidator
from context_router.services.mcp_trace import current_tool_call_id
from context_router.services.value_mapping import ValueMappingError, ValueMappingService

OperationKind = Literal["read", "write", "destructive", "unknown"]
_EXECUTABLE_OPERATION_KINDS = frozenset({"read", "write", "destructive", "unknown"})
_HOST_RUNNER_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
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
        host_job_poll_interval_seconds: float = 0.25,
    ) -> None:
        self._database_url = database_url
        self._tasks = task_repository
        self._environments = database_environment_repository
        self._value_mappings = value_mapping_service
        self._host_runner_available = host_runner_available
        self._host_execution_timeout_seconds = max(5.0, host_execution_timeout_seconds)
        self._host_job_poll_interval_seconds = min(1.0, max(0.05, host_job_poll_interval_seconds))

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
        # The caller's limit controls only the returned result count. Keep the
        # semantic reranking pool stable so limit=1 cannot change the winner.
        candidate_limit = 250
        with self._connect() as connection, connection.cursor() as cursor:
            intent = InterfaceIntentMatcher.analyze(normalized)
            like = f"%{intent.search_term}%"
            cursor.execute(
                """
                SELECT interface.id, interface.name, interface.controller_name,
                       interface.controller_description, interface.path, interface.method,
                       interface.description, interface.operation_id,
                       interface.operation_kind, interface.crud_type,
                       interface.request_schema,
                       profile.business_entity, profile.business_action,
                       profile.business_scenario, profile.aliases,
                       profile.positive_examples, profile.negative_examples,
                       profile.source AS intent_source,
                       profile.confidence AS intent_confidence,
                       COALESCE(effects.items, '[]'::jsonb) AS table_effects,
                       source.name AS service_name,
                       source.invocation_mode, route.name AS route_service_name,
                       count(DISTINCT address.id)::int AS address_count,
                       count(DISTINCT identity.id)::int AS identity_count,
                       max(log.created_at) AS last_requested_at,
                       count(DISTINCT log.id)::int AS request_count,
                       count(DISTINCT log.id) FILTER (WHERE log.success=true)::int
                         AS successful_request_count
                FROM interface_forwarding_interfaces AS interface
                JOIN interface_forwarding_services AS source ON source.id=interface.service_id
                LEFT JOIN interface_forwarding_intent_profiles AS profile
                  ON profile.interface_id=interface.id
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'database_key', effect.database_key,
                            'schema_name', effect.schema_name,
                            'table_name', effect.table_name,
                            'effect_type', effect.effect_type,
                            'response_contribution', effect.response_contribution,
                            'source_file', effect.source_file,
                            'source_class', effect.source_class,
                            'source_method', effect.source_method,
                            'call_path', effect.call_path,
                            'evidence_type', effect.evidence_type,
                            'confidence', effect.confidence
                        ) ORDER BY effect.table_name, effect.effect_type
                    ) AS items
                    FROM interface_forwarding_table_effects effect
                    WHERE effect.interface_id=interface.id
                      AND effect.effect_type=ANY(
                        CASE interface.crud_type
                          WHEN 'read' THEN ARRAY['select']::text[]
                          WHEN 'create' THEN ARRAY['insert', 'upsert']::text[]
                          WHEN 'update' THEN ARRAY[
                            'insert', 'update', 'delete', 'soft_delete', 'upsert'
                          ]::text[]
                          WHEN 'delete' THEN ARRAY['delete', 'soft_delete']::text[]
                          ELSE ARRAY[]::text[]
                        END
                      )
                      AND (interface.crud_type <> 'read'
                           OR effect.response_contribution='returned')
                ) effects ON TRUE
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
                       OR interface.description ILIKE %s
                       OR interface.controller_name ILIKE %s
                       OR interface.controller_description ILIKE %s
                       OR profile.business_entity ILIKE %s
                       OR profile.business_action ILIKE %s
                       OR profile.business_scenario ILIKE %s
                       OR profile.aliases::text ILIKE %s
                       OR profile.positive_examples::text ILIKE %s
                       OR effects.items::text ILIKE %s
                       OR interface.request_schema::text ILIKE %s)
                GROUP BY interface.id, source.id, route.id, profile.interface_id, effects.items
                ORDER BY max(log.created_at) DESC NULLS LAST,
                         lower(interface.path), interface.method
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
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    candidate_limit,
                ),
            )
            rows = list(cursor.fetchall())
        ranked: list[tuple[int, str, dict[str, object]]] = []
        for row in rows:
            callable_now = (
                row["operation_kind"] in _EXECUTABLE_OPERATION_KINDS
                and row["invocation_mode"] != "disabled"
                and row["address_count"] > 0
            )
            item: dict[str, object] = {
                "interface_id": row["id"],
                "name": row["name"],
                "controller": row["controller_name"],
                "controller_name": row["controller_name"],
                "controller_description": row["controller_description"],
                "description": row["description"],
                "operation_id": row["operation_id"],
                "method": row["method"],
                "path": row["path"],
                "service": row["service_name"],
                "route_service": row["route_service_name"],
                "operation_kind": row["operation_kind"],
                "crud_type": row["crud_type"],
                "business_entity": row["business_entity"] or "",
                "business_action": row["business_action"] or "",
                "business_scenario": row["business_scenario"] or "",
                "aliases": row["aliases"] or [],
                "positive_examples": row["positive_examples"] or [],
                "negative_examples": row["negative_examples"] or [],
                "intent_source": row["intent_source"],
                "intent_confidence": row["intent_confidence"],
                "request_schema": row["request_schema"] or {},
                "table_effects": row["table_effects"] or [],
                "callable": callable_now,
                "address_count": row["address_count"],
                "identity_count": row["identity_count"],
                "request_count": row["request_count"],
                "successful_request_count": row["successful_request_count"],
                "last_requested_at": self._iso(row["last_requested_at"]),
            }
            match = InterfaceIntentMatcher.score(intent, item)
            item["match_score"] = match.score
            item["match_reasons"] = list(match.reasons)
            item["mismatches"] = list(match.mismatches)
            item["score_breakdown"] = list(match.score_breakdown)
            ranked.append((match.score, str(row["path"]), item))
        ranked.sort(key=lambda entry: (-entry[0], entry[1]))
        bounded = ranked[: max(1, min(limit, 50))]
        results = [entry[2] for entry in bounded]
        top_score = bounded[0][0] if bounded else 0
        second_score = bounded[1][0] if len(bounded) > 1 else 0
        confidence = InterfaceIntentMatcher.confidence(top_score, top_score - second_score)
        task_intent = self._task_intent(task_id)
        discovery = task_intent == "interface_discovery"
        goal_completed = bool(results) and discovery and confidence == "high"
        next_action = (
            "save_task_visualization_result"
            if goal_completed
            else "read_forwarding_interface_detail"
            if discovery and results
            else "prepare_forwarding_request"
            if confidence == "high"
            else "read_forwarding_interface_detail"
            if results
            else "report_no_match"
        )
        search_event_id = str(uuid4())
        ranking = [
            {
                "rank": rank,
                "interface_id": result["interface_id"],
                "match_score": result["match_score"],
            }
            for rank, result in enumerate(results, start=1)
        ]
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO interface_forwarding_search_events
                   (id, task_id, workspace_id, environment_key, tool_call_id,
                    query, parsed_intent, candidate_count, returned_count,
                    match_confidence, result_ranking, recommended_interface_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    search_event_id,
                    task_id,
                    workspace_id,
                    environment,
                    current_tool_call_id(),
                    normalized,
                    Jsonb(intent.as_dict()),
                    len(rows),
                    len(results),
                    confidence,
                    Jsonb(ranking),
                    results[0]["interface_id"] if results else None,
                ),
            )
        return {
            "status": "ok",
            "search_event_id": search_event_id,
            "environment": environment,
            "query": normalized,
            "parsed_intent": intent.as_dict(),
            "returned_count": len(results),
            "candidate_count": len(rows),
            "match_confidence": confidence,
            "recommended_interface_id": results[0]["interface_id"] if results else None,
            "recommended_detail_interface_ids": [result["interface_id"] for result in results[:2]]
            if results and confidence != "high"
            else [],
            "goal_completed": goal_completed,
            "next_action": next_action,
            "results": results,
        }

    def detail(self, *, task_id: int, interface_id: str) -> dict[str, object]:
        workspace_id, environment = self._task_scope(task_id, None)
        try:
            task = self._tasks.get_task(task_id)
        except TaskRepositoryError as exc:
            raise InterfaceForwardingContextError("任务不存在", code="task_not_found") from exc
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT interface.*, source.name AS service_name,
                       source.invocation_mode, source.gateway_path_prefix,
                       route.name AS route_service_name,
                       profile.business_entity, profile.business_action,
                       profile.business_scenario, profile.aliases,
                       profile.positive_examples, profile.negative_examples,
                       profile.source AS intent_source,
                       profile.confidence AS intent_confidence,
                       COALESCE((
                           SELECT jsonb_agg(
                               jsonb_build_object(
                                   'database_key', effect.database_key,
                                   'schema_name', effect.schema_name,
                                   'table_name', effect.table_name,
                                   'effect_type', effect.effect_type,
                                   'response_contribution', effect.response_contribution,
                                   'source_file', effect.source_file,
                                   'source_class', effect.source_class,
                                   'source_method', effect.source_method,
                                   'call_path', effect.call_path,
                                   'evidence_type', effect.evidence_type,
                                   'confidence', effect.confidence
                               ) ORDER BY effect.table_name, effect.effect_type
                           )
                           FROM interface_forwarding_table_effects AS effect
                           WHERE effect.interface_id=interface.id
                       ), '[]'::jsonb) AS table_effects,
                       COALESCE((
                           SELECT jsonb_agg(
                               jsonb_build_object(
                                   'mapping_id', mapping.id,
                                   'value_key', mapping.value_key,
                                   'name', mapping.name,
                                   'location', binding.location,
                                   'parameter_path', binding.parameter_path,
                                   'required', binding.required
                               ) ORDER BY binding.location, binding.parameter_path
                           )
                           FROM interface_value_mapping_bindings AS binding
                           JOIN interface_value_mappings AS mapping
                             ON mapping.id=binding.mapping_id
                            AND mapping.status='published'
                           WHERE binding.interface_id=interface.id
                       ), '[]'::jsonb) AS parameter_mappings,
                       COALESCE((
                           SELECT jsonb_build_object(
                               'success_code_paths', rule.success_code_paths,
                               'success_values', rule.success_values,
                               'message_paths', rule.message_paths,
                               'data_paths', rule.data_paths,
                               'required_result_paths', rule.required_result_paths,
                               'source', rule.source,
                               'confidence', rule.confidence
                           )
                           FROM interface_forwarding_response_rules AS rule
                           WHERE rule.interface_id=interface.id
                       ), '{}'::jsonb) AS response_rule,
                       (SELECT count(*)::int
                        FROM interface_forwarding_environments AS address
                        WHERE address.workspace_id=interface.workspace_id
                          AND address.environment_key=%s
                          AND address.service_id=route.id) AS address_count,
                       (SELECT count(*)::int
                        FROM interface_forwarding_identities AS identity
                        JOIN interface_forwarding_environments AS address
                          ON address.id=identity.environment_id
                        WHERE address.workspace_id=interface.workspace_id
                          AND address.environment_key=%s
                          AND address.service_id=route.id) AS identity_count,
                       (SELECT count(*)::int FROM interface_forwarding_logs AS log
                        WHERE log.interface_id=interface.id) AS request_count,
                       (SELECT max(log.created_at) FROM interface_forwarding_logs AS log
                        WHERE log.interface_id=interface.id) AS last_requested_at
                FROM interface_forwarding_interfaces AS interface
                JOIN interface_forwarding_services AS source ON source.id=interface.service_id
                LEFT JOIN interface_forwarding_services AS route
                  ON route.id=CASE WHEN source.invocation_mode='gateway'
                                   THEN source.gateway_service_id ELSE source.id END
                LEFT JOIN interface_forwarding_intent_profiles AS profile
                  ON profile.interface_id=interface.id
                WHERE interface.id=%s AND interface.workspace_id=%s
                """,
                (environment, environment, interface_id, workspace_id),
            )
            row = cursor.fetchone()
        if not row:
            raise InterfaceForwardingContextError("接口不存在", code="interface_not_found")
        parsed_intent = InterfaceIntentMatcher.analyze(task.task)
        candidate = {
            "name": row["name"],
            "path": row["path"],
            "crud_type": row["crud_type"],
            "business_entity": row["business_entity"] or "",
            "business_action": row["business_action"] or "",
            "business_scenario": row["business_scenario"] or "",
            "aliases": row["aliases"] or [],
            "positive_examples": row["positive_examples"] or [],
            "negative_examples": row["negative_examples"] or [],
            "intent_confidence": row["intent_confidence"],
            "table_effects": row["table_effects"] or [],
        }
        match = InterfaceIntentMatcher.score(parsed_intent, candidate)
        callable_now = (
            row["operation_kind"] in _EXECUTABLE_OPERATION_KINDS
            and row["invocation_mode"] != "disabled"
            and int(row["address_count"] or 0) > 0
        )
        discovery = task.intent_type == "interface_discovery"
        return {
            "status": "ok",
            "task_intent": task.intent_type,
            "environment": environment,
            "identity": {
                "id": row["id"],
                "name": row["name"],
                "service": row["service_name"],
                "route_service": row["route_service_name"],
                "controller": row["controller_name"],
                "operation_id": row["operation_id"],
                "method": row["method"],
                "path": row["path"],
            },
            "semantics": {
                "business_entity": row["business_entity"] or "",
                "business_action": row["business_action"] or "",
                "business_scenario": row["business_scenario"] or "",
                "crud_type": row["crud_type"],
                "operation_kind": row["operation_kind"],
                "aliases": row["aliases"] or [],
                "positive_examples": row["positive_examples"] or [],
                "negative_examples": row["negative_examples"] or [],
                "source": row["intent_source"],
                "confidence": row["intent_confidence"],
            },
            "selection_assessment": {
                "parsed_intent": parsed_intent.as_dict(),
                "match_score": match.score,
                "match_reasons": list(match.reasons),
                "mismatches": list(match.mismatches),
            },
            "request_contract": self._contract_summary(
                self._normalize_contract(row["request_contract"] or {}, self._route_path(row))
            ),
            "response_contract": self._response_contract_summary(row["response_schema"] or {}),
            "response_rule": row["response_rule"] or {},
            "parameter_mappings": row["parameter_mappings"] or [],
            "table_effects": row["table_effects"] or [],
            "execution_readiness": {
                "callable": callable_now,
                "address_count": int(row["address_count"] or 0),
                "identity_count": int(row["identity_count"] or 0),
            },
            "history_summary": {
                "request_count": int(row["request_count"] or 0),
                "last_requested_at": self._iso(row["last_requested_at"]),
            },
            "goal_completed": discovery,
            "next_action": (
                "save_task_visualization_result" if discovery else "prepare_forwarding_request"
            ),
        }

    def history(
        self,
        *,
        task_id: int,
        interface_id: str,
        limit: int = 5,
        success_only: bool = True,
        include_response: bool = False,
    ) -> dict[str, object]:
        workspace_id, environment = self._task_scope(task_id, None)
        bounded_limit = max(1, min(limit, 10))
        with self._connect() as connection, connection.cursor() as cursor:
            interface = self._load_interface(cursor, workspace_id, interface_id)
            cursor.execute(
                """SELECT log.id, log.created_at, log.status_code, log.success,
                          log.duration_ms, log.request_body, log.response_body,
                          log.response_bytes, log.response_truncated,
                          address.name AS address_name,
                          log.identity_name, log.identity_role,
                          plan.parameter_evidence
                   FROM interface_forwarding_logs AS log
                   LEFT JOIN interface_forwarding_environments AS address
                     ON address.id=log.address_id
                   LEFT JOIN interface_forwarding_request_plans AS plan
                     ON plan.id=log.plan_id
                   WHERE log.workspace_id=%s AND log.interface_id=%s
                     AND (log.environment_key=%s OR log.environment_key IS NULL)
                     AND (%s=false OR log.success=true)
                   ORDER BY log.created_at DESC, log.id DESC
                   LIMIT %s""",
                (workspace_id, interface_id, environment, success_only, bounded_limit),
            )
            rows = list(cursor.fetchall())

        requests: list[dict[str, object]] = []
        for row in rows:
            item: dict[str, object] = {
                "log_id": str(row["id"]),
                "created_at": self._iso(row["created_at"]),
                "status_code": row["status_code"],
                "success": bool(row["success"]),
                "duration_ms": int(row["duration_ms"] or 0),
                "address_name": row["address_name"],
                "login_account": row["identity_name"],
                "role_name": row["identity_role"],
                "request": self._parse_log_payload(row["request_body"]),
                "parameter_evidence": (
                    row["parameter_evidence"] if isinstance(row["parameter_evidence"], dict) else {}
                ),
                "response_bytes": int(row["response_bytes"] or 0),
                "response_truncated": bool(row["response_truncated"]),
            }
            if include_response:
                response, history_truncated = self._bounded_log_payload(row["response_body"])
                item["response"] = response
                item["response_history_truncated"] = history_truncated
            requests.append(item)

        return {
            "status": "ok",
            "environment": environment,
            "interface": {
                "id": str(interface["id"]),
                "name": str(interface["name"]),
                "service": str(interface["service_name"]),
                "method": str(interface["method"]),
                "path": str(interface["path"]),
            },
            "returned_count": len(requests),
            "requests": requests,
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
        try:
            task = self._tasks.get_task(task_id)
        except TaskRepositoryError as exc:
            raise InterfaceForwardingContextError("任务不存在", code="task_not_found") from exc
        with self._connect() as connection, connection.cursor() as cursor:
            interface = self._load_interface(cursor, workspace_id, interface_id)
            parsed_intent = InterfaceIntentMatcher.analyze(task.task)
            candidate = {
                "name": interface["name"],
                "path": interface["path"],
                "description": interface["description"] or "",
                "controller_name": interface["controller_name"] or "",
                "controller_description": interface["controller_description"] or "",
                "crud_type": interface["crud_type"],
                "business_entity": interface["business_entity"] or "",
                "business_action": interface["business_action"] or "",
                "business_scenario": interface["business_scenario"] or "",
                "aliases": interface["aliases"] or [],
                "positive_examples": interface["positive_examples"] or [],
                "negative_examples": interface["negative_examples"] or [],
                "intent_confidence": interface["intent_confidence"],
                "request_schema": interface["request_schema"] or {},
                "table_effects": interface["table_effects"] or [],
                "successful_request_count": interface["successful_request_count"],
            }
            semantic_match = InterfaceIntentMatcher.score(parsed_intent, candidate)
            intent_assessment = {
                "parsed_intent": parsed_intent.as_dict(),
                "match_score": semantic_match.score,
                "match_reasons": list(semantic_match.reasons),
                "mismatches": list(semantic_match.mismatches),
                "selected_interface_id": interface_id,
            }
            blocking_mismatches = self._blocking_intent_mismatches(semantic_match)
            intent_assessment["blocking_mismatches"] = blocking_mismatches
            search_selection = self._bind_latest_search_selection(
                cursor,
                task_id=task_id,
                workspace_id=workspace_id,
                interface_id=interface_id,
            )
            if search_selection:
                intent_assessment["search_event_id"] = search_selection["id"]
                intent_assessment["initial_rank"] = search_selection["selected_rank"]
            intent["intent_assessment"] = intent_assessment
            if task.intent_type == "interface_discovery":
                return {
                    "status": "intent_mismatch",
                    **intent,
                    "message": "当前任务只查找或说明接口，不执行请求",
                    "next_action": "save_task_visualization_result",
                }
            if task.intent_type == "interface_execute" and blocking_mismatches:
                return {
                    "status": "intent_mismatch",
                    **intent,
                    "message": "所选接口与用户业务动作不一致，请重新选择搜索结果",
                    "selected_interface": {
                        "id": interface["id"],
                        "name": interface["name"],
                        "crud_type": interface["crud_type"],
                        "business_entity": interface["business_entity"] or "",
                        "business_action": interface["business_action"] or "",
                    },
                    "next_action": "search_forwarding_interfaces",
                }
            if interface["operation_kind"] not in _EXECUTABLE_OPERATION_KINDS:
                return {
                    "status": "operation_not_allowed",
                    **intent,
                    "operation_kind": interface["operation_kind"],
                    "message": "接口操作类型无效，无法生成执行计划",
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
                 request_payload, parameter_evidence, intent_match_score,
                 intent_match_evidence, search_event_id, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
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
                    semantic_match.score,
                    Jsonb(intent_assessment),
                    search_selection["id"] if search_selection else None,
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
                          interface.response_schema,
                          source.name AS service_name, source.invocation_mode,
                          source.gateway_path_prefix, source.updated_at AS service_updated_at,
                          route.id AS route_service_id, route.name AS route_service_name,
                          interface.updated_at AS interface_updated_at,
                          address.name AS address_name, address.base_url,
                          address.updated_at AS address_updated_at,
                          identity.login_account, identity.role_name, identity.request_header,
                          identity.updated_at AS identity_updated_at,
                          workspace_environment.display_name AS workspace_environment_name,
                          COALESCE((
                              SELECT jsonb_build_object(
                                  'success_code_paths', rule.success_code_paths,
                                  'success_values', rule.success_values,
                                  'message_paths', rule.message_paths,
                                  'data_paths', rule.data_paths,
                                  'required_result_paths', rule.required_result_paths
                              )
                              FROM interface_forwarding_response_rules AS rule
                              WHERE rule.interface_id=interface.id
                          ), '{}'::jsonb) AS response_rule
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
            if plan["request_sha256"] != request_sha256:
                raise InterfaceForwardingContextError(
                    "请求摘要不匹配", code="request_hash_mismatch"
                )
            if (
                plan["operation_kind"] not in _EXECUTABLE_OPERATION_KINDS
                or plan["current_operation_kind"] not in _EXECUTABLE_OPERATION_KINDS
            ):
                raise InterfaceForwardingContextError(
                    "接口操作类型无效", code="operation_not_allowed"
                )
            if (
                self._fingerprint(plan, plan, plan if plan["identity_id"] else None)
                != plan["configuration_fingerprint"]
            ):
                raise InterfaceForwardingContextError(
                    "转发配置已变化，请重新准备", code="configuration_changed"
                )
            if plan["executed_at"] is not None:
                existing_execution = self._existing_execution_for_plan(cursor, plan_id)
                if existing_execution is not None:
                    self._complete_search_event(
                        cursor,
                        search_event_id=plan.get("search_event_id"),
                        execution_log_id=str(existing_execution["id"]),
                        success=bool(existing_execution["success"]),
                    )
                    return self._reused_execution_result(existing_execution)
                raise InterfaceForwardingContextError(
                    "执行计划已经使用", code="plan_already_executed"
                )
            if plan["expires_at"] <= datetime.now(UTC):
                raise InterfaceForwardingContextError(
                    "执行计划已过期，请重新准备", code="plan_expired"
                )
            successful_execution = self._successful_execution_for_request(cursor, plan)
            if successful_execution is not None:
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
                self._complete_search_event(
                    cursor,
                    search_event_id=plan.get("search_event_id"),
                    execution_log_id=str(successful_execution["id"]),
                    success=bool(successful_execution["success"]),
                )
                return self._reused_execution_result(successful_execution)
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
            if self._host_runner_ready() and str(payload["method"]).upper() in _HOST_RUNNER_METHODS:
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
        validation = InterfaceResponseValidator.validate(
            status_code=status_code,
            response_body=response_body,
            response_schema=plan["response_schema"] or {},
            response_rule=plan["response_rule"] or {},
            response_truncated=response_truncated,
            error_type=error_type,
        )
        success = self._response_success(status_code, response_body)
        if validation["status"] == "failed":
            success = False
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
                 address_id, identity_id, request_sha256, response_bytes, response_truncated,
                 intent_match_score, intent_match_evidence, validation_status,
                 validation_result)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s)""",
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
                    plan["intent_match_score"],
                    Jsonb(plan["intent_match_evidence"] or {}),
                    validation["status"],
                    Jsonb(validation),
                ),
            )
            if host_job_id:
                cursor.execute(
                    "DELETE FROM interface_forwarding_host_jobs WHERE id=%s",
                    (host_job_id,),
                )
            self._complete_search_event(
                cursor,
                search_event_id=plan.get("search_event_id"),
                execution_log_id=log_id,
                success=success,
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
            "validation_status": validation["status"],
            "validation": validation,
            "deduplicated": False,
        }

    @staticmethod
    def _existing_execution_for_plan(cursor: Any, plan_id: str) -> dict[str, Any] | None:
        cursor.execute(
            """SELECT id, success, status_code, duration_ms, response_body,
                      response_bytes, response_truncated,
                      validation_status, validation_result
               FROM interface_forwarding_logs
               WHERE plan_id=%s
               ORDER BY created_at DESC, id DESC
               LIMIT 1""",
            (plan_id,),
        )
        return cursor.fetchone()

    @staticmethod
    def _successful_execution_for_request(
        cursor: Any,
        plan: dict[str, Any],
    ) -> dict[str, Any] | None:
        cursor.execute(
            """SELECT log.id, log.success, log.status_code, log.duration_ms,
                      log.response_body, log.response_bytes, log.response_truncated,
                      log.validation_status, log.validation_result
               FROM interface_forwarding_logs AS log
               JOIN interface_forwarding_request_plans AS prior_plan
                 ON prior_plan.id=log.plan_id
               WHERE log.task_id=%s
                 AND log.interface_id=%s
                 AND log.environment_key=%s
                 AND log.address_id=%s
                 AND log.identity_id::text IS NOT DISTINCT FROM %s::text
                 AND log.request_sha256=%s
                 AND log.success=true
                 AND prior_plan.configuration_fingerprint=%s
               ORDER BY log.created_at DESC, log.id DESC
               LIMIT 1""",
            (
                plan["task_id"],
                plan["interface_id"],
                plan["environment_key"],
                plan["address_id"],
                plan["identity_id"],
                plan["request_sha256"],
                plan["configuration_fingerprint"],
            ),
        )
        return cursor.fetchone()

    @staticmethod
    def _reused_execution_result(execution: dict[str, Any]) -> dict[str, object]:
        success = bool(execution["success"])
        return {
            "status": "completed" if success else "request_failed",
            "execution_mode": "deduplicated",
            "execution_id": str(execution["id"]),
            "success": success,
            "status_code": execution["status_code"],
            "duration_ms": int(execution["duration_ms"] or 0),
            "response_body": execution["response_body"],
            "response_headers": {},
            "response_bytes": int(execution["response_bytes"] or 0),
            "truncated": bool(execution["response_truncated"]),
            "error_type": None if success else "previous_request_failed",
            "validation_status": execution.get("validation_status") or "not_configured",
            "validation": execution.get("validation_result") or {},
            "deduplicated": True,
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
                    json=(body_values or None if method.upper() not in {"GET", "HEAD"} else None),
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
            time.sleep(self._host_job_poll_interval_seconds)
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
            raise InterfaceForwardingContextError("宿主机转发任务不存在", code="host_job_not_found")
        return dict(row)

    def lease_host_job(self, *, runner_id: str, lease_seconds: int) -> dict[str, object] | None:
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
                or plan["operation_kind"] not in _EXECUTABLE_OPERATION_KINDS
                or plan["current_operation_kind"] not in _EXECUTABLE_OPERATION_KINDS
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
            url, query_values, body_values = self._materialize_request(plan["base_url"], payload)
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

    def _task_intent(self, task_id: int) -> str:
        try:
            return str(self._tasks.get_task(task_id).intent_type)
        except TaskRepositoryError as exc:
            raise InterfaceForwardingContextError("任务不存在", code="task_not_found") from exc

    @staticmethod
    def _load_interface(cursor: Any, workspace_id: str, interface_id: str) -> dict[str, Any]:
        cursor.execute(
            """SELECT interface.*, source.name AS service_name, source.invocation_mode,
                      source.gateway_path_prefix, source.updated_at AS service_updated_at,
                      route.id AS route_service_id, route.name AS route_service_name,
                      profile.business_entity, profile.business_action,
                      profile.business_scenario, profile.aliases,
                      profile.positive_examples, profile.negative_examples,
                      profile.source AS intent_source,
                      profile.confidence AS intent_confidence,
                      (SELECT count(*)::int
                       FROM interface_forwarding_logs AS log
                       WHERE log.interface_id=interface.id AND log.success=true)
                        AS successful_request_count,
                      COALESCE((
                          SELECT jsonb_agg(
                              jsonb_build_object(
                                  'database_key', effect.database_key,
                                  'schema_name', effect.schema_name,
                                  'table_name', effect.table_name,
                                  'effect_type', effect.effect_type,
                                  'response_contribution', effect.response_contribution,
                                  'confidence', effect.confidence
                              ) ORDER BY effect.table_name, effect.effect_type
                          ) FROM interface_forwarding_table_effects AS effect
                          WHERE effect.interface_id=interface.id
                      ), '[]'::jsonb) AS table_effects
               FROM interface_forwarding_interfaces AS interface
               JOIN interface_forwarding_services AS source ON source.id=interface.service_id
               LEFT JOIN interface_forwarding_services AS route
                 ON route.id=CASE WHEN source.invocation_mode='gateway'
                                  THEN source.gateway_service_id ELSE source.id END
               LEFT JOIN interface_forwarding_intent_profiles AS profile
                 ON profile.interface_id=interface.id
               WHERE interface.id=%s AND interface.workspace_id=%s""",
            (interface_id, workspace_id),
        )
        row = cursor.fetchone()
        if not row:
            raise InterfaceForwardingContextError("接口不存在", code="interface_not_found")
        return row

    @staticmethod
    def _bind_latest_search_selection(
        cursor: Any,
        *,
        task_id: int,
        workspace_id: str,
        interface_id: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """WITH selected AS (
                   SELECT event.id,
                          COALESCE((ranked.item->>'rank')::int, ranked.position::int)
                            AS selected_rank
                   FROM interface_forwarding_search_events AS event
                   CROSS JOIN LATERAL jsonb_array_elements(event.result_ranking)
                     WITH ORDINALITY AS ranked(item, position)
                   WHERE event.task_id=%s AND event.workspace_id=%s
                     AND ranked.item->>'interface_id'=%s
                   ORDER BY event.created_at DESC, event.id DESC
                   LIMIT 1
               )
               UPDATE interface_forwarding_search_events AS event
               SET selected_interface_id=%s,
                   selected_rank=selected.selected_rank,
                   selected_at=CURRENT_TIMESTAMP
               FROM selected
               WHERE event.id=selected.id
               RETURNING event.id, event.selected_rank""",
            (task_id, workspace_id, interface_id, interface_id),
        )
        return cursor.fetchone()

    @staticmethod
    def _complete_search_event(
        cursor: Any,
        *,
        search_event_id: str | None,
        execution_log_id: str,
        success: bool,
    ) -> None:
        if not search_event_id:
            return
        cursor.execute(
            """UPDATE interface_forwarding_search_events
               SET execution_log_id=%s, execution_success=%s,
                   executed_at=CURRENT_TIMESTAMP
               WHERE id=%s""",
            (execution_log_id, success, search_event_id),
        )

    @staticmethod
    def _blocking_intent_mismatches(match: Any) -> list[str]:
        """Return only contradictions that make the selected operation unsafe to execute."""

        blocking_categories = {"crud", "negative_example"}
        return [
            str(item["reason"])
            for item in match.score_breakdown
            if item.get("category") in blocking_categories and int(item.get("delta") or 0) < 0
        ]

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
                    caller_bindings.append({"location": location, "parameter_path": parameter_path})
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
                field_summaries.append({"location": location, "parameter_path": parameter_path})
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
    def _parse_log_payload(value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    @classmethod
    def _bounded_log_payload(cls, value: object) -> tuple[object, bool]:
        if not isinstance(value, str):
            return value, False
        maximum_characters = 100_000
        truncated = len(value) > maximum_characters
        bounded = value[:maximum_characters]
        if truncated:
            return bounded, True
        return cls._parse_log_payload(bounded), False

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
                        value if isinstance(value, int) and not isinstance(value, bool) else 10
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
    def _response_contract_summary(schema: dict[str, Any]) -> dict[str, object]:
        if not isinstance(schema, dict) or not schema:
            return {"configured": False, "type": "unknown", "fields": []}
        properties = schema.get("properties")
        fields: list[dict[str, object]] = []
        required = set(schema.get("required") or [])
        if isinstance(properties, dict):
            for name, raw_field in list(properties.items())[:200]:
                field = raw_field if isinstance(raw_field, dict) else {}
                fields.append(
                    {
                        "name": str(name),
                        "type": str(field.get("type") or "unknown"),
                        "required": name in required,
                    }
                )
        return {
            "configured": True,
            "type": str(schema.get("type") or "object"),
            "fields": fields,
            "truncated": isinstance(properties, dict) and len(properties) > len(fields),
        }

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
