from __future__ import annotations

import hashlib
import logging

from context_router.database.errors import DatabaseAccessError, DatabaseConnectorError
from context_router.database.manager import ConnectorManager, ConnectorManagerError
from context_router.database.policy import (
    QueryPolicyError,
    SqlSafetyPolicy,
    policy_as_safety_context,
)
from context_router.database.result import DatabaseResultFormatter, ResultFormattingError
from context_router.repositories.database_call_repository import (
    DatabaseCallRepositoryError,
    DatabaseCallStore,
    DatabaseCallWrite,
)
from context_router.services.database_access import DatabaseAccessService
from context_router.services.mcp_trace import current_tool_call_id

logger = logging.getLogger(__name__)


class DatabaseQueryService:
    def __init__(
        self,
        *,
        access_service: DatabaseAccessService,
        connector_manager: ConnectorManager,
        sql_policy: SqlSafetyPolicy,
        result_formatter: DatabaseResultFormatter,
        call_repository: DatabaseCallStore,
    ) -> None:
        self._access_service = access_service
        self._connector_manager = connector_manager
        self._sql_policy = sql_policy
        self._result_formatter = result_formatter
        self._call_repository = call_repository

    def execute(self, *, task_id: int, database: str, sql: str) -> dict[str, object]:
        normalized_sql = sql.strip()
        sql_hash = hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()
        access = None
        statement_type: str | None = None
        try:
            access = self._access_service.resolve(
                task_id=task_id,
                mcp_alias=database,
                require_query=True,
            )
            validated = self._sql_policy.validate(
                normalized_sql,
                policy_as_safety_context(access.policy),
            )
            statement_type = validated.statement_type
            envelope = {
                "task_id": task_id,
                "database": access.database.mcp_alias,
                "engine": access.database.engine,
            }
            with self._connector_manager.lease(access.spec) as connector:
                raw_result = connector.execute_query(validated.sql, access.policy)
            formatted = self._result_formatter.format_query(
                raw_result,
                access.policy,
                envelope=envelope,
            )
            result = {**envelope, **formatted.as_dict()}
            self._record(
                DatabaseCallWrite(
                    task_id=task_id,
                    operation="execute_query",
                    database_alias=access.database.mcp_alias,
                    engine=access.database.engine,
                    statement_type=statement_type,
                    sql_sha256=sql_hash,
                    status="ok",
                    duration_ms=formatted.elapsed_ms,
                    returned_count=formatted.returned_rows,
                    result_bytes=formatted.result_bytes,
                    truncated=formatted.truncated,
                    tool_call_id=current_tool_call_id(),
                )
            )
            return result
        except DatabaseAccessError as exc:
            self._record_error(
                task_id=task_id,
                database=database,
                engine=access.database.engine if access is not None else "unknown",
                statement_type=statement_type,
                sql_hash=sql_hash,
                code=exc.code,
            )
            raise
        except (
            QueryPolicyError,
            ConnectorManagerError,
            DatabaseConnectorError,
            ResultFormattingError,
        ) as exc:
            code = getattr(exc, "code", "query_failed")
            self._record_error(
                task_id=task_id,
                database=access.database.mcp_alias if access is not None else database,
                engine=access.database.engine if access is not None else "unknown",
                statement_type=statement_type,
                sql_hash=sql_hash,
                code=code,
            )
            raise DatabaseAccessError(code, _public_query_message(code)) from exc
        except Exception as exc:
            self._record_error(
                task_id=task_id,
                database=access.database.mcp_alias if access is not None else database,
                engine=access.database.engine if access is not None else "unknown",
                statement_type=statement_type,
                sql_hash=sql_hash,
                code="query_failed",
            )
            raise DatabaseAccessError("query_failed", "数据库查询执行失败") from exc

    def _record_error(
        self,
        *,
        task_id: int,
        database: str,
        engine: str,
        statement_type: str | None,
        sql_hash: str,
        code: str,
    ) -> None:
        if task_id < 1 or not database:
            return
        self._record(
            DatabaseCallWrite(
                task_id=task_id,
                operation="execute_query",
                database_alias=database[:64],
                engine=engine[:32] or "unknown",
                statement_type=statement_type,
                sql_sha256=sql_hash,
                status="error",
                error_code=code[:64],
                tool_call_id=current_tool_call_id(),
            )
        )

    def _record(self, call: DatabaseCallWrite) -> None:
        try:
            self._call_repository.create_call(call)
        except DatabaseCallRepositoryError:
            logger.warning("Unable to persist database query metadata")


def _public_query_message(code: str) -> str:
    return {
        "query_rejected": "SQL 不符合当前项目的只读或数据库范围策略",
        "query_timeout": "数据库查询超时",
        "query_cancelled": "数据库查询已取消",
        "connection_failed": "数据库当前无法连接",
        "result_cell_too_large": "单个查询结果字段超过响应限制",
        "result_metadata_too_large": "查询列信息超过响应限制",
        "engine_not_supported": "这个数据库类型暂不支持只读查询",
    }.get(code, "数据库查询执行失败")
