from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from context_router.schemas.ai_interface_visualization import (
    AiInterfaceRequestDetail,
    AiInterfaceRequestList,
    AiInterfaceRequestListItem,
)
from context_router.services.visualization_pagination import (
    VisualizationCursorError,
    decode_visualization_cursor,
    encode_visualization_cursor,
)
from context_router.services.visualization_security import (
    VISUALIZATION_RETENTION_DAYS,
    redact_value,
)


class AiInterfaceVisualizationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "interface_visualization_failed") -> None:
        super().__init__(message)
        self.code = code


class AiInterfaceVisualizationService:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def list_requests(
        self,
        *,
        workspace_id: str | None = None,
        success: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        cursor: str | None = None,
        task_id: int | None = None,
    ) -> AiInterfaceRequestList:
        bounded_limit = max(1, min(limit, 100))
        bounded_offset = max(0, offset)
        clauses = ["log.created_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')"]
        parameters: list[object] = [VISUALIZATION_RETENTION_DAYS]
        if workspace_id is not None:
            clauses.append("log.workspace_id=%s")
            parameters.append(workspace_id)
        if success is not None:
            clauses.append("log.success=%s")
            parameters.append(success)
        if task_id is not None:
            clauses.append("log.task_id=%s")
            parameters.append(task_id)
        if cursor:
            try:
                before_created_at, before_id = decode_visualization_cursor(cursor)
            except VisualizationCursorError as exc:
                raise AiInterfaceVisualizationError(str(exc), code="invalid_cursor") from exc
            clauses.append("(log.created_at, log.id) < (%s, %s)")
            parameters.extend((before_created_at, before_id))
            bounded_offset = 0
        parameters.extend((bounded_limit + 1, bounded_offset))
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    f"""{self._base_select()}
                       WHERE {" AND ".join(clauses)}
                       ORDER BY log.created_at DESC, log.id DESC
                       LIMIT %s OFFSET %s""",
                    tuple(parameters),
                )
                rows = list(cursor.fetchall())
        except psycopg.Error as exc:
            raise AiInterfaceVisualizationError("接口请求记录读取失败") from exc

        has_more = len(rows) > bounded_limit
        visible_rows = rows[:bounded_limit]
        items = [self._list_item(row) for row in visible_rows]
        next_cursor = (
            encode_visualization_cursor(visible_rows[-1]["created_at"], str(visible_rows[-1]["id"]))
            if has_more and visible_rows
            else None
        )
        return AiInterfaceRequestList(
            items=items,
            limit=bounded_limit,
            offset=bounded_offset,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    def get_request(self, request_id: str) -> AiInterfaceRequestDetail:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    f"""{self._base_select()}
                       WHERE log.id=%s
                         AND log.created_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')""",
                    (request_id, VISUALIZATION_RETENTION_DAYS),
                )
                row = cursor.fetchone()
        except psycopg.Error as exc:
            raise AiInterfaceVisualizationError("接口请求详情读取失败") from exc
        if row is None:
            raise AiInterfaceVisualizationError("接口请求记录不存在", code="request_not_found")

        item = self._list_item(row)
        return AiInterfaceRequestDetail(
            **item.model_dump(),
            task_id=row["task_id"],
            tool_call_id=row["tool_call_id"],
            plan_id=str(row["plan_id"]) if row["plan_id"] else None,
            request_sha256=row["request_sha256"],
            request=redact_value(self._parse_payload(row["request_body"])),
            response=redact_value(self._parse_payload(row["response_body"])),
            parameter_evidence=(
                row["parameter_evidence"] if isinstance(row["parameter_evidence"], dict) else {}
            ),
        )

    def _connect(self) -> psycopg.Connection[Any]:
        if not self._database_url:
            raise AiInterfaceVisualizationError("接口请求数据库尚未配置")
        return psycopg.connect(self._database_url, row_factory=dict_row)

    @staticmethod
    def _base_select() -> str:
        return """
            SELECT log.id, log.workspace_id, workspace.name AS workspace_name,
                   log.task_id, log.tool_call_id, log.plan_id, log.request_sha256,
                   log.request_body, log.response_body, log.status_code, log.success,
                   log.duration_ms, log.response_bytes, log.response_truncated,
                   log.created_at, log.environment_key, log.environment_name,
                   log.identity_name, log.identity_role,
                   interface.id AS interface_id, interface.name AS interface_name,
                   interface.method, interface.path,
                   service.name AS service_name,
                   address.name AS address_name,
                   task.task AS description, task.agent_name,
                   plan.parameter_evidence
            FROM interface_forwarding_logs AS log
            JOIN workspaces AS workspace ON workspace.id=log.workspace_id
            JOIN interface_forwarding_interfaces AS interface
              ON interface.id=log.interface_id
            JOIN interface_forwarding_services AS service
              ON service.id=interface.service_id
            LEFT JOIN interface_forwarding_environments AS address
              ON address.id=log.address_id
            LEFT JOIN mcp_tasks AS task ON task.id=log.task_id
            LEFT JOIN interface_forwarding_request_plans AS plan
              ON plan.id=log.plan_id
        """

    @classmethod
    def _list_item(cls, row: dict[str, Any]) -> AiInterfaceRequestListItem:
        source = str(row["agent_name"] or "manual")
        description = str(row["description"] or "手动接口请求")
        request = redact_value(cls._parse_payload(row["request_body"]))
        preview = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        if len(preview) > 240:
            preview = f"{preview[:237]}..."
        return AiInterfaceRequestListItem(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            workspace_name=str(row["workspace_name"]),
            source=source,
            description=description,
            interface_id=str(row["interface_id"]),
            interface_name=str(row["interface_name"]),
            service_name=str(row["service_name"]),
            method=str(row["method"]).upper(),
            path=str(row["path"]),
            environment=str(row["environment_key"] or row["environment_name"]),
            address_name=str(row["address_name"]) if row["address_name"] else None,
            login_account=str(row["identity_name"]) if row["identity_name"] else None,
            role_name=str(row["identity_role"]) if row["identity_role"] else None,
            request_preview=preview,
            status_code=row["status_code"],
            success=bool(row["success"]),
            duration_ms=int(row["duration_ms"] or 0),
            response_bytes=int(row["response_bytes"] or 0),
            response_truncated=bool(row["response_truncated"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _parse_payload(value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
