from __future__ import annotations

import json
import re
import time
from contextlib import nullcontext
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from context_router.interface_search.domain import EndpointCreate
from context_router.interface_search.search import SearchService
from context_router.schemas.interface_forwarding import (
    BrowserInterfaceCapture,
    InterfaceForwardingBrowserCaptureImport,
    InterfaceForwardingEnvironmentWrite,
    InterfaceForwardingExecute,
    InterfaceForwardingIdentityWrite,
    InterfaceForwardingImport,
    InterfaceForwardingLogWrite,
    InterfaceSemanticsWrite,
)
from context_router.services.visualization_security import redact_value

_BROWSER_REQUEST_MAX_BYTES = 262_144
_BROWSER_RESPONSE_MAX_BYTES = 1_048_576


class InterfaceForwardingError(RuntimeError):
    pass


class InterfaceForwardingService:
    def __init__(
        self,
        database_url: str | None,
        interface_search_service: SearchService | None = None,
    ) -> None:
        self._database_url = database_url
        self._interface_search = interface_search_service

    @staticmethod
    def _coalesce_interface_name(
        name: str,
        *,
        operation_id: str = "",
        summary: str = "",
        path: str = "",
        method: str = "",
    ) -> str:
        """Choose source-provided identity without workspace-specific naming rules."""
        return next(
            (
                candidate.strip()
                for candidate in (summary, name, operation_id, f"{method.upper()} {path}")
                if candidate and candidate.strip()
            ),
            "",
        )

    @staticmethod
    def _controller_name(operation: dict[str, Any]) -> str:
        tags = operation.get("tags")
        tag = str(tags[0]).strip() if isinstance(tags, list) and tags else ""
        if not tag:
            return ""
        words = [word for word in tag.replace("_", "-").split("-") if word]
        controller_name = "".join(word[:1].upper() + word[1:] for word in words)
        if not controller_name.lower().endswith("controller"):
            controller_name += "Controller"
        return controller_name

    def _connect(self):
        if not self._database_url:
            raise InterfaceForwardingError("控制面数据库尚未配置")
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def overview(
        self,
        workspace_id: str,
        keyword: str = "",
        *,
        service_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        like = f"%{keyword.strip()}%"
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT s.id, s.name, s.created_at, s.updated_at,
                       count(i.id)::int AS interface_count
                FROM interface_forwarding_services s
                LEFT JOIN interface_forwarding_interfaces i ON i.service_id = s.id
                WHERE s.workspace_id = %s
                GROUP BY s.id ORDER BY lower(s.name)
                """,
                (workspace_id,),
            )
            services = list(cursor.fetchall())
            service_ids = {str(item["id"]) for item in services}
            if service_id is None or (service_id and service_id not in service_ids):
                selected_service_id = str(services[0]["id"]) if services else ""
            else:
                selected_service_id = service_id
            filter_params = (
                workspace_id,
                selected_service_id,
                selected_service_id,
                keyword.strip(),
                like,
                like,
                like,
                like,
                like,
            )
            cursor.execute(
                """
                SELECT count(*)::int AS total
                FROM interface_forwarding_interfaces i
                LEFT JOIN interface_semantic_index semantic ON semantic.id = i.id
                WHERE i.workspace_id = %s
                  AND (%s = '' OR i.service_id = %s)
                  AND (%s = '' OR i.name ILIKE %s OR i.path ILIKE %s
                       OR i.description ILIKE %s
                       OR i.controller_name ILIKE %s
                       OR semantic.search_document ILIKE %s)
                """,
                filter_params,
            )
            total_row = cursor.fetchone()
            interface_total = int(total_row["total"] if total_row else 0)
            total_pages = max(1, (interface_total + page_size - 1) // page_size)
            current_page = min(page, total_pages)
            offset = (current_page - 1) * page_size
            cursor.execute(
                """
                SELECT i.id, i.service_id, service.name AS service_name,
                       i.name, i.path, i.method, i.description,
                       i.controller_name, i.operation_id, i.operation_kind,
                       i.request_schema, i.response_schema, i.created_at, i.updated_at,
                       latest.last_requested_at,
                       semantic.purpose, semantic.audiences, semantic.domains,
                       semantic.scenarios, semantic.actions, semantic.entities,
                       semantic.aliases, semantic.resource, semantic.lookup_keys,
                       semantic.cardinality, semantic.ownership, semantic.discriminators,
                       semantic.required_inputs, semantic.request_schema_paths,
                       semantic.response_schema_paths, semantic.business_identifiers,
                       semantic.interface_family, semantic.family_size,
                       semantic.sibling_actions, semantic.distinguishing_features,
                       semantic.tags, semantic.semantic_source, semantic.semantic_model,
                       semantic.semantic_confidence, semantic.semantic_evidence,
                       semantic.semantic_field_sources, semantic.semantic_confidences,
                       semantic.search_document_version, semantic.embedding_version,
                       semantic.source_locations, semantic.semantic_stale,
                       COALESCE(effects.items, '[]'::jsonb) AS table_effects
                FROM interface_forwarding_interfaces i
                JOIN interface_forwarding_services service ON service.id = i.service_id
                LEFT JOIN interface_semantic_index semantic ON semantic.id = i.id
                LEFT JOIN LATERAL (
                    SELECT logs.created_at AS last_requested_at
                    FROM interface_forwarding_logs logs
                    WHERE logs.interface_id = i.id
                    ORDER BY logs.created_at DESC
                    LIMIT 1
                ) latest ON TRUE
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
                    WHERE effect.interface_id = i.id
                ) effects ON TRUE
                WHERE i.workspace_id = %s
                  AND (%s = '' OR i.service_id = %s)
                  AND (%s = '' OR i.name ILIKE %s OR i.path ILIKE %s
                       OR i.description ILIKE %s
                       OR i.controller_name ILIKE %s
                       OR semantic.search_document ILIKE %s)
                ORDER BY latest.last_requested_at DESC NULLS LAST,
                         lower(i.path), i.method
                LIMIT %s OFFSET %s
                """,
                (*filter_params, page_size, offset),
            )
            interfaces = list(cursor.fetchall())
            for item in interfaces:
                item["name"] = self._coalesce_interface_name(
                    str(item["name"]),
                    summary=str(item["description"] or ""),
                    path=str(item["path"]),
                    method=str(item["method"]),
                )
                item["semantic"] = self._retrieval_semantic_json(item)
                item["semantic_governance"] = self._semantic_governance_json(item)
                for semantic_key in (
                    "purpose",
                    "audiences",
                    "domains",
                    "scenarios",
                    "actions",
                    "entities",
                    "aliases",
                    "resource",
                    "lookup_keys",
                    "cardinality",
                    "ownership",
                    "discriminators",
                    "required_inputs",
                    "request_schema_paths",
                    "response_schema_paths",
                    "business_identifiers",
                    "interface_family",
                    "family_size",
                    "sibling_actions",
                    "distinguishing_features",
                    "tags",
                    "semantic_source",
                    "semantic_model",
                    "semantic_confidence",
                    "semantic_evidence",
                    "semantic_field_sources",
                    "semantic_confidences",
                    "search_document_version",
                    "embedding_version",
                    "source_locations",
                    "semantic_stale",
                ):
                    item.pop(semantic_key, None)
            environments = self.list_environments(workspace_id, connection=connection)
        return {
            "workspace_id": workspace_id,
            "services": services,
            "environments": environments,
            "interfaces": interfaces,
            "selected_service_id": selected_service_id,
            "interface_total": interface_total,
            "page": current_page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    @staticmethod
    def _retrieval_semantic_json(item: dict[str, Any]) -> dict[str, Any] | None:
        if not item.get("purpose"):
            return None
        result: dict[str, Any] = {
            "id": str(item["id"]),
            "service": str(item.get("service_name") or ""),
            "method": str(item["method"]),
            "path": str(item["path"]),
            "operation_id": str(item.get("operation_id") or ""),
            "title": str(item["name"]),
            "purpose": str(item["purpose"]),
            "audiences": item.get("audiences") or [],
            "domains": item.get("domains") or [],
            "resource": str(item.get("resource") or ""),
            "actions": item.get("actions") or [],
        }
        optional = {
            "entities": item.get("entities") or [],
            "scenarios": item.get("scenarios") or [],
            "aliases": item.get("aliases") or [],
            "lookup_keys": item.get("lookup_keys") or [],
            "discriminators": item.get("discriminators") or [],
        }
        result.update({key: value for key, value in optional.items() if value})
        if item.get("cardinality") not in {None, "", "unknown"}:
            result["cardinality"] = item["cardinality"]
        if item.get("ownership") not in {None, "", "unknown"}:
            result["ownership"] = item["ownership"]
        return result

    @staticmethod
    def _semantic_governance_json(item: dict[str, Any]) -> dict[str, Any] | None:
        if not item.get("purpose"):
            return None
        return {
            "schema_retrieval": {
                "required_inputs": item.get("required_inputs") or [],
                "request_schema_paths": item.get("request_schema_paths") or [],
                "response_schema_paths": item.get("response_schema_paths") or [],
                "business_identifiers": item.get("business_identifiers") or [],
            },
            "interface_family": {
                "controller_name": item.get("controller_name") or "",
                "family": item.get("interface_family") or "",
                "family_size": item.get("family_size") or 1,
                "sibling_actions": item.get("sibling_actions") or {},
                "distinguishing_features": item.get("distinguishing_features") or {},
                "tags": item.get("tags") or [],
            },
            "semantic_governance": {
                "source": item.get("semantic_source") or "",
                "model": item.get("semantic_model") or "",
                "confidence": item.get("semantic_confidence"),
                "evidence": item.get("semantic_evidence") or [],
                "field_sources": item.get("semantic_field_sources") or {},
                "field_confidences": item.get("semantic_confidences") or {},
                "search_document_version": item.get("search_document_version") or "",
                "embedding_version": item.get("embedding_version") or "",
                "source_locations": item.get("source_locations") or [],
                "stale": bool(item.get("semantic_stale")),
            },
        }

    def update_interface_semantics(
        self,
        interface_id: str,
        payload: InterfaceSemanticsWrite,
    ) -> dict[str, Any]:
        if self._interface_search is None:
            raise InterfaceForwardingError("接口语义检索尚未启用")
        result = self._interface_search.update_semantics(interface_id, payload)
        if result is None:
            raise InterfaceForwardingError("接口不存在")
        return result.model_dump(mode="json")

    def import_spec(self, payload: InterfaceForwardingImport) -> dict[str, Any]:
        service_name = payload.service_name.strip()
        endpoints = self._parse_spec(payload.spec)
        if not endpoints:
            raise InterfaceForwardingError("Swagger/OpenAPI 文件中没有可导入的接口")
        pending_index: list[tuple[str, EndpointCreate]] = []
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO interface_forwarding_services (id, workspace_id, name)
                VALUES (%s, %s, %s)
                ON CONFLICT (workspace_id, name) DO UPDATE
                SET updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                (str(uuid4()), payload.workspace_id, service_name),
            )
            service_id = str(cursor.fetchone()["id"])
            imported_count = 0
            for endpoint in endpoints:
                endpoint_id = str(uuid4())
                controller_name = str(endpoint["controller_name"]).strip()
                interface_name = (
                    str(endpoint["name"]).strip()
                    or str(endpoint["operation_id"]).strip()
                    or f"{endpoint['method']} {endpoint['path']}"
                )
                cursor.execute(
                    """
                    INSERT INTO interface_forwarding_interfaces
                        (id, workspace_id, service_id, name, path, method, description,
                         controller_name, request_schema, response_schema,
                         operation_id, operation_kind, request_contract)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (service_id, path, method) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        controller_name = EXCLUDED.controller_name,
                        request_schema = EXCLUDED.request_schema,
                        response_schema = EXCLUDED.response_schema,
                        operation_id = EXCLUDED.operation_id,
                        operation_kind = EXCLUDED.operation_kind,
                        request_contract = EXCLUDED.request_contract,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (
                        endpoint_id,
                        payload.workspace_id,
                        service_id,
                        interface_name,
                        endpoint["path"],
                        endpoint["method"],
                        endpoint["description"],
                        controller_name,
                        Jsonb(endpoint["request_schema"]),
                        Jsonb(endpoint["response_schema"]),
                        endpoint["operation_id"],
                        endpoint["operation_kind"],
                        Jsonb(endpoint["request_contract"]),
                    ),
                )
                saved_interface_id = str(cursor.fetchone()["id"])
                pending_index.append(
                    (
                        saved_interface_id,
                        EndpointCreate(
                            workspace_id=payload.workspace_id,
                            project=payload.workspace_id,
                            service=service_name,
                            method=endpoint["method"],
                            path=endpoint["path"],
                            operation_id=endpoint["operation_id"],
                            title=interface_name,
                            purpose=endpoint["description"] or interface_name,
                            controller_name=controller_name,
                            request_schema=endpoint["request_schema"],
                            response_schema=endpoint["response_schema"],
                            semantic_source="openapi_bootstrap",
                            semantic_model="openapi",
                            semantic_confidence=0.35,
                            semantic_evidence=["openapi_contract"],
                        ),
                    )
                )
                imported_count += 1
        if self._interface_search is not None:
            self._interface_search.add_many_with_ids(pending_index)
        return {
            "service_id": service_id,
            "service_name": service_name,
            "imported_count": imported_count,
        }

    def rewrite_names(
        self,
        workspace_id: str,
        service_id: str | None = None,
        path_prefix: str | None = None,
    ) -> dict[str, Any]:
        query = """
            SELECT interface.id, interface.name, interface.description,
                   interface.path, interface.method, interface.controller_name
            FROM interface_forwarding_interfaces AS interface
            JOIN interface_forwarding_services AS service
              ON service.id = interface.service_id
            WHERE interface.workspace_id = %s
            """
        params: tuple[str, ...] = (workspace_id,)
        if service_id:
            query += " AND interface.service_id = %s"
            params = (workspace_id, service_id)
        if path_prefix:
            query += " AND interface.path LIKE %s"
            params = (*params, f"{path_prefix.rstrip('/')}%")

        updated = 0
        total = 0
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = list(cursor.fetchall())
            total = len(rows)
            for row in rows:
                normalized_controller_name = str(row["controller_name"] or "").strip()
                normalized_name = self._coalesce_interface_name(
                    str(row["name"]),
                    summary=str(row["description"] or ""),
                    path=str(row["path"]),
                    method=str(row["method"]),
                )
                if normalized_name and (
                    normalized_name != str(row["name"])
                    or normalized_controller_name != str(row["controller_name"] or "")
                ):
                    cursor.execute(
                        """
                        UPDATE interface_forwarding_interfaces
                        SET name = %s,
                            controller_name = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (normalized_name, normalized_controller_name, row["id"]),
                    )
                    updated += 1

        return {
            "workspace_id": workspace_id,
            "service_id": service_id,
            "path_prefix": path_prefix,
            "total": total,
            "updated": updated,
        }

    @staticmethod
    def _parse_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
        paths = spec.get("paths")
        if not isinstance(paths, dict):
            return []

        def resolve(value: Any, seen: set[str] | None = None) -> Any:
            if not isinstance(value, dict) or "$ref" not in value:
                if isinstance(value, dict):
                    return {key: resolve(item, seen) for key, item in value.items()}
                if isinstance(value, list):
                    return [resolve(item, seen) for item in value]
                return value
            ref = str(value["$ref"])
            if not ref.startswith("#/") or ref in (seen or set()):
                return value
            current: Any = spec
            for part in ref[2:].split("/"):
                current = (
                    current.get(part.replace("~1", "/").replace("~0", "~"), {})
                    if isinstance(current, dict)
                    else {}
                )
            return resolve(current, (seen or set()) | {ref})

        endpoints: list[dict[str, Any]] = []
        methods = {"get", "post", "put", "patch", "delete", "head", "options"}
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method.lower() not in methods or not isinstance(operation, dict):
                    continue
                operation_id = str(operation.get("operationId") or "")
                controller_name = InterfaceForwardingService._controller_name(operation)
                request_schema: Any = {}
                parameter_contract: dict[str, list[dict[str, Any]]] = {
                    "path": [],
                    "query": [],
                    "header": [],
                }
                combined_parameters: list[Any] = []
                path_parameters = path_item.get("parameters", [])
                if isinstance(path_parameters, list):
                    combined_parameters.extend(path_parameters)
                operation_parameters = operation.get("parameters", [])
                if isinstance(operation_parameters, list):
                    combined_parameters.extend(operation_parameters)
                for raw_parameter in combined_parameters:
                    parameter = resolve(raw_parameter)
                    if not isinstance(parameter, dict):
                        continue
                    location = str(parameter.get("in") or "")
                    if location not in parameter_contract:
                        continue
                    schema = resolve(parameter.get("schema", {}))
                    if not isinstance(schema, dict):
                        schema = {}
                    parameter_contract[location].append(
                        {
                            "name": str(parameter.get("name") or ""),
                            "required": bool(parameter.get("required")),
                            "description": str(parameter.get("description") or ""),
                            "schema": schema,
                            "example": parameter.get("example", schema.get("example")),
                        }
                    )
                request_body = operation.get("requestBody", {})
                if isinstance(request_body, dict):
                    content = request_body.get("content", {})
                    if isinstance(content, dict):
                        media = content.get("application/json") or next(iter(content.values()), {})
                        if isinstance(media, dict):
                            request_schema = media.get("schema", {})
                if not request_schema:
                    if isinstance(operation_parameters, list):
                        for parameter in operation_parameters:
                            if isinstance(parameter, dict) and parameter.get("in") == "body":
                                request_schema = parameter.get("schema", {})
                                break
                response_schema: Any = {}
                responses = operation.get("responses", {})
                if isinstance(responses, dict):
                    response = (
                        responses.get("200")
                        or responses.get("201")
                        or responses.get("default")
                        or next(iter(responses.values()), {})
                    )
                    if isinstance(response, dict):
                        content = response.get("content", {})
                        if isinstance(content, dict) and content:
                            media = content.get("application/json") or next(
                                iter(content.values()), {}
                            )
                            if isinstance(media, dict):
                                response_schema = media.get("schema", {})
                        response_schema = response_schema or response.get("schema", {})
                endpoints.append(
                    {
                        "name": str(
                            operation.get("summary") or operation_id or f"{method.upper()} {path}"
                        ),
                        "operation_id": operation_id,
                        "path": str(path),
                        "method": method.upper(),
                        "description": str(operation.get("description") or ""),
                        "controller_name": controller_name,
                        "request_schema": resolve(request_schema),
                        "response_schema": resolve(response_schema),
                        "operation_kind": InterfaceForwardingService._operation_kind(
                            method.upper(),
                            str(operation.get("summary") or operation_id or ""),
                        ),
                        "request_contract": {
                            "path": InterfaceForwardingService._parameter_object_schema(
                                parameter_contract["path"]
                            ),
                            "query": InterfaceForwardingService._parameter_object_schema(
                                parameter_contract["query"]
                            ),
                            "header": InterfaceForwardingService._parameter_object_schema(
                                parameter_contract["header"]
                            ),
                            "body": resolve(request_schema),
                        },
                    }
                )
        return endpoints

    @staticmethod
    def _parameter_object_schema(parameters: list[dict[str, Any]]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for parameter in parameters:
            name = str(parameter.get("name") or "").strip()
            if not name:
                continue
            schema = dict(parameter.get("schema") or {})
            if parameter.get("description") and "description" not in schema:
                schema["description"] = parameter["description"]
            if parameter.get("example") is not None and "example" not in schema:
                schema["example"] = parameter["example"]
            properties[name] = schema
            if parameter.get("required"):
                required.append(name)
        result: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            result["required"] = required
        return result

    @staticmethod
    def _operation_kind(method: str, name: str) -> str:
        if "取消订阅" in name:
            return "write"
        if re.match(r"^(删除|批量删除|取消|驳回|停用|禁用|撤销|清除)", name.strip()):
            return "destructive"
        if re.match(
            r"^(新增|保存|更新|修改|创建|上传|提交|确认|启用|同步|导入|发货|调度)",
            name.strip(),
        ):
            return "write"
        if method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return "read"
        normalized = name.strip()
        if re.match(
            r"^(查询|分页查询|获取|统计|下载|预览|校验|检查|搜索|列出|按.+查询)",
            normalized,
        ):
            return "read"
        return "unknown"

    def rename_service(self, service_id: str, name: str) -> dict[str, Any]:
        return self._update_returning(
            """UPDATE interface_forwarding_services
            SET name=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s
            RETURNING id, workspace_id, name, updated_at""",
            (name.strip(), service_id),
        )

    def delete_service(self, service_id: str) -> None:
        self._delete("interface_forwarding_services", service_id)

    def delete_interface(self, interface_id: str) -> None:
        self._delete("interface_forwarding_interfaces", interface_id)

    def list_environments(self, workspace_id: str, *, connection=None) -> list[dict[str, Any]]:
        owns = connection is None
        connection = connection or self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT workspace.workspace_id,
                              workspace.environment_key,
                              workspace.display_name,
                              workspace.sort_order,
                              workspace.is_default
                    FROM workspace_environments AS workspace
                    WHERE workspace.workspace_id=%s
                    ORDER BY workspace.sort_order, workspace.environment_key""",
                    (workspace_id,),
                )
                environments = list(cursor.fetchall())
                cursor.execute(
                    """SELECT address.id, address.workspace_id,
                              address.environment_key, address.service_id,
                              service.name AS service_name, address.name,
                              address.base_url, address.created_at, address.updated_at
                    FROM interface_forwarding_environments AS address
                    LEFT JOIN interface_forwarding_services AS service
                      ON service.id=address.service_id
                    WHERE address.workspace_id=%s
                    ORDER BY address.environment_key, lower(service.name),
                             lower(address.name), address.created_at""",
                    (workspace_id,),
                )
                addresses_by_key: dict[str, list[dict[str, Any]]] = {}
                for address in cursor.fetchall():
                    addresses_by_key.setdefault(str(address["environment_key"]), []).append(address)
                for environment in environments:
                    environment["addresses"] = addresses_by_key.get(
                        str(environment["environment_key"]), []
                    )
                return environments
        finally:
            if owns:
                connection.close()

    def create_environment(self, payload: InterfaceForwardingEnvironmentWrite) -> dict[str, Any]:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO interface_forwarding_environments (
                            id, workspace_id, environment_key, service_id, name, base_url
                        )
                        SELECT %s, workspace.workspace_id, workspace.environment_key,
                               service.id, %s, %s
                        FROM workspace_environments AS workspace
                        JOIN interface_forwarding_services AS service
                          ON service.workspace_id=workspace.workspace_id
                         AND service.id=%s
                        WHERE workspace.workspace_id=%s
                          AND workspace.environment_key=%s
                        RETURNING id, workspace_id, environment_key, service_id,
                                  name, base_url, created_at, updated_at""",
                    (
                        str(uuid4()),
                        payload.name.strip(),
                        payload.base_url,
                        payload.service_id,
                        payload.workspace_id,
                        payload.environment_key,
                    ),
                )
                row = cursor.fetchone()
                if not row:
                    raise InterfaceForwardingError("当前环境或接口服务不存在")
                cursor.execute(
                    "SELECT name FROM interface_forwarding_services WHERE id=%s",
                    (row["service_id"],),
                )
                row["service_name"] = cursor.fetchone()["name"]
                return row
        except psycopg.errors.UniqueViolation as exc:
            raise InterfaceForwardingError("这个环境下已存在相同的地址名称") from exc

    def update_environment(
        self, environment_id: str, payload: InterfaceForwardingEnvironmentWrite
    ) -> dict[str, Any]:
        try:
            return self._update_returning(
                """UPDATE interface_forwarding_environments AS forwarding
                SET service_id=service.id, name=%s, base_url=%s,
                    updated_at=CURRENT_TIMESTAMP
                FROM workspace_environments AS workspace
                JOIN interface_forwarding_services AS service
                  ON service.workspace_id=workspace.workspace_id
                 AND service.id=%s
                WHERE forwarding.id=%s
                  AND forwarding.workspace_id=%s
                  AND workspace.workspace_id=forwarding.workspace_id
                  AND workspace.environment_key=%s
                  AND forwarding.environment_key=workspace.environment_key
                RETURNING forwarding.id, forwarding.workspace_id,
                          forwarding.environment_key, forwarding.service_id,
                          service.name AS service_name, forwarding.name,
                          forwarding.base_url, forwarding.created_at,
                          forwarding.updated_at""",
                (
                    payload.name.strip(),
                    payload.base_url,
                    payload.service_id,
                    environment_id,
                    payload.workspace_id,
                    payload.environment_key,
                ),
            )
        except InterfaceForwardingError as exc:
            if str(exc) == "同一工作空间内名称或接口已存在":
                raise InterfaceForwardingError("这个环境下已存在相同的地址名称") from exc
            raise

    def delete_environment(self, environment_id: str) -> None:
        self._delete("interface_forwarding_environments", environment_id)

    def list_identities(
        self, workspace_id: str, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT i.id, i.workspace_id, i.environment_id, i.login_account,
                       i.role_name, i.request_header, i.created_at, i.updated_at,
                       e.environment_key, e.name AS environment_name
                FROM interface_forwarding_identities i
                JOIN interface_forwarding_environments e ON e.id=i.environment_id
                WHERE i.workspace_id=%s AND (%s::text IS NULL OR e.id=%s)
                ORDER BY lower(i.login_account)
                """,
                (workspace_id, environment_id, environment_id),
            )
            return list(cursor.fetchall())

    def create_identity(self, payload: InterfaceForwardingIdentityWrite) -> dict[str, Any]:
        return self._write_identity(str(uuid4()), payload, create=True)

    def update_identity(
        self, identity_id: str, payload: InterfaceForwardingIdentityWrite
    ) -> dict[str, Any]:
        return self._write_identity(identity_id, payload, create=False)

    def _write_identity(
        self, identity_id: str, payload: InterfaceForwardingIdentityWrite, *, create: bool
    ) -> dict[str, Any]:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """SELECT id, environment_key, name FROM interface_forwarding_environments
                    WHERE id=%s AND workspace_id=%s""",
                    (payload.environment_id, payload.workspace_id),
                )
                environment = cursor.fetchone()
                if not environment:
                    raise InterfaceForwardingError("转发地址不存在")
                if create:
                    cursor.execute(
                        """INSERT INTO interface_forwarding_identities (
                                id, workspace_id, environment_id, login_account,
                                role_name, request_header
                            ) VALUES (%s,%s,%s,%s,%s,%s)
                            RETURNING id, workspace_id, environment_id, login_account,
                                      role_name, request_header, created_at, updated_at""",
                        (
                            identity_id,
                            payload.workspace_id,
                            environment["id"],
                            payload.login_account.strip(),
                            payload.role_name.strip(),
                            payload.request_header,
                        ),
                    )
                else:
                    cursor.execute(
                        """UPDATE interface_forwarding_identities
                            SET environment_id=%s, login_account=%s, role_name=%s,
                                request_header=%s,
                                updated_at=CURRENT_TIMESTAMP
                            WHERE id=%s AND workspace_id=%s
                            RETURNING id, workspace_id, environment_id, login_account,
                                      role_name, request_header, created_at, updated_at""",
                        (
                            environment["id"],
                            payload.login_account.strip(),
                            payload.role_name.strip(),
                            payload.request_header,
                            identity_id,
                            payload.workspace_id,
                        ),
                    )
                row = cursor.fetchone()
                if not row:
                    raise InterfaceForwardingError("请求身份不存在")
                row["environment_key"] = environment["environment_key"]
                row["environment_name"] = environment["name"]
                return row
        except psycopg.errors.UniqueViolation as exc:
            raise InterfaceForwardingError("这个转发地址下已存在相同登录账号和角色") from exc

    def delete_identity(self, identity_id: str) -> None:
        self._delete("interface_forwarding_identities", identity_id)

    def interface_state(self, interface_id: str) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, workspace_id, service_id, name, path, method,
                          description, request_schema, response_schema
                   FROM interface_forwarding_interfaces WHERE id=%s""",
                (interface_id,),
            )
            interface = cursor.fetchone()
            if not interface:
                raise InterfaceForwardingError("接口不存在")
            cursor.execute(
                """SELECT environment_id, identity_id, request_body,
                          response_body, params.updated_at, environment.environment_key
                   FROM interface_forwarding_params AS params
                   LEFT JOIN interface_forwarding_environments AS environment
                     ON environment.id=params.environment_id
                   WHERE interface_id=%s""",
                (interface_id,),
            )
            last_params = cursor.fetchone()
        return {"interface": interface, "last_params": last_params}

    def logs(self, interface_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, environment_name, identity_name, identity_role,
                request_url, request_body,
                response_body, status_code, success, duration_ms,
                created_at
                FROM interface_forwarding_logs WHERE interface_id=%s
                ORDER BY created_at DESC LIMIT %s""",
                (interface_id, max(1, min(limit, 200))),
            )
            return list(cursor.fetchall())

    def record_external_log(
        self, interface_id: str, payload: InterfaceForwardingLogWrite
    ) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, workspace_id, service_id, path
                FROM interface_forwarding_interfaces WHERE id=%s""",
                (interface_id,),
            )
            interface = cursor.fetchone()
            if not interface:
                raise InterfaceForwardingError("接口不存在")
            cursor.execute(
                """SELECT forwarding.id, forwarding.service_id, forwarding.name,
                          forwarding.base_url,
                          workspace.display_name AS workspace_environment_name
                FROM interface_forwarding_environments AS forwarding
                JOIN workspace_environments AS workspace
                  ON workspace.workspace_id=forwarding.workspace_id
                 AND workspace.environment_key=forwarding.environment_key
                WHERE forwarding.workspace_id=%s AND forwarding.id=%s""",
                (interface["workspace_id"], payload.environment_id),
            )
            environment = cursor.fetchone()
            if not environment:
                raise InterfaceForwardingError("转发地址不存在")
            if str(environment["service_id"] or "") != str(interface["service_id"]):
                raise InterfaceForwardingError("转发地址未映射到当前接口服务")
            cursor.execute(
                """SELECT id, login_account, role_name
                FROM interface_forwarding_identities
                WHERE id=%s AND environment_id=%s""",
                (payload.identity_id, environment["id"]),
            )
            identity = cursor.fetchone()
            if not identity:
                raise InterfaceForwardingError("请求身份不存在或不属于当前环境")
            request_url = urljoin(
                environment["base_url"].rstrip("/") + "/",
                interface["path"].lstrip("/"),
            )
            log_id = str(uuid4())
            cursor.execute(
                """INSERT INTO interface_forwarding_logs
                (id, workspace_id, interface_id, environment_name, identity_name,
                 identity_role, request_url, request_body, response_body, status_code,
                 success, duration_ms)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, environment_name, identity_name, identity_role,
                          request_url, request_body, response_body, status_code,
                          success, duration_ms, created_at""",
                (
                    log_id,
                    interface["workspace_id"],
                    interface_id,
                    f"{environment['workspace_environment_name']} · {environment['name']}",
                    identity["login_account"],
                    identity["role_name"],
                    request_url,
                    payload.request_body,
                    payload.response_body,
                    payload.status_code,
                    payload.success,
                    payload.duration_ms,
                ),
            )
            return cursor.fetchone()

    def import_browser_captures(
        self, payload: InterfaceForwardingBrowserCaptureImport, *, rematch: bool = False
    ) -> dict[str, Any]:
        """Acknowledge durable observations, not merely an HTTP-successful batch.

        Matching runs under a savepoint: a matching/log failure cannot discard the
        original sanitized observation. Revisions prevent delayed retries from
        overwriting a response with an earlier request-start snapshot.
        """
        acknowledged, imported, deduplicated, skipped, rejected = [], [], [], [], []
        with self._connect() as connection, connection.cursor() as cursor:
            if payload.environment_id:
                cursor.execute(
                    "SELECT environment_key FROM interface_forwarding_environments "
                    "WHERE workspace_id=%s AND id=%s",
                    (payload.workspace_id, payload.environment_id),
                )
            else:
                cursor.execute(
                    "SELECT environment_key FROM workspace_environments "
                    "WHERE workspace_id=%s AND environment_key=%s",
                    (payload.workspace_id, payload.environment_key),
                )
            environment = cursor.fetchone()
            if not environment:
                raise InterfaceForwardingError("录制环境不存在")
            environment_key = environment["environment_key"]
            for index, capture in enumerate(payload.captures):
                capture_id = capture.capture_id or str(uuid4())
                capture_retained = True
                try:
                    safe_url = self._safe_capture_url(capture.url)
                    if (
                        urlsplit(safe_url).scheme not in {"http", "https"}
                        or not urlsplit(safe_url).netloc
                    ):
                        raise ValueError("invalid_url")
                    self._url_origin(safe_url)
                    request, _, _ = self._bounded_json(
                        redact_value(capture.request_body), _BROWSER_REQUEST_MAX_BYTES
                    )
                    response, _, _ = self._bounded_json(
                        redact_value(capture.response_body), _BROWSER_RESPONSE_MAX_BYTES
                    )
                    safe_capture = capture.model_copy(
                        update={
                            "capture_id": capture_id,
                            "url": safe_url,
                            "request_body": json.loads(request),
                            "response_body": json.loads(response),
                        }
                    )
                    with connection.transaction():
                        cursor.execute(
                            """INSERT INTO browser_interface_captures
                            (workspace_id,capture_id,environment_key,revision,payload,match_status)
                            VALUES (%s,%s,%s,%s,%s,'pending')
                            ON CONFLICT (workspace_id,capture_id) DO NOTHING""",
                            (
                                payload.workspace_id,
                                capture_id,
                                environment_key,
                                capture.revision,
                                Jsonb(safe_capture.model_dump()),
                            ),
                        )
                        is_new = cursor.rowcount == 1
                        cursor.execute(
                            "SELECT * FROM browser_interface_captures "
                            "WHERE workspace_id=%s AND capture_id=%s FOR UPDATE",
                            (payload.workspace_id, capture_id),
                        )
                        stored = cursor.fetchone()
                        if stored["environment_key"] != environment_key:
                            raise ValueError("capture_environment_conflict")
                        needs_match = is_new or capture.revision > stored["revision"] or rematch
                        if capture.revision > stored["revision"]:
                            cursor.execute(
                                "UPDATE browser_interface_captures "
                                "SET revision=%s,payload=%s,updated_at=now() "
                                "WHERE workspace_id=%s AND capture_id=%s",
                                (
                                    capture.revision,
                                    Jsonb(safe_capture.model_dump()),
                                    payload.workspace_id,
                                    capture_id,
                                ),
                            )
                        elif not is_new:
                            safe_capture = BrowserInterfaceCapture.model_validate(stored["payload"])
                        match_status, reason, log_id = (
                            stored["match_status"],
                            stored["reason"],
                            stored["log_id"],
                        )
                        if needs_match:
                            match_status, reason = "pending", "in_progress"
                            if safe_capture.capture_state != "started":
                                try:
                                    with connection.transaction():
                                        result = self._import_browser_captures_matched(
                                            payload.model_copy(update={"captures": [safe_capture]}),
                                            connection=connection,
                                        )
                                    if result["imported"]:
                                        item = {**result["imported"][0], "index": index}
                                        imported.append(item)
                                        match_status, reason, log_id = "matched", "", item["log_id"]
                                    elif result["deduplicated"]:
                                        item = {**result["deduplicated"][0], "index": index}
                                        deduplicated.append(item)
                                        match_status = "matched"
                                        reason = "daily_read_deduplicated"
                                        log_id = item["log_id"]
                                        capture_retained = False
                                    else:
                                        reason = result["skipped"][0]["reason"]
                                except InterfaceForwardingError:
                                    reason = "forwarding_configuration_missing"
                                except psycopg.Error:
                                    reason = "matching_database_error"
                            if capture_retained:
                                cursor.execute(
                                    "UPDATE browser_interface_captures "
                                    "SET match_status=%s,reason=%s,log_id=%s,updated_at=now() "
                                    "WHERE workspace_id=%s AND capture_id=%s",
                                    (
                                        match_status,
                                        reason,
                                        log_id,
                                        payload.workspace_id,
                                        capture_id,
                                    ),
                                )
                            else:
                                cursor.execute(
                                    "DELETE FROM browser_interface_captures "
                                    "WHERE workspace_id=%s AND capture_id=%s",
                                    (payload.workspace_id, capture_id),
                                )
                    acknowledged.append(
                        {
                            "index": index,
                            "capture_id": capture_id,
                            "revision": max(capture.revision, stored["revision"]),
                            "status": "stored",
                            "deduplicated": not capture_retained,
                            "match_status": match_status,
                            "reason": reason,
                            "log_id": log_id,
                        }
                    )
                    if capture_retained and match_status != "matched":
                        skipped.append(
                            {"index": index, "url": safe_url, "reason": reason, "saved": True}
                        )
                except (ValueError, psycopg.Error):
                    rejected.append(
                        {"index": index, "capture_id": capture_id, "reason": "capture_rejected"}
                    )
        return {
            "workspace_id": payload.workspace_id,
            "environment_id": payload.environment_id,
            "environment_key": environment_key,
            "captured_count": len(payload.captures),
            "stored_count": sum(
                item["status"] == "stored" and not item["deduplicated"] for item in acknowledged
            ),
            "deduplicated_count": len(deduplicated),
            "imported_count": len(imported),
            "skipped_count": len(skipped),
            "imported": imported,
            "deduplicated": deduplicated,
            "skipped": skipped,
            "acknowledged": acknowledged,
            "rejected": rejected,
        }

    def browser_captures(
        self, workspace_id: str, *, limit: int = 50, capture_id: str | None = None
    ) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT match_status, count(*) AS count FROM browser_interface_captures "
                "WHERE workspace_id=%s GROUP BY match_status",
                (workspace_id,),
            )
            counts = {row["match_status"]: row["count"] for row in cursor.fetchall()}
            cursor.execute(
                """SELECT capture_id,environment_key,revision,match_status,reason,log_id,
                created_at,updated_at,payload->>'url' AS url,payload->>'method' AS method,
                payload->>'capture_state' AS capture_state,
                payload->'status_code' AS status_code,
                payload->'response_body_missing' AS response_body_missing
                FROM browser_interface_captures WHERE workspace_id=%s
                AND (%s::text IS NULL OR capture_id=%s)
                ORDER BY created_at DESC,capture_id LIMIT %s""",
                (workspace_id, capture_id, capture_id, limit),
            )
            records = list(cursor.fetchall())
            if capture_id and records:
                cursor.execute(
                    "SELECT payload FROM browser_interface_captures "
                    "WHERE workspace_id=%s AND capture_id=%s",
                    (workspace_id, capture_id),
                )
                records[0]["payload"] = cursor.fetchone()["payload"]
            return {"counts": counts, "records": records}

    def reconcile_browser_captures(self, workspace_id: str, limit: int = 50) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT environment_key,payload FROM browser_interface_captures
                WHERE workspace_id=%s AND match_status='pending'
                AND payload->>'capture_state' <> 'started' ORDER BY updated_at LIMIT %s""",
                (workspace_id, limit),
            )
            records = list(cursor.fetchall())
        results = [
            self.import_browser_captures(
                InterfaceForwardingBrowserCaptureImport(
                    workspace_id=workspace_id,
                    environment_key=record["environment_key"],
                    captures=[BrowserInterfaceCapture.model_validate(record["payload"])],
                ),
                rematch=True,
            )
            for record in records
        ]
        return {"checked": len(records), "matched": sum(r["imported_count"] for r in results)}

    def _import_browser_captures_matched(
        self,
        payload: InterfaceForwardingBrowserCaptureImport,
        *,
        connection=None,
    ) -> dict[str, Any]:
        """Map trusted browser observations to imported interfaces and persist safe logs.

        This endpoint deliberately accepts no request or response headers. Browser cookies,
        authorization headers and other ambient credentials therefore never enter the log.
        """
        with (
            nullcontext(connection) if connection is not None else self._connect() as connection,
            connection.cursor() as cursor,
        ):
            environment_where = (
                "forwarding.id=%s" if payload.environment_id else ("forwarding.environment_key=%s")
            )
            environment_value = payload.environment_id or payload.environment_key
            cursor.execute(
                f"""SELECT forwarding.id, forwarding.workspace_id, forwarding.service_id,
                           forwarding.environment_key, forwarding.name,
                           forwarding.base_url,
                           workspace.display_name AS workspace_environment_name
                    FROM interface_forwarding_environments AS forwarding
                    JOIN workspace_environments AS workspace
                      ON workspace.workspace_id=forwarding.workspace_id
                     AND workspace.environment_key=forwarding.environment_key
                    WHERE {environment_where} AND forwarding.workspace_id=%s
                    ORDER BY lower(forwarding.name), forwarding.id""",
                (environment_value, payload.workspace_id),
            )
            environments = list(cursor.fetchall())
            if not environments:
                raise InterfaceForwardingError(
                    "转发地址不存在" if payload.environment_id else "当前环境没有转发地址"
                )

            identity = None
            if payload.identity_id:
                cursor.execute(
                    """SELECT id, login_account, role_name
                       FROM interface_forwarding_identities
                       WHERE id=%s AND environment_id=%s AND workspace_id=%s""",
                    (payload.identity_id, payload.environment_id, payload.workspace_id),
                )
                identity = cursor.fetchone()
                if not identity:
                    raise InterfaceForwardingError("请求身份不存在或不属于当前环境")

            cursor.execute(
                """SELECT interface.id, interface.service_id, interface.name,
                          interface.method, interface.path, interface.operation_kind,
                          CASE WHEN source.invocation_mode='gateway'
                               THEN source.gateway_service_id ELSE source.id END
                            AS effective_service_id
                   FROM interface_forwarding_interfaces AS interface
                   JOIN interface_forwarding_services AS source
                     ON source.id=interface.service_id
                   WHERE interface.workspace_id=%s
                     AND source.invocation_mode <> 'disabled'
                   ORDER BY interface.id""",
                (payload.workspace_id,),
            )
            interfaces = list(cursor.fetchall())
            imported: list[dict[str, Any]] = []
            deduplicated: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []

            for index, capture in enumerate(payload.captures):
                capture_url = urlsplit(capture.url)
                if capture_url.scheme not in {"http", "https"} or not capture_url.netloc:
                    skipped.append({"index": index, "url": capture.url, "reason": "invalid_url"})
                    continue
                try:
                    capture_origin = self._url_origin(capture.url)
                except ValueError:
                    skipped.append({"index": index, "url": capture.url, "reason": "invalid_url"})
                    continue
                compatible_environments = [
                    environment
                    for environment in environments
                    if payload.allow_origin_mismatch
                    or self._browser_capture_origins_compatible(
                        capture_origin,
                        self._url_origin(str(environment["base_url"])),
                    )
                ]
                if not compatible_environments:
                    skipped.append(
                        {"index": index, "url": capture.url, "reason": "origin_mismatch"}
                    )
                    continue

                matches: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
                for environment in compatible_environments:
                    base_url = str(environment["base_url"])
                    for interface in interfaces:
                        if str(
                            interface["method"]
                        ).upper() != capture.method or not self._capture_matches_interface(
                            captured_path=capture_url.path,
                            interface_path=str(interface["path"]),
                            base_url=base_url,
                        ):
                            continue
                        interface_id = str(interface["id"])
                        candidate = (interface, environment)
                        current = matches.get(interface_id)
                        if current is None or self._browser_environment_rank(*candidate) < (
                            self._browser_environment_rank(*current)
                        ):
                            matches[interface_id] = candidate
                if matches:
                    ranks = {
                        key: self._browser_match_rank(capture_url.path, *candidate)
                        for key, candidate in matches.items()
                    }
                    best = min(ranks.values())
                    matches = {
                        key: candidate for key, candidate in matches.items() if ranks[key] == best
                    }
                if len(matches) != 1:
                    skipped.append(
                        {
                            "index": index,
                            "url": capture.url,
                            "reason": (
                                "interface_not_found" if not matches else "ambiguous_interface"
                            ),
                            "candidate_interface_ids": sorted(matches),
                        }
                    )
                    continue

                interface, environment = next(iter(matches.values()))
                uses_selected_environment = (
                    interface["effective_service_id"] == environment["service_id"]
                )
                query = self._query_payload(capture.url)
                request_payload = {
                    "query": query,
                    "body": redact_value(capture.request_body),
                }
                request_body, request_truncated, _request_bytes = self._bounded_json(
                    request_payload,
                    _BROWSER_REQUEST_MAX_BYTES,
                )
                response_body, response_truncated, response_bytes = self._bounded_json(
                    redact_value(capture.response_body),
                    _BROWSER_RESPONSE_MAX_BYTES,
                )
                success = capture.status_code is not None and 200 <= capture.status_code < 400
                log_id = str(uuid4())
                environment_name = (
                    f"{environment['workspace_environment_name']} · {environment['name']}"
                    if uses_selected_environment
                    else f"{environment['workspace_environment_name']} · 浏览器录制"
                )
                identity_name = (
                    identity["login_account"] if identity and uses_selected_environment else None
                )
                identity_role = (
                    identity["role_name"] if identity and uses_selected_environment else ""
                )
                address_id = environment["id"] if uses_selected_environment else None
                identity_id = identity["id"] if identity and uses_selected_environment else None
                common_values = (
                    log_id,
                    payload.workspace_id,
                    interface["id"],
                    environment_name,
                    identity_name,
                    identity_role,
                    self._safe_capture_url(capture.url),
                    request_body,
                    response_body,
                    capture.status_code,
                    success,
                    capture.duration_ms,
                    environment["environment_key"],
                    address_id,
                    identity_id,
                    response_bytes,
                    request_truncated or response_truncated,
                    capture.capture_id,
                )
                daily_read = interface["operation_kind"] == "read"
                if daily_read:
                    cursor.execute(
                        """INSERT INTO interface_forwarding_logs
                        (id, workspace_id, interface_id, environment_name, identity_name,
                         identity_role, request_url, request_body, response_body, status_code,
                         success, duration_ms, environment_key, address_id, identity_id,
                         response_bytes, response_truncated, browser_capture_id,
                         browser_capture_day, browser_observed_count, browser_success_count,
                         browser_first_seen_at, browser_last_seen_at,
                         browser_last_observed_capture_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date,
                                1,CASE WHEN %s THEN 1 ELSE 0 END,
                                CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,%s)
                        ON CONFLICT (workspace_id, environment_key, interface_id,
                                     browser_capture_day)
                        WHERE browser_capture_day IS NOT NULL DO UPDATE SET
                        browser_observed_count=
                            COALESCE(interface_forwarding_logs.browser_observed_count,1)
                            + CASE WHEN interface_forwarding_logs.browser_last_observed_capture_id
                                             IS NOT DISTINCT FROM EXCLUDED.browser_capture_id
                                   THEN 0 ELSE 1 END,
                        browser_success_count=
                            COALESCE(interface_forwarding_logs.browser_success_count,
                                     CASE WHEN interface_forwarding_logs.success THEN 1 ELSE 0 END)
                            + CASE
                                WHEN interface_forwarding_logs.browser_last_observed_capture_id
                                         IS NOT DISTINCT FROM EXCLUDED.browser_capture_id
                                THEN CASE
                                    WHEN interface_forwarding_logs.browser_capture_id
                                             = EXCLUDED.browser_capture_id
                                    THEN (CASE WHEN EXCLUDED.success THEN 1 ELSE 0 END)
                                       - (CASE WHEN interface_forwarding_logs.success
                                               THEN 1 ELSE 0 END)
                                    ELSE 0
                                  END
                                WHEN EXCLUDED.success THEN 1 ELSE 0
                              END,
                        browser_last_seen_at=CURRENT_TIMESTAMP,
                        browser_last_observed_capture_id=EXCLUDED.browser_capture_id,
                        environment_name=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.environment_name
                            ELSE interface_forwarding_logs.environment_name END,
                        identity_name=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.identity_name
                            ELSE interface_forwarding_logs.identity_name END,
                        identity_role=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.identity_role
                            ELSE interface_forwarding_logs.identity_role END,
                        request_url=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.request_url
                            ELSE interface_forwarding_logs.request_url END,
                        request_body=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.request_body
                            ELSE interface_forwarding_logs.request_body END,
                        response_body=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.response_body
                            ELSE interface_forwarding_logs.response_body END,
                        status_code=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.status_code
                            ELSE interface_forwarding_logs.status_code END,
                        success=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.success
                            ELSE interface_forwarding_logs.success END,
                        duration_ms=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.duration_ms
                            ELSE interface_forwarding_logs.duration_ms END,
                        address_id=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.address_id
                            ELSE interface_forwarding_logs.address_id END,
                        identity_id=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.identity_id
                            ELSE interface_forwarding_logs.identity_id END,
                        response_bytes=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.response_bytes
                            ELSE interface_forwarding_logs.response_bytes END,
                        response_truncated=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.response_truncated
                            ELSE interface_forwarding_logs.response_truncated END,
                        browser_capture_id=CASE
                            WHEN interface_forwarding_logs.browser_capture_id
                                   = EXCLUDED.browser_capture_id
                                 OR NOT interface_forwarding_logs.success
                            THEN EXCLUDED.browser_capture_id
                            ELSE interface_forwarding_logs.browser_capture_id END
                        RETURNING id,browser_capture_id,browser_observed_count,
                                  browser_success_count""",
                        (*common_values, success, capture.capture_id),
                    )
                    saved_log = cursor.fetchone()
                    log_id = str(saved_log["id"])
                    retained_capture_id = str(saved_log["browser_capture_id"])
                    cursor.execute(
                        """DELETE FROM browser_interface_captures
                        WHERE workspace_id=%s AND log_id=%s AND capture_id<>%s""",
                        (payload.workspace_id, log_id, retained_capture_id),
                    )
                else:
                    cursor.execute(
                        """INSERT INTO interface_forwarding_logs
                        (id, workspace_id, interface_id, environment_name, identity_name,
                         identity_role, request_url, request_body, response_body, status_code,
                         success, duration_ms, environment_key, address_id, identity_id,
                         response_bytes, response_truncated, browser_capture_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (workspace_id, browser_capture_id)
                        WHERE browser_capture_id IS NOT NULL DO UPDATE SET
                        interface_id=EXCLUDED.interface_id,
                        request_body=EXCLUDED.request_body,response_body=EXCLUDED.response_body,
                        status_code=EXCLUDED.status_code,success=EXCLUDED.success,
                        duration_ms=EXCLUDED.duration_ms,response_bytes=EXCLUDED.response_bytes,
                        response_truncated=EXCLUDED.response_truncated
                        RETURNING id,browser_capture_id""",
                        common_values,
                    )
                    saved_log = cursor.fetchone()
                    log_id = str(saved_log["id"])
                    retained_capture_id = str(saved_log["browser_capture_id"])

                item = {
                    "index": index,
                    "log_id": log_id,
                    "interface_id": str(interface["id"]),
                    "interface_name": str(interface["name"]),
                    "method": capture.method,
                    "path": str(interface["path"]),
                    "status_code": capture.status_code,
                    "success": success,
                    "truncated": request_truncated or response_truncated,
                    "daily_read": daily_read,
                }
                if daily_read and retained_capture_id != capture.capture_id:
                    item.update(
                        {
                            "reason": "daily_read_deduplicated",
                            "retained_capture_id": retained_capture_id,
                            "observed_count": saved_log["browser_observed_count"],
                            "success_count": saved_log["browser_success_count"],
                        }
                    )
                    deduplicated.append(item)
                else:
                    if daily_read:
                        item.update(
                            {
                                "observed_count": saved_log["browser_observed_count"],
                                "success_count": saved_log["browser_success_count"],
                            }
                        )
                    imported.append(item)

        return {
            "workspace_id": payload.workspace_id,
            "environment_id": payload.environment_id,
            "environment_key": payload.environment_key or environments[0]["environment_key"],
            "captured_count": len(payload.captures),
            "imported_count": len(imported),
            "deduplicated_count": len(deduplicated),
            "skipped_count": len(skipped),
            "imported": imported,
            "deduplicated": deduplicated,
            "skipped": skipped,
        }

    @staticmethod
    def _browser_match_rank(captured_path: str, interface: dict, environment: dict) -> tuple:
        path = str(interface["path"])
        expected = urlsplit(
            urljoin(str(environment["base_url"]).rstrip("/") + "/", path.lstrip("/"))
        ).path
        direct = any(
            InterfaceForwardingService._path_template_matches(p, captured_path)
            for p in (path, expected)
        )
        templated = bool(re.search(r"\{[^{}]+\}", path))
        literal_segments = sum(bool(part) and "{" not in part for part in path.split("/"))
        # Explicit routes win over templates; suffix fallback remains lower confidence.
        return (
            int(not direct) * 2 + int(templated),
            -literal_segments,
            int(interface["effective_service_id"] != environment["service_id"]),
        )

    @staticmethod
    def _browser_environment_rank(
        interface: dict[str, Any], environment: dict[str, Any]
    ) -> tuple[int, str, str]:
        return (
            0 if interface["effective_service_id"] == environment["service_id"] else 1,
            str(environment["name"]).lower(),
            str(environment["id"]),
        )

    @staticmethod
    def _url_origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(url)
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme.lower() == "https" else 80
        return parsed.scheme.lower(), (parsed.hostname or "").lower(), port

    @staticmethod
    def _browser_capture_origins_compatible(
        captured: tuple[str, str, int | None],
        configured: tuple[str, str, int | None],
    ) -> bool:
        if captured == configured:
            return True
        loopback_hosts = {"localhost", "127.0.0.1", "::1"}
        return (
            captured[0] == configured[0] == "http"
            and captured[1] in loopback_hosts
            and configured[1] in loopback_hosts
        )

    @classmethod
    def _capture_matches_interface(
        cls,
        *,
        captured_path: str,
        interface_path: str,
        base_url: str,
    ) -> bool:
        expected_path = urlsplit(
            urljoin(base_url.rstrip("/") + "/", interface_path.lstrip("/"))
        ).path
        return (
            cls._path_template_matches(expected_path, captured_path)
            or (
                expected_path != interface_path
                and cls._path_template_matches(interface_path, captured_path)
            )
            or cls._path_template_matches_suffix(interface_path, captured_path)
        )

    @classmethod
    def _path_template_matches_suffix(cls, template: str, actual: str) -> bool:
        normalized_template = "/" + template.strip("/")
        normalized_actual = "/" + actual.strip("/")
        template_segments = normalized_template.strip("/").split("/")
        actual_segments = normalized_actual.strip("/").split("/")
        if len(actual_segments) < len(template_segments):
            return False
        return cls._path_template_matches(
            normalized_template,
            "/" + "/".join(actual_segments[-len(template_segments) :]),
        )

    @staticmethod
    def _path_template_matches(template: str, actual: str) -> bool:
        normalized_template = "/" + template.strip("/")
        normalized_actual = "/" + actual.strip("/")
        pieces: list[str] = []
        position = 0
        for match in re.finditer(r"\{[^{}]+\}", normalized_template):
            pieces.append(re.escape(normalized_template[position : match.start()]))
            pieces.append(r"[^/]+")
            position = match.end()
        pieces.append(re.escape(normalized_template[position:]))
        return re.fullmatch("".join(pieces), normalized_actual) is not None

    @staticmethod
    def _query_payload(url: str) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True):
            safe_value = redact_value(value, field_name=key)
            if key not in values:
                values[key] = safe_value
            elif isinstance(values[key], list):
                values[key].append(safe_value)
            else:
                values[key] = [values[key], safe_value]
        return values

    @classmethod
    def _safe_capture_url(cls, url: str) -> str:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
        query = urlencode(cls._query_payload(url), doseq=True)
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, query, ""))

    @staticmethod
    def _bounded_json(value: Any, max_bytes: int) -> tuple[str, bool, int]:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        encoded = serialized.encode("utf-8")
        if len(encoded) <= max_bytes:
            return serialized, False, len(encoded)
        preview = encoded[:max_bytes].decode("utf-8", errors="ignore")
        while True:
            bounded = json.dumps(
                {"_truncated": True, "preview": preview},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(bounded.encode("utf-8")) <= max_bytes:
                return bounded, True, len(encoded)
            preview = preview[:-1]

    def execute(self, interface_id: str, payload: InterfaceForwardingExecute) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, workspace_id, service_id, path, method
                FROM interface_forwarding_interfaces WHERE id=%s""",
                (interface_id,),
            )
            interface = cursor.fetchone()
            if not interface:
                raise InterfaceForwardingError("接口不存在")
            cursor.execute(
                """SELECT forwarding.id, forwarding.service_id, forwarding.name,
                          forwarding.environment_key, forwarding.base_url,
                          workspace.display_name AS workspace_environment_name
                FROM interface_forwarding_environments AS forwarding
                JOIN workspace_environments AS workspace
                  ON workspace.workspace_id=forwarding.workspace_id
                 AND workspace.environment_key=forwarding.environment_key
                WHERE forwarding.workspace_id=%s AND forwarding.id=%s""",
                (interface["workspace_id"], payload.environment_id),
            )
            environment = cursor.fetchone()
            if not environment:
                raise InterfaceForwardingError("转发地址不存在")
            if str(environment["service_id"] or "") != str(interface["service_id"]):
                raise InterfaceForwardingError("转发地址未映射到当前接口服务")
            identity = None
            if payload.identity_id:
                cursor.execute(
                    """SELECT id, login_account, role_name, request_header
                    FROM interface_forwarding_identities
                    WHERE id=%s AND environment_id=%s""",
                    (payload.identity_id, environment["id"]),
                )
                identity = cursor.fetchone()
                if not identity:
                    raise InterfaceForwardingError("请求身份不存在或不属于当前环境")

        headers: dict[str, str] = {"Accept": "application/json"}
        if identity and identity["request_header"].strip():
            raw_header = identity["request_header"].strip()
            try:
                parsed = json.loads(raw_header)
                if not isinstance(parsed, dict):
                    raise ValueError
                headers.update({str(key): str(value) for key, value in parsed.items()})
            except (json.JSONDecodeError, ValueError):
                headers["Authorization"] = raw_header
        body: Any = None
        if payload.request_body.strip():
            try:
                body = json.loads(payload.request_body)
            except json.JSONDecodeError as exc:
                raise InterfaceForwardingError("请求参数不是合法 JSON") from exc
        url = urljoin(environment["base_url"].rstrip("/") + "/", interface["path"].lstrip("/"))
        started = time.perf_counter()
        status_code: int | None = None
        success = False
        response_body = ""
        response_headers: dict[str, str] = {}
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.request(
                    interface["method"],
                    url,
                    headers=headers,
                    json=body if interface["method"] not in {"GET", "HEAD"} else None,
                    params=body
                    if interface["method"] in {"GET", "HEAD"} and isinstance(body, dict)
                    else None,
                )
            status_code = response.status_code
            success = response.is_success
            response_headers = dict(response.headers)
            try:
                response_body = json.dumps(response.json(), ensure_ascii=False, indent=2)
            except ValueError:
                response_body = response.text
        except httpx.HTTPError as exc:
            response_body = f"请求失败：{exc.__class__.__name__}: {exc}"
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO interface_forwarding_params
                (interface_id, environment_id, identity_id, request_body, response_body, updated_at)
                VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
                ON CONFLICT (interface_id) DO UPDATE SET environment_id=EXCLUDED.environment_id,
                identity_id=EXCLUDED.identity_id, request_body=EXCLUDED.request_body,
                response_body=EXCLUDED.response_body, updated_at=CURRENT_TIMESTAMP""",
                (
                    interface_id,
                    environment["id"],
                    payload.identity_id,
                    payload.request_body,
                    response_body,
                ),
            )
            cursor.execute(
                """INSERT INTO interface_forwarding_logs
                (id, workspace_id, interface_id, environment_name, identity_name,
                 identity_role, request_url, request_body, response_body, status_code,
                 success, duration_ms)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(uuid4()),
                    interface["workspace_id"],
                    interface_id,
                    f"{environment['workspace_environment_name']} · {environment['name']}",
                    identity["login_account"] if identity else None,
                    identity["role_name"] if identity else "",
                    url,
                    payload.request_body,
                    response_body,
                    status_code,
                    success,
                    duration_ms,
                ),
            )
        return {
            "success": success,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "response_body": response_body,
            "response_headers": response_headers,
        }

    def _update_returning(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                if not row:
                    raise InterfaceForwardingError("记录不存在")
                return row
        except psycopg.errors.UniqueViolation as exc:
            raise InterfaceForwardingError("同一工作空间内名称或接口已存在") from exc

    def _delete(self, table: str, record_id: str) -> None:
        allowed = {
            "interface_forwarding_services",
            "interface_forwarding_interfaces",
            "interface_forwarding_environments",
            "interface_forwarding_identities",
        }
        if table not in allowed:
            raise InterfaceForwardingError("不支持的删除目标")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table} WHERE id=%s", (record_id,))
            if cursor.rowcount == 0:
                raise InterfaceForwardingError("记录不存在")
