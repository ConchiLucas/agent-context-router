from __future__ import annotations

import logging

from context_router.config import Settings
from context_router.database.errors import DatabaseAccessError, DatabaseConnectorError
from context_router.database.manager import ConnectorManager, ConnectorManagerError
from context_router.database.models import DatabaseObjectType, SearchDetail, SearchObjectsRequest
from context_router.database.result import DatabaseResultFormatter, ResultFormattingError
from context_router.repositories.database_call_repository import (
    DatabaseCallRepositoryError,
    DatabaseCallStore,
    DatabaseCallWrite,
)
from context_router.services.database_access import DatabaseAccessService

logger = logging.getLogger(__name__)


class DatabaseCatalogService:
    def __init__(
        self,
        *,
        settings: Settings,
        access_service: DatabaseAccessService,
        connector_manager: ConnectorManager,
        result_formatter: DatabaseResultFormatter,
        call_repository: DatabaseCallStore,
    ) -> None:
        self._settings = settings
        self._access_service = access_service
        self._connector_manager = connector_manager
        self._result_formatter = result_formatter
        self._call_repository = call_repository

    def search(
        self,
        *,
        task_id: int,
        database: str,
        object_type: str,
        pattern: str = "*",
        detail: str = "names",
        schema: str | None = None,
        table: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        access = None
        try:
            normalized_type = DatabaseObjectType(object_type)
            normalized_detail = SearchDetail(detail)
            access = self._access_service.resolve(
                task_id=task_id,
                mcp_alias=database,
                object_type=normalized_type,
            )
            request = SearchObjectsRequest(
                object_type=normalized_type,
                schema=schema.strip() if schema else None,
                table=table.strip() if table else None,
                glob=pattern,
                detail=normalized_detail,
                limit=limit,
            )
            envelope = {
                "task_id": task_id,
                "database": access.database.mcp_alias,
                "engine": access.database.engine,
                "object_type": normalized_type.value,
                "detail": normalized_detail.value,
            }
            with self._connector_manager.lease(access.spec) as connector:
                raw_result = connector.search_objects(request, access.policy)
            max_objects = min(
                limit,
                {
                    SearchDetail.NAMES: 500,
                    SearchDetail.SUMMARY: 100,
                    SearchDetail.FULL: 20,
                }[normalized_detail],
            )
            formatted = self._result_formatter.format_search(
                raw_result,
                max_objects=max_objects,
                max_result_bytes=min(
                    self._settings.database_schema_result_bytes,
                    access.policy.max_result_bytes,
                ),
                envelope=envelope,
            )
            result = {**envelope, **formatted.as_dict()}
            self._record(
                DatabaseCallWrite(
                    task_id=task_id,
                    operation="search_objects",
                    database_alias=access.database.mcp_alias,
                    engine=access.database.engine,
                    object_type=normalized_type.value,
                    status="ok",
                    duration_ms=formatted.elapsed_ms,
                    returned_count=formatted.returned_count,
                    result_bytes=formatted.result_bytes,
                    truncated=formatted.truncated,
                )
            )
            return result
        except DatabaseAccessError as exc:
            self._record_error(
                task_id=task_id,
                database=database,
                engine=access.database.engine if access is not None else "unknown",
                object_type=object_type,
                code=exc.code,
            )
            raise
        except (
            ValueError,
            ConnectorManagerError,
            DatabaseConnectorError,
            ResultFormattingError,
        ) as exc:
            code = getattr(exc, "code", "catalog_query_failed")
            self._record_error(
                task_id=task_id,
                database=(access.database.mcp_alias if access is not None else database),
                engine=access.database.engine if access is not None else "unknown",
                object_type=object_type,
                code=code,
            )
            raise DatabaseAccessError(code, _public_catalog_message(code)) from exc
        except Exception as exc:
            self._record_error(
                task_id=task_id,
                database=database,
                engine=access.database.engine if access is not None else "unknown",
                object_type=object_type,
                code="catalog_query_failed",
            )
            raise DatabaseAccessError(
                "catalog_query_failed",
                "数据库对象搜索失败",
            ) from exc

    def _record_error(
        self,
        *,
        task_id: int,
        database: str,
        engine: str,
        object_type: str,
        code: str,
    ) -> None:
        if task_id < 1 or not database:
            return
        self._record(
            DatabaseCallWrite(
                task_id=task_id,
                operation="search_objects",
                database_alias=database[:64],
                engine=engine[:32] or "unknown",
                object_type=object_type[:32] or None,
                status="error",
                error_code=code[:64],
            )
        )

    def _record(self, call: DatabaseCallWrite) -> None:
        try:
            self._call_repository.create_call(call)
        except DatabaseCallRepositoryError:
            logger.warning("Unable to persist database object search metadata")


def _public_catalog_message(code: str) -> str:
    return {
        "connection_failed": "数据库当前无法连接",
        "catalog_query_failed": "数据库对象搜索失败",
        "query_rejected": "数据库对象搜索超出项目授权范围",
        "result_metadata_too_large": "数据库对象结果超过响应限制",
        "result_cell_too_large": "数据库对象字段超过响应限制",
        "engine_not_supported": "这个数据库类型不支持所请求的对象搜索",
    }.get(code, "数据库对象搜索失败")
