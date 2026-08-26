from __future__ import annotations

import math
import re
from random import SystemRandom
from typing import Any, Literal
from uuid import uuid4

import psycopg
from psycopg.errors import ForeignKeyViolation, UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from context_router.database.errors import DatabaseAccessError, DatabaseConnectorError
from context_router.database.manager import ConnectorManager, ConnectorManagerError
from context_router.database.policy import (
    QueryPolicyError,
    SqlSafetyPolicy,
    policy_as_safety_context,
)
from context_router.database.result import ResultFormattingError, normalize_json_value
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
from context_router.schemas.value_mapping import ValueMappingWrite
from context_router.services.database_access import DatabaseAccessService

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")
_RANDOM = SystemRandom()


class ValueMappingError(RuntimeError):
    def __init__(self, message: str, *, code: str = "value_mapping_failed") -> None:
        super().__init__(message)
        self.code = code


class ValueMappingService:
    """Workspace-scoped business values and constrained database resolvers."""

    def __init__(
        self,
        *,
        database_url: str | None,
        database_access_service: DatabaseAccessService,
        connector_manager: ConnectorManager,
        sql_policy: SqlSafetyPolicy,
        task_repository: TaskReader,
    ) -> None:
        self._database_url = database_url
        self._database_access = database_access_service
        self._connectors = connector_manager
        self._sql_policy = sql_policy
        self._task_repository = task_repository

    def search_for_task(
        self,
        *,
        task_id: int,
        query: str | None,
        interface_id: str | None,
        location: str | None,
        parameter_path: str | None,
        limit: int,
    ) -> dict[str, object]:
        """Find published mappings by business term or an exact interface parameter."""
        workspace_id, environment = self._task_scope(task_id)
        normalized_query = (query or "").strip()
        normalized_interface_id = (interface_id or "").strip()
        normalized_parameter_path = (parameter_path or "").strip().strip(".")
        if not normalized_query and not normalized_interface_id:
            raise ValueMappingError(
                "关键词和接口 ID 至少需要提供一个",
                code="mapping_search_required",
            )
        if (location or normalized_parameter_path) and not normalized_interface_id:
            raise ValueMappingError(
                "按参数位置筛选时必须同时提供接口 ID",
                code="interface_id_required",
            )

        bounded_limit = max(1, min(limit, 20))
        where = ["mapping.workspace_id=%s", "mapping.status='published'"]
        parameters: list[object] = [workspace_id]
        if normalized_query:
            like = f"%{normalized_query}%"
            where.append(
                """(
                    mapping.value_key ILIKE %s
                    OR mapping.name ILIKE %s
                    OR mapping.description ILIKE %s
                    OR EXISTS (
                      SELECT 1 FROM interface_value_mapping_aliases AS alias
                      WHERE alias.mapping_id=mapping.id AND alias.alias ILIKE %s
                    )
                )"""
            )
            parameters.extend((like, like, like, like))
        if normalized_interface_id:
            binding_conditions = [
                "binding.mapping_id=mapping.id",
                "binding.interface_id=%s",
            ]
            parameters.append(normalized_interface_id)
            if location:
                binding_conditions.append("binding.location=%s")
                parameters.append(location)
            if normalized_parameter_path:
                binding_conditions.append("binding.parameter_path=%s")
                parameters.append(normalized_parameter_path)
            where.append(
                "EXISTS (SELECT 1 FROM interface_value_mapping_bindings AS binding WHERE "
                + " AND ".join(binding_conditions)
                + ")"
            )

        rank_sql = "0"
        rank_parameters: list[object] = []
        if normalized_query:
            rank_sql = """CASE
                WHEN lower(mapping.value_key)=lower(%s) OR lower(mapping.name)=lower(%s) THEN 0
                WHEN EXISTS (
                  SELECT 1 FROM interface_value_mapping_aliases AS alias
                  WHERE alias.mapping_id=mapping.id AND lower(alias.alias)=lower(%s)
                ) THEN 1
                WHEN mapping.value_key ILIKE %s OR mapping.name ILIKE %s THEN 2
                ELSE 3 END"""
            rank_parameters = [
                normalized_query,
                normalized_query,
                normalized_query,
                f"%{normalized_query}%",
                f"%{normalized_query}%",
            ]

        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""SELECT mapping.id, {rank_sql} AS relevance_rank
                    FROM interface_value_mappings AS mapping
                    WHERE {" AND ".join(where)}
                    ORDER BY relevance_rank, lower(mapping.name), mapping.id
                    LIMIT %s""",
                (*rank_parameters, *parameters, bounded_limit + 1),
            )
            rows = cursor.fetchall()
            mappings = [
                self._mcp_mapping(
                    self._mapping(cursor, str(row["id"])),
                    interface_id=normalized_interface_id or None,
                    location=location,
                    parameter_path=normalized_parameter_path or None,
                )
                for row in rows[:bounded_limit]
            ]
        return {
            "task_id": task_id,
            "workspace_id": workspace_id,
            "environment": environment,
            "query": normalized_query or None,
            "interface_id": normalized_interface_id or None,
            "mappings": mappings,
            "returned_count": len(mappings),
            "truncated": len(rows) > bounded_limit,
        }

    def resolve_for_task(
        self,
        mapping_id: str,
        *,
        task_id: int,
        environment: str | None,
        keyword: str,
        limit: int,
        selection: Literal["default", "random"] = "default",
    ) -> dict[str, object]:
        """Execute one saved resolver in the database environment captured by the task."""
        workspace_id, selected_environment = self._task_scope(task_id, environment)
        mapping = self.get(mapping_id)
        if mapping["workspace_id"] != workspace_id:
            raise ValueMappingError("映射不属于当前工作空间", code="workspace_mismatch")
        if mapping["status"] != "published":
            raise ValueMappingError("映射尚未发布，不能用于 MCP 取值", code="mapping_unpublished")
        normalized_keyword = keyword.strip()
        if normalized_keyword and not mapping["search_columns"]:
            raise ValueMappingError("当前映射还没有配置可搜索字段", code="search_unavailable")
        bounded_limit = max(1, min(limit, 10))
        candidate_pool_limit = 10 if selection == "random" else bounded_limit
        try:
            access = self._database_access.resolve(
                task_id=task_id,
                mcp_alias=str(mapping["database_alias"]),
                require_query=True,
            )
            candidates, elapsed_ms, truncated = self._execute_candidates(
                mapping,
                access=access,
                keyword=normalized_keyword,
                limit=candidate_pool_limit,
            )
        except DatabaseAccessError as exc:
            raise ValueMappingError(str(exc), code=exc.code) from exc
        selected_candidates = self._select_candidates(
            candidates,
            selection=selection,
            limit=bounded_limit,
        )
        return {
            "task_id": task_id,
            "mapping_id": mapping_id,
            "value_key": mapping["value_key"],
            "name": mapping["name"],
            "environment": selected_environment,
            "keyword": normalized_keyword,
            "selection": selection,
            "source": {
                "database_alias": mapping["database_alias"],
                "schema_name": mapping["schema_name"],
                "table_name": mapping["table_name"],
                "value_column": mapping["value_column"],
                "display_columns": mapping["display_columns"],
            },
            "next_action": {
                "mapping_source_is_resolved": True,
                "skip_schema_discovery": True,
                "visualization_mapping_id": mapping_id,
                "message": (
                    "候选值及来源已经解析；显示字段足够时直接保存数据可视化，"
                    "需要完整记录时可按 value_column 对候选 value 做一次有界只读查询，"
                    "不要再次搜索数据库对象或表关系。"
                ),
            },
            "candidates": selected_candidates,
            "returned_count": len(selected_candidates),
            "candidate_pool_count": len(candidates),
            "elapsed_ms": elapsed_ms,
            "truncated": truncated,
        }

    def source_for_task(self, mapping_id: str, *, task_id: int) -> dict[str, object]:
        """Return a published mapping source after checking the task Workspace boundary."""
        workspace_id, environment = self._task_scope(task_id, None)
        mapping = self.get(mapping_id)
        if mapping["workspace_id"] != workspace_id:
            raise ValueMappingError("映射不属于当前工作空间", code="workspace_mismatch")
        if mapping["status"] != "published":
            raise ValueMappingError("映射尚未发布，不能用于 MCP 取值", code="mapping_unpublished")
        schema_name = str(mapping["schema_name"] or "").strip()
        schema_source = "mapping"
        if not schema_name:
            try:
                access = self._database_access.resolve(
                    task_id=task_id,
                    mcp_alias=str(mapping["database_alias"]),
                )
            except DatabaseAccessError as exc:
                raise ValueMappingError(str(exc), code=exc.code) from exc
            allowed_schemas = tuple(access.policy.allowed_schemas)
            if len(allowed_schemas) == 1:
                schema_name = allowed_schemas[0]
                schema_source = "environment_allowed_schema"
            elif access.policy.engine in {"mysql", "mariadb", "clickhouse"}:
                schema_name = access.policy.current_database
                schema_source = "environment_database_namespace"
            else:
                raise ValueMappingError(
                    "映射未配置 Schema，且任务环境不能唯一确定真实 Schema",
                    code="mapping_schema_unresolved",
                )
        return {
            "mapping_id": mapping_id,
            "environment": environment,
            "database_alias": mapping["database_alias"],
            "schema_name": schema_name,
            "schema_source": schema_source,
            "table_name": mapping["table_name"],
            "value_column": mapping["value_column"],
        }

    def overview(self, workspace_id: str, keyword: str = "") -> dict[str, object]:
        normalized_keyword = keyword.strip()
        with self._connect() as connection, connection.cursor() as cursor:
            self._require_workspace(cursor, workspace_id)
            like = f"%{normalized_keyword}%"
            cursor.execute(
                """SELECT mapping.id
                   FROM interface_value_mappings AS mapping
                   WHERE mapping.workspace_id=%s
                     AND (
                       %s=''
                       OR mapping.name ILIKE %s
                       OR mapping.value_key ILIKE %s
                       OR mapping.description ILIKE %s
                       OR EXISTS (
                         SELECT 1 FROM interface_value_mapping_aliases AS alias
                         WHERE alias.mapping_id=mapping.id AND alias.alias ILIKE %s
                       )
                     )
                   ORDER BY CASE mapping.status WHEN 'published' THEN 0 ELSE 1 END,
                            lower(mapping.name), mapping.id""",
                (workspace_id, normalized_keyword, like, like, like, like),
            )
            mappings = [self._mapping(cursor, str(row["id"])) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT value, min(label) AS label
                   FROM (
                     SELECT lower(mcp_alias) AS value, logical_name AS label
                     FROM project_database_environment_mappings
                     WHERE workspace_id=%s
                     UNION ALL
                     SELECT lower(link.mcp_alias) AS value,
                            COALESCE(NULLIF(link.alias, ''), link.mcp_alias) AS label
                     FROM project_databases AS link
                     WHERE link.workspace_id=%s
                       AND link.mcp_alias IS NOT NULL
                       AND link.readonly=true
                       AND NOT EXISTS (
                         SELECT 1 FROM project_database_environment_mappings AS mapping
                         WHERE mapping.workspace_id=%s
                       )
                   ) AS aliases
                   GROUP BY value
                   ORDER BY value""",
                (workspace_id, workspace_id, workspace_id),
            )
            databases = [dict(row) for row in cursor.fetchall()]
        return {
            "workspace_id": workspace_id,
            "mappings": mappings,
            "database_aliases": databases,
        }

    def get(self, mapping_id: str) -> dict[str, object]:
        with self._connect() as connection, connection.cursor() as cursor:
            return self._mapping(cursor, mapping_id)

    def create(self, payload: ValueMappingWrite) -> dict[str, object]:
        mapping_id = str(uuid4())
        with self._connect() as connection, connection.cursor() as cursor:
            self._validate(cursor, payload)
            try:
                cursor.execute(
                    """INSERT INTO interface_value_mappings
                    (id, workspace_id, value_key, name, description, status, resolver_type,
                     database_alias, schema_name, table_name, value_column, search_columns,
                     display_columns, filter_conditions)
                    VALUES (%s,%s,%s,%s,%s,%s,'database_column',%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        mapping_id,
                        payload.workspace_id,
                        payload.value_key,
                        payload.name,
                        payload.description,
                        payload.status,
                        payload.database_alias.casefold(),
                        payload.schema_name,
                        payload.table_name,
                        payload.value_column,
                        Jsonb(payload.search_columns),
                        Jsonb(payload.display_columns),
                        Jsonb(payload.filters),
                    ),
                )
                self._replace_aliases(cursor, mapping_id, payload.workspace_id, payload.aliases)
                self._replace_bindings(cursor, mapping_id, payload.bindings)
            except (UniqueViolation, ForeignKeyViolation) as exc:
                raise self._constraint_error(exc) from exc
            return self._mapping(cursor, mapping_id)

    def update(self, mapping_id: str, payload: ValueMappingWrite) -> dict[str, object]:
        with self._connect() as connection, connection.cursor() as cursor:
            current = self._mapping(cursor, mapping_id)
            if current["workspace_id"] != payload.workspace_id:
                raise ValueMappingError("映射不能移动到其他工作空间", code="workspace_mismatch")
            self._validate(cursor, payload)
            try:
                cursor.execute(
                    """UPDATE interface_value_mappings
                       SET value_key=%s, name=%s, description=%s, status=%s,
                           database_alias=%s, schema_name=%s, table_name=%s,
                           value_column=%s, search_columns=%s, display_columns=%s,
                           filter_conditions=%s, version=version+1,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE id=%s""",
                    (
                        payload.value_key,
                        payload.name,
                        payload.description,
                        payload.status,
                        payload.database_alias.casefold(),
                        payload.schema_name,
                        payload.table_name,
                        payload.value_column,
                        Jsonb(payload.search_columns),
                        Jsonb(payload.display_columns),
                        Jsonb(payload.filters),
                        mapping_id,
                    ),
                )
                self._replace_aliases(cursor, mapping_id, payload.workspace_id, payload.aliases)
                self._replace_bindings(cursor, mapping_id, payload.bindings)
            except (UniqueViolation, ForeignKeyViolation) as exc:
                raise self._constraint_error(exc) from exc
            return self._mapping(cursor, mapping_id)

    def delete(self, mapping_id: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM interface_value_mappings WHERE id=%s RETURNING id",
                (mapping_id,),
            )
            if not cursor.fetchone():
                raise ValueMappingError("映射不存在", code="mapping_not_found")

    def search_interfaces(
        self, *, workspace_id: str, keyword: str, limit: int
    ) -> dict[str, object]:
        normalized_keyword = keyword.strip()
        like = f"%{normalized_keyword}%"
        with self._connect() as connection, connection.cursor() as cursor:
            self._require_workspace(cursor, workspace_id)
            cursor.execute(
                """SELECT interface.id, interface.name, interface.controller_name,
                          interface.path, interface.method, interface.request_contract,
                          service.name AS service_name
                   FROM interface_forwarding_interfaces AS interface
                   JOIN interface_forwarding_services AS service
                     ON service.id=interface.service_id
                   WHERE interface.workspace_id=%s
                     AND (
                       %s=''
                       OR interface.name ILIKE %s
                       OR interface.path ILIKE %s
                       OR interface.controller_name ILIKE %s
                       OR service.name ILIKE %s
                     )
                   ORDER BY lower(service.name), lower(interface.name), interface.path
                   LIMIT %s""",
                (
                    workspace_id,
                    normalized_keyword,
                    like,
                    like,
                    like,
                    like,
                    max(1, min(limit, 100)),
                ),
            )
            interfaces = [self._interface_candidate(row) for row in cursor.fetchall()]
        return {
            "workspace_id": workspace_id,
            "keyword": normalized_keyword,
            "returned_count": len(interfaces),
            "interfaces": interfaces,
        }

    def preview(
        self,
        mapping_id: str,
        *,
        workspace_id: str,
        environment: str,
        keyword: str,
        limit: int,
    ) -> dict[str, object]:
        mapping = self.get(mapping_id)
        if mapping["workspace_id"] != workspace_id:
            raise ValueMappingError("映射不属于当前工作空间", code="workspace_mismatch")
        if keyword.strip() and not mapping["search_columns"]:
            raise ValueMappingError("当前映射还没有配置可搜索字段", code="search_unavailable")
        try:
            access = self._database_access.resolve_workspace_database(
                workspace_id=workspace_id,
                environment=environment,
                mcp_alias=str(mapping["database_alias"]),
                require_query=True,
            )
            sql = self._preview_sql(
                mapping,
                engine=access.database.engine,
                keyword=keyword.strip(),
                limit=max(1, min(limit, 20)),
            )
            validated = self._sql_policy.validate(
                sql,
                policy_as_safety_context(access.policy),
            )
            with self._connectors.lease(access.spec) as connector:
                result = connector.execute_query(validated.sql, access.policy)
        except DatabaseAccessError as exc:
            raise ValueMappingError(str(exc), code=exc.code) from exc
        except (
            QueryPolicyError,
            ConnectorManagerError,
            DatabaseConnectorError,
            ResultFormattingError,
        ) as exc:
            raise ValueMappingError(
                "取值预览失败，请检查数据库字段与过滤条件",
                code=getattr(exc, "code", "preview_failed"),
            ) from exc

        display_columns = list(mapping["display_columns"])
        candidates: list[dict[str, object]] = []
        for raw_row in result.rows:
            row = list(raw_row)
            if not row:
                continue
            value = normalize_json_value(row[0])
            labels = {
                column: normalize_json_value(row[index + 1])
                for index, column in enumerate(display_columns)
                if index + 1 < len(row)
            }
            label_parts = [str(item) for item in labels.values() if item not in (None, "")]
            candidates.append(
                {
                    "value": value,
                    "label": " · ".join(label_parts) if label_parts else str(value),
                    "labels": labels,
                }
            )
            if len(candidates) >= limit:
                break
        return {
            "mapping_id": mapping_id,
            "value_key": mapping["value_key"],
            "environment": environment,
            "database_alias": mapping["database_alias"],
            "keyword": keyword.strip(),
            "candidates": candidates,
            "returned_count": len(candidates),
            "elapsed_ms": max(0, result.elapsed_ms),
            "truncated": bool(result.truncated),
        }

    def _task_scope(
        self,
        task_id: int,
        explicit_environment: str | None = None,
    ) -> tuple[str, str]:
        try:
            task = self._task_repository.get_task(task_id)
        except TaskRepositoryError as exc:
            raise ValueMappingError("任务不存在，请重新 prepare", code="task_not_found") from exc
        if getattr(task, "scope", "project") != "workspace" or not task.workspace_id:
            raise ValueMappingError(
                "业务值映射仅支持工作空间任务，请重新 prepare",
                code="workspace_task_required",
            )
        task_environment = (task.database_environment or "local").strip().casefold()
        requested_environment = (explicit_environment or "").strip().casefold()
        if requested_environment and requested_environment != task_environment:
            raise ValueMappingError(
                "显式环境与任务环境不一致，请使用目标环境重新 prepare",
                code="environment_mismatch",
            )
        return task.workspace_id, task_environment

    @staticmethod
    def _mcp_mapping(
        mapping: dict[str, object],
        *,
        interface_id: str | None,
        location: str | None,
        parameter_path: str | None,
    ) -> dict[str, object]:
        bindings = [
            binding
            for binding in mapping["bindings"]
            if isinstance(binding, dict)
            and (interface_id is None or binding.get("interface_id") == interface_id)
            and (location is None or binding.get("location") == location)
            and (parameter_path is None or binding.get("parameter_path") == parameter_path)
        ]
        visible_bindings = bindings[:20]
        if interface_id is None:
            visible_bindings = []
        return {
            "mapping_id": mapping["id"],
            "value_key": mapping["value_key"],
            "name": mapping["name"],
            "description": mapping["description"],
            "aliases": mapping["aliases"],
            "resolver": {
                "type": mapping["resolver_type"],
                "database_alias": mapping["database_alias"],
                "schema_name": mapping["schema_name"],
                "table_name": mapping["table_name"],
                "value_column": mapping["value_column"],
                "search_columns": mapping["search_columns"],
                "display_columns": mapping["display_columns"],
                "filters": mapping["filters"],
            },
            "binding_count": len(bindings),
            "bindings_included": interface_id is not None,
            "bindings": visible_bindings,
            "bindings_truncated": len(bindings) > len(visible_bindings),
        }

    @staticmethod
    def _select_candidates(
        candidates: list[dict[str, object]],
        *,
        selection: Literal["default", "random"],
        limit: int,
    ) -> list[dict[str, object]]:
        bounded_limit = max(1, min(limit, 10))
        if selection == "default":
            return candidates[:bounded_limit]
        if selection == "random":
            sample_size = min(bounded_limit, len(candidates))
            return _RANDOM.sample(candidates, sample_size)
        raise ValueMappingError("不支持的候选选择策略", code="invalid_selection")

    def _execute_candidates(
        self,
        mapping: dict[str, object],
        *,
        access: Any,
        keyword: str,
        limit: int,
    ) -> tuple[list[dict[str, object]], int, bool]:
        try:
            sql = self._preview_sql(
                mapping,
                engine=access.database.engine,
                keyword=keyword,
                limit=min(limit + 1, 20),
            )
            validated = self._sql_policy.validate(
                sql,
                policy_as_safety_context(access.policy),
            )
            with self._connectors.lease(access.spec) as connector:
                result = connector.execute_query(validated.sql, access.policy)
        except (
            QueryPolicyError,
            ConnectorManagerError,
            DatabaseConnectorError,
            ResultFormattingError,
        ) as exc:
            raise ValueMappingError(
                "业务值解析失败，请检查映射的数据库字段与过滤条件",
                code=getattr(exc, "code", "value_resolution_failed"),
            ) from exc

        display_columns = list(mapping["display_columns"])
        candidates: list[dict[str, object]] = []
        for raw_row in result.rows[:limit]:
            row = list(raw_row)
            if not row:
                continue
            value = normalize_json_value(row[0])
            labels = {
                column: normalize_json_value(row[index + 1])
                for index, column in enumerate(display_columns)
                if index + 1 < len(row)
            }
            label_parts = [str(item) for item in labels.values() if item not in (None, "")]
            candidates.append(
                {
                    "value": value,
                    "label": " · ".join(label_parts) if label_parts else str(value),
                    "labels": labels,
                }
            )
        return (
            candidates,
            max(0, result.elapsed_ms),
            bool(result.truncated) or len(result.rows) > limit,
        )

    def _validate(self, cursor: Any, payload: ValueMappingWrite) -> None:
        self._require_workspace(cursor, payload.workspace_id)
        cursor.execute(
            """SELECT 1
               FROM project_database_environment_mappings
               WHERE workspace_id=%s AND lower(mcp_alias)=lower(%s)
               UNION ALL
               SELECT 1 FROM project_databases AS link
               WHERE link.workspace_id=%s AND lower(link.mcp_alias)=lower(%s)
                 AND link.readonly=true
                 AND NOT EXISTS (
                   SELECT 1 FROM project_database_environment_mappings AS mapping
                   WHERE mapping.workspace_id=%s
                 )
               LIMIT 1""",
            (
                payload.workspace_id,
                payload.database_alias,
                payload.workspace_id,
                payload.database_alias,
                payload.workspace_id,
            ),
        )
        if not cursor.fetchone():
            raise ValueMappingError(
                "当前工作空间没有这个只读数据库别名",
                code="database_alias_not_found",
            )
        identifiers = [
            payload.table_name,
            payload.value_column,
            *payload.search_columns,
            *payload.display_columns,
            *payload.filters,
        ]
        if payload.schema_name:
            identifiers.append(payload.schema_name)
        invalid = [item for item in identifiers if not _IDENTIFIER.fullmatch(item)]
        if invalid:
            raise ValueMappingError(
                f"数据库标识符格式无效：{invalid[0]}",
                code="invalid_identifier",
            )
        for value in payload.filters.values():
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueMappingError(
                    "固定过滤条件只允许字符串、数字、布尔值或 null",
                    code="invalid_filter",
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueMappingError("固定过滤条件不能使用非有限数字", code="invalid_filter")
        for binding in payload.bindings:
            cursor.execute(
                """SELECT path, request_contract
                   FROM interface_forwarding_interfaces
                   WHERE id=%s AND workspace_id=%s""",
                (binding.interface_id, payload.workspace_id),
            )
            interface = cursor.fetchone()
            if not interface:
                raise ValueMappingError("绑定的接口不存在", code="interface_not_found")
            if not self._has_parameter(
                interface["request_contract"] or {},
                str(interface["path"]),
                binding.location,
                binding.parameter_path,
            ):
                raise ValueMappingError(
                    f"接口没有参数 {binding.location}.{binding.parameter_path}",
                    code="parameter_not_found",
                )

    def _mapping(self, cursor: Any, mapping_id: str) -> dict[str, object]:
        cursor.execute(
            """SELECT id, workspace_id, value_key, name, description, status,
                      resolver_type, database_alias, schema_name, table_name,
                      value_column, search_columns, display_columns, filter_conditions,
                      version, created_at, updated_at
               FROM interface_value_mappings WHERE id=%s""",
            (mapping_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueMappingError("映射不存在", code="mapping_not_found")
        cursor.execute(
            """SELECT alias FROM interface_value_mapping_aliases
               WHERE mapping_id=%s ORDER BY lower(alias), id""",
            (mapping_id,),
        )
        aliases = [str(item["alias"]) for item in cursor.fetchall()]
        cursor.execute(
            """SELECT binding.id, binding.interface_id, binding.location,
                      binding.parameter_path, binding.required,
                      interface.name AS interface_name, interface.path AS interface_path,
                      interface.method, interface.controller_name,
                      service.name AS service_name
               FROM interface_value_mapping_bindings AS binding
               JOIN interface_forwarding_interfaces AS interface
                 ON interface.id=binding.interface_id
               JOIN interface_forwarding_services AS service
                 ON service.id=interface.service_id
               WHERE binding.mapping_id=%s
               ORDER BY lower(service.name), lower(interface.name),
                        binding.location, binding.parameter_path""",
            (mapping_id,),
        )
        result = dict(row)
        result["aliases"] = aliases
        result["filters"] = result.pop("filter_conditions") or {}
        result["bindings"] = [dict(item) for item in cursor.fetchall()]
        result["binding_count"] = len(result["bindings"])
        result["created_at"] = self._iso(result["created_at"])
        result["updated_at"] = self._iso(result["updated_at"])
        return result

    @staticmethod
    def _replace_aliases(
        cursor: Any, mapping_id: str, workspace_id: str, aliases: list[str]
    ) -> None:
        cursor.execute(
            "DELETE FROM interface_value_mapping_aliases WHERE mapping_id=%s",
            (mapping_id,),
        )
        for alias in aliases:
            cursor.execute(
                """INSERT INTO interface_value_mapping_aliases
                   (id, workspace_id, mapping_id, alias) VALUES (%s,%s,%s,%s)""",
                (str(uuid4()), workspace_id, mapping_id, alias),
            )

    @staticmethod
    def _replace_bindings(cursor: Any, mapping_id: str, bindings: list[Any]) -> None:
        cursor.execute(
            "DELETE FROM interface_value_mapping_bindings WHERE mapping_id=%s",
            (mapping_id,),
        )
        for binding in bindings:
            cursor.execute(
                """INSERT INTO interface_value_mapping_bindings
                   (id, mapping_id, interface_id, location, parameter_path, required)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (
                    str(uuid4()),
                    mapping_id,
                    binding.interface_id,
                    binding.location,
                    binding.parameter_path,
                    binding.required,
                ),
            )

    @classmethod
    def _interface_candidate(cls, row: dict[str, Any]) -> dict[str, object]:
        result = {
            "id": row["id"],
            "name": row["name"],
            "controller_name": row["controller_name"],
            "path": row["path"],
            "method": row["method"],
            "service_name": row["service_name"],
            "parameters": cls._parameters(row["request_contract"] or {}, str(row["path"])),
        }
        return result

    @classmethod
    def _parameters(cls, contract: dict[str, Any], path: str) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for location in ("path", "query"):
            schema = contract.get(location, {})
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            required = set(schema.get("required", [])) if isinstance(schema, dict) else set()
            if isinstance(properties, dict):
                for name, raw_field in properties.items():
                    field = raw_field if isinstance(raw_field, dict) else {}
                    result.append(
                        {
                            "location": location,
                            "parameter_path": str(name),
                            "required": name in required,
                            "type": str(field.get("type") or "unknown"),
                            "description": str(field.get("description") or "")[:240],
                        }
                    )
        body = contract.get("body", {})
        if isinstance(body, dict):
            cls._append_body_parameters(result, body, prefix="", required=True)
        existing_path = {
            str(item["parameter_path"]) for item in result if item["location"] == "path"
        }
        for name in _PATH_PARAMETER.findall(path):
            if name not in existing_path:
                result.append(
                    {
                        "location": "path",
                        "parameter_path": name,
                        "required": True,
                        "type": "string",
                        "description": "",
                    }
                )
        return result

    @classmethod
    def _append_body_parameters(
        cls,
        result: list[dict[str, object]],
        schema: dict[str, Any],
        *,
        prefix: str,
        required: bool,
    ) -> None:
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            if prefix:
                result.append(
                    {
                        "location": "body",
                        "parameter_path": prefix,
                        "required": required,
                        "type": str(schema.get("type") or "unknown"),
                        "description": str(schema.get("description") or "")[:240],
                    }
                )
            return
        required_names = set(schema.get("required", []))
        for name, raw_field in properties.items():
            field = raw_field if isinstance(raw_field, dict) else {}
            parameter_path = f"{prefix}.{name}" if prefix else str(name)
            field_required = required and name in required_names
            nested = field
            array_suffix = ""
            if field.get("type") == "array" and isinstance(field.get("items"), dict):
                nested = field["items"]
                array_suffix = "[]"
            if isinstance(nested.get("properties"), dict):
                cls._append_body_parameters(
                    result,
                    nested,
                    prefix=f"{parameter_path}{array_suffix}",
                    required=field_required,
                )
                continue
            result.append(
                {
                    "location": "body",
                    "parameter_path": f"{parameter_path}{array_suffix}",
                    "required": field_required,
                    "type": str(field.get("type") or nested.get("type") or "unknown"),
                    "description": str(field.get("description") or "")[:240],
                }
            )

    @classmethod
    def _has_parameter(
        cls,
        contract: dict[str, Any],
        path: str,
        location: str,
        parameter_path: str,
    ) -> bool:
        return any(
            item["location"] == location and item["parameter_path"] == parameter_path
            for item in cls._parameters(contract, path)
        )

    @classmethod
    def _preview_sql(
        cls,
        mapping: dict[str, object],
        *,
        engine: str,
        keyword: str,
        limit: int,
    ) -> str:
        quote = "`" if engine in {"mysql", "mariadb", "doris", "clickhouse"} else '"'

        def identifier(value: object) -> str:
            text = str(value)
            if not _IDENTIFIER.fullmatch(text):
                raise ValueMappingError("映射包含无效数据库标识符", code="invalid_identifier")
            return f"{quote}{text}{quote}"

        table = identifier(mapping["table_name"])
        if mapping.get("schema_name"):
            table = f"{identifier(mapping['schema_name'])}.{table}"
        value_column = identifier(mapping["value_column"])
        display_columns = [identifier(item) for item in mapping["display_columns"]]
        select_parts = [f"{value_column} AS {identifier('_value')}"]
        select_parts.extend(
            f"{column} AS {identifier(f'_display_{index}')}"
            for index, column in enumerate(display_columns)
        )
        conditions: list[str] = []
        if keyword:
            literal = cls._literal(keyword)
            search_conditions = []
            for item in mapping["search_columns"]:
                column = identifier(item)
                if engine == "postgresql":
                    search_conditions.append(
                        f"CAST({column} AS TEXT) ILIKE '%' || {literal} || '%'"
                    )
                elif engine == "clickhouse":
                    search_conditions.append(
                        f"positionCaseInsensitiveUTF8(toString({column}), {literal}) > 0"
                    )
                else:
                    search_conditions.append(
                        f"CAST({column} AS CHAR) LIKE CONCAT('%', {literal}, '%')"
                    )
            conditions.append("(" + " OR ".join(search_conditions) + ")")
        for raw_column, raw_value in dict(mapping["filters"]).items():
            column = identifier(raw_column)
            conditions.append(
                f"{column} IS NULL"
                if raw_value is None
                else f"{column} = {cls._literal(raw_value)}"
            )
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return (
            f"SELECT {', '.join(select_parts)} FROM {table}{where} "
            f"ORDER BY {value_column} ASC LIMIT {max(1, min(limit, 20))}"
        )

    @staticmethod
    def _literal(value: object) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueMappingError("过滤值不能使用非有限数字", code="invalid_filter")
            return repr(value)
        escaped = str(value).replace("\\", "\\\\").replace("'", "''")
        return f"'{escaped}'"

    @staticmethod
    def _require_workspace(cursor: Any, workspace_id: str) -> None:
        cursor.execute("SELECT 1 FROM workspaces WHERE id=%s", (workspace_id,))
        if not cursor.fetchone():
            raise ValueMappingError("工作空间不存在", code="workspace_not_found")

    def _connect(self):
        if not self._database_url:
            raise ValueMappingError("控制面数据库尚未配置", code="database_unavailable")
        return psycopg.connect(self._database_url, row_factory=dict_row)

    @staticmethod
    def _constraint_error(exc: Exception) -> ValueMappingError:
        name = getattr(getattr(exc, "diag", None), "constraint_name", "")
        if name == "uq_interface_value_mappings_workspace_key_lower":
            return ValueMappingError("当前工作空间已存在相同 value_key", code="duplicate_key")
        if name == "uq_interface_value_mapping_aliases_workspace_alias_lower":
            return ValueMappingError("当前工作空间已存在相同关键词别名", code="duplicate_alias")
        if name == "uq_interface_value_mapping_bindings_parameter":
            return ValueMappingError("这个接口参数已经绑定其他业务值", code="duplicate_binding")
        return ValueMappingError("映射保存失败，请检查关联记录", code="mapping_conflict")

    @staticmethod
    def _iso(value: Any) -> str | None:
        return value.isoformat() if value is not None else None
