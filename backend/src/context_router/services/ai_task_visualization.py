from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from context_router.schemas.ai_task_visualization import (
    AiTaskChainHealthItem,
    AiTaskCodeLocation,
    AiTaskRelatedArtifacts,
    AiTaskResult,
    AiTaskResultWrite,
    AiTaskTimeline,
    AiTaskTimelineEvent,
    AiTaskVerificationItem,
    AiTaskVisualizationDetail,
    AiTaskVisualizationList,
    AiTaskVisualizationListItem,
)
from context_router.services.mcp_trace import current_tool_call_id
from context_router.services.visualization_pagination import (
    VisualizationCursorError,
    decode_visualization_cursor,
    encode_visualization_cursor,
)
from context_router.services.visualization_security import (
    VISUALIZATION_RETENTION_DAYS,
    redact_text,
    redact_value,
)


class AiTaskVisualizationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "task_visualization_failed") -> None:
        super().__init__(message)
        self.code = code


_OVERVIEW_CTES = """
WITH tool_stats AS (
    SELECT call.task_id,
           COUNT(*) AS tool_call_count,
           COUNT(*) FILTER (WHERE call.status = 'error') AS tool_error_count,
           COUNT(*) FILTER (WHERE call.status = 'running') AS running_call_count,
           MAX(COALESCE(call.finished_at, call.started_at)) AS last_activity_at
    FROM mcp_tool_calls AS call
    WHERE call.server_name = 'context-router'
      AND call.source IN ('server', 'legacy')
    GROUP BY call.task_id
), data_stats AS (
    SELECT record.task_id, COUNT(*) AS data_query_count,
           COUNT(*) FILTER (WHERE record.execution_status = 'succeeded') AS data_succeeded_count,
           COUNT(*) FILTER (WHERE record.execution_status = 'failed') AS data_failed_count,
           COUNT(*) FILTER (WHERE record.execution_status = 'pending') AS data_pending_count,
           MAX(COALESCE(record.updated_at, record.created_at)) AS last_activity_at
    FROM ai_data_query_records AS record
    JOIN mcp_tasks AS owner ON owner.id = record.task_id
                           AND owner.workspace_id = record.workspace_id
    WHERE record.task_id IS NOT NULL
    GROUP BY record.task_id
), interface_stats AS (
    SELECT log.task_id,
           COUNT(*) FILTER (WHERE log.success) AS interface_success_count,
           COUNT(*) FILTER (WHERE NOT log.success) AS interface_failed_count,
           MAX(log.created_at) AS last_activity_at
    FROM interface_forwarding_logs AS log
    JOIN mcp_tasks AS owner ON owner.id = log.task_id
                           AND owner.workspace_id = log.workspace_id
    WHERE log.task_id IS NOT NULL
    GROUP BY log.task_id
), log_stats AS (
    SELECT record.task_id,
           COALESCE(SUM(record.occurrence_count), 0) AS error_event_count,
           MAX(record.updated_at) AS last_activity_at
    FROM ai_log_investigations AS record
    JOIN mcp_tasks AS owner ON owner.id = record.task_id
                           AND owner.workspace_id = record.workspace_id
    WHERE record.task_id IS NOT NULL
    GROUP BY record.task_id
), overview AS (
    SELECT task.id AS task_id,
           task.task AS description,
           task.workspace_id,
           COALESCE(task.workspace_name, task.project_name) AS workspace_name,
           COALESCE(task.database_environment, 'local') AS environment,
           COALESCE(NULLIF(task.agent_name, ''), 'agent') AS agent_name,
           task.intent_type,
           task.intent_error_signal,
           task.intent_summary,
           task.intent_source,
           CASE
               WHEN result.status IS NOT NULL THEN result.status
               WHEN COALESCE(tool.running_call_count, 0) > 0 THEN 'investigating'
               ELSE 'unclosed'
           END AS display_status,
           task.created_at,
           GREATEST(
               task.created_at,
               COALESCE(tool.last_activity_at, task.created_at),
               COALESCE(data.last_activity_at, task.created_at),
               COALESCE(interface.last_activity_at, task.created_at),
               COALESCE(log.last_activity_at, task.created_at),
               COALESCE(result.updated_at, task.created_at)
           ) AS last_activity_at,
           COALESCE(tool.tool_call_count, 0) AS tool_call_count,
           COALESCE(tool.tool_error_count, 0) AS tool_error_count,
           COALESCE(tool.running_call_count, 0) AS running_call_count,
           COALESCE(data.data_query_count, 0) AS data_query_count,
           COALESCE(data.data_succeeded_count, 0) AS data_succeeded_count,
           COALESCE(data.data_failed_count, 0) AS data_failed_count,
           COALESCE(data.data_pending_count, 0) AS data_pending_count,
           COALESCE(interface.interface_success_count, 0) AS interface_success_count,
           COALESCE(interface.interface_failed_count, 0) AS interface_failed_count,
           COALESCE(log.error_event_count, 0) AS error_event_count,
           task.cwd,
           task.active_project_name
    FROM mcp_tasks AS task
    LEFT JOIN tool_stats AS tool ON tool.task_id = task.id
    LEFT JOIN data_stats AS data ON data.task_id = task.id
    LEFT JOIN interface_stats AS interface ON interface.task_id = task.id
    LEFT JOIN log_stats AS log ON log.task_id = task.id
    LEFT JOIN ai_task_visualization_results AS result ON result.task_id = task.id
    WHERE task.workspace_id IS NOT NULL
      AND task.agent_name IS DISTINCT FROM 'connection-test'
      AND task.agent_name IS DISTINCT FROM 'web-preview'
)
"""


class AiTaskVisualizationService:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def list_tasks(
        self,
        *,
        workspace_id: str | None = None,
        environment: str | None = None,
        agent_name: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
        limit: int = 30,
        cursor: str | None = None,
    ) -> AiTaskVisualizationList:
        bounded_limit = max(1, min(limit, 100))
        clauses = ["last_activity_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')"]
        parameters: list[object] = [VISUALIZATION_RETENTION_DAYS]
        if workspace_id:
            clauses.append("workspace_id = %s")
            parameters.append(workspace_id)
        if environment:
            clauses.append("environment = %s")
            parameters.append(environment)
        if agent_name:
            clauses.append("lower(agent_name) = lower(%s)")
            parameters.append(agent_name)
        if status:
            clauses.append("display_status = %s")
            parameters.append(status)
        normalized_keyword = keyword.strip() if keyword else ""
        if normalized_keyword:
            clauses.append(
                "(description ILIKE %s OR workspace_name ILIKE %s OR EXISTS ("
                "SELECT 1 FROM ai_task_visualization_results AS keyword_result "
                "WHERE keyword_result.task_id = overview.task_id "
                "AND (keyword_result.summary ILIKE %s OR keyword_result.root_cause ILIKE %s)))"
            )
            pattern = f"%{normalized_keyword}%"
            parameters.extend((pattern, pattern, pattern, pattern))
        if cursor:
            try:
                before_activity, before_id = decode_visualization_cursor(cursor)
                before_task_id = int(before_id)
            except (VisualizationCursorError, ValueError) as exc:
                raise AiTaskVisualizationError(str(exc), code="invalid_cursor") from exc
            clauses.append("(last_activity_at, task_id) < (%s, %s)")
            parameters.extend((before_activity, before_task_id))
        parameters.append(bounded_limit + 1)
        try:
            with self._connect() as connection, connection.cursor() as db_cursor:
                db_cursor.execute(
                    f"""{_OVERVIEW_CTES}
                    SELECT * FROM overview
                    WHERE {" AND ".join(clauses)}
                    ORDER BY last_activity_at DESC, task_id DESC
                    LIMIT %s""",
                    tuple(parameters),
                )
                rows = list(db_cursor.fetchall())
        except psycopg.Error as exc:
            raise AiTaskVisualizationError("任务可视化列表读取失败") from exc

        has_more = len(rows) > bounded_limit
        visible = rows[:bounded_limit]
        next_cursor = (
            encode_visualization_cursor(
                visible[-1]["last_activity_at"],
                str(visible[-1]["task_id"]),
            )
            if has_more and visible
            else None
        )
        return AiTaskVisualizationList(
            items=[self._list_item(row) for row in visible],
            limit=bounded_limit,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    def get_task(self, task_id: int) -> AiTaskVisualizationDetail:
        try:
            with self._connect() as connection, connection.cursor() as db_cursor:
                db_cursor.execute(
                    f"""{_OVERVIEW_CTES}
                    SELECT * FROM overview
                    WHERE task_id = %s
                      AND last_activity_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')""",
                    (task_id, VISUALIZATION_RETENTION_DAYS),
                )
                row = db_cursor.fetchone()
                if row is None:
                    raise AiTaskVisualizationError(
                        "任务可视化记录不存在",
                        code="task_not_found",
                    )
                result = self._read_result(db_cursor, task_id)
        except AiTaskVisualizationError:
            raise
        except psycopg.Error as exc:
            raise AiTaskVisualizationError("任务可视化详情读取失败") from exc
        item = self._list_item(row)
        return AiTaskVisualizationDetail(
            **item.model_dump(),
            cwd=str(row["cwd"]),
            active_project_name=(
                str(row["active_project_name"]) if row["active_project_name"] else None
            ),
            result=result,
            related=AiTaskRelatedArtifacts(
                mcp_trace=item.tool_call_count > 0,
                data_visualization=item.data_query_count > 0,
                interface_visualization=(
                    item.interface_success_count + item.interface_failed_count > 0
                ),
                log_visualization=item.error_event_count > 0,
            ),
            chain_health=self._chain_health(item, row, result),
        )

    def timeline(
        self,
        task_id: int,
        *,
        limit: int = 50,
        cursor: str | None = None,
        event_type: str | None = None,
    ) -> AiTaskTimeline:
        bounded_limit = max(1, min(limit, 100))
        clauses = ["task_id = %s"]
        parameters: list[object] = [task_id]
        if event_type:
            clauses.append("event_type = %s")
            parameters.append(event_type)
        if cursor:
            try:
                before_activity, before_id = decode_visualization_cursor(cursor)
            except VisualizationCursorError as exc:
                raise AiTaskVisualizationError(str(exc), code="invalid_cursor") from exc
            clauses.append("(occurred_at, event_id) < (%s, %s)")
            parameters.extend((before_activity, before_id))
        parameters.append(bounded_limit + 1)
        try:
            with self._connect() as connection, connection.cursor() as db_cursor:
                db_cursor.execute(
                    f"""{self._timeline_cte()}
                    SELECT * FROM timeline
                    WHERE {" AND ".join(clauses)}
                    ORDER BY occurred_at DESC, event_id DESC
                    LIMIT %s""",
                    tuple(parameters),
                )
                rows = list(db_cursor.fetchall())
        except psycopg.Error as exc:
            raise AiTaskVisualizationError("任务时间线读取失败") from exc
        has_more = len(rows) > bounded_limit
        visible = rows[:bounded_limit]
        next_cursor = (
            encode_visualization_cursor(visible[-1]["occurred_at"], visible[-1]["event_id"])
            if has_more and visible
            else None
        )
        return AiTaskTimeline(
            task_id=task_id,
            items=[self._timeline_event(row) for row in visible],
            limit=bounded_limit,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    def save_result(self, task_id: int, payload: AiTaskResultWrite) -> AiTaskResult:
        safe = redact_value(payload.model_dump())
        tool_call_id = current_tool_call_id()
        try:
            with self._connect() as connection, connection.cursor() as db_cursor:
                self._validate_intent_closure(db_cursor, task_id, str(safe["status"]))
                db_cursor.execute(
                    """
                    INSERT INTO ai_task_visualization_results (
                        task_id, status, summary, root_cause, code_locations,
                        suggested_actions, verification, source, tool_call_id,
                        revision, created_at, updated_at, finalized_at
                    )
                    SELECT task.id, %s, %s, %s, %s, %s, %s,
                           COALESCE(NULLIF(task.agent_name, ''), 'agent'), %s,
                           1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                           CASE WHEN %s = 'investigating' THEN NULL ELSE CURRENT_TIMESTAMP END
                    FROM mcp_tasks AS task
                    WHERE task.id = %s AND task.workspace_id IS NOT NULL
                    ON CONFLICT (task_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        summary = EXCLUDED.summary,
                        root_cause = EXCLUDED.root_cause,
                        code_locations = EXCLUDED.code_locations,
                        suggested_actions = EXCLUDED.suggested_actions,
                        verification = EXCLUDED.verification,
                        source = EXCLUDED.source,
                        tool_call_id = EXCLUDED.tool_call_id,
                        revision = ai_task_visualization_results.revision + 1,
                        updated_at = CURRENT_TIMESTAMP,
                        finalized_at = EXCLUDED.finalized_at
                    RETURNING task_id
                    """,
                    (
                        safe["status"],
                        safe["summary"],
                        safe.get("root_cause"),
                        Jsonb(safe["code_locations"]),
                        Jsonb(safe["suggested_actions"]),
                        Jsonb(safe["verification"]),
                        tool_call_id,
                        safe["status"],
                        task_id,
                    ),
                )
                row = db_cursor.fetchone()
                if row is None:
                    raise AiTaskVisualizationError("任务不存在", code="task_not_found")
                result = self._read_result(db_cursor, task_id)
        except AiTaskVisualizationError:
            raise
        except psycopg.Error as exc:
            raise AiTaskVisualizationError("任务诊断结论保存失败") from exc
        if result is None:
            raise AiTaskVisualizationError("任务诊断结论保存后无法读取")
        return result

    def _connect(self) -> psycopg.Connection[Any]:
        if not self._database_url:
            raise AiTaskVisualizationError("任务可视化数据库尚未配置")
        return psycopg.connect(self._database_url, row_factory=dict_row)

    @staticmethod
    def _list_item(row: dict[str, Any]) -> AiTaskVisualizationListItem:
        return AiTaskVisualizationListItem(
            task_id=int(row["task_id"]),
            description=redact_text(str(row["description"])),
            workspace_id=str(row["workspace_id"]),
            workspace_name=str(row["workspace_name"]),
            environment=str(row["environment"]),
            agent_name=str(row["agent_name"]),
            intent_type=str(row["intent_type"]),
            intent_error_signal=bool(row["intent_error_signal"]),
            intent_summary=(
                redact_text(str(row["intent_summary"])) if row["intent_summary"] else None
            ),
            intent_source=str(row["intent_source"]),
            status=str(row["display_status"]),
            created_at=row["created_at"],
            last_activity_at=row["last_activity_at"],
            tool_call_count=int(row["tool_call_count"]),
            tool_error_count=int(row["tool_error_count"]),
            running_call_count=int(row["running_call_count"]),
            data_query_count=int(row["data_query_count"]),
            interface_success_count=int(row["interface_success_count"]),
            interface_failed_count=int(row["interface_failed_count"]),
            error_event_count=int(row["error_event_count"]),
        )

    @staticmethod
    def _validate_intent_closure(db_cursor: Any, task_id: int, status: str) -> None:
        db_cursor.execute(
            """
            SELECT task.intent_type,
                   task.intent_error_signal,
                   EXISTS (
                       SELECT 1 FROM ai_data_query_records AS data_record
                       WHERE data_record.task_id = task.id
                   ) AS has_data_record,
                   EXISTS (
                       SELECT 1 FROM interface_forwarding_logs AS interface_log
                       WHERE interface_log.task_id = task.id
                   ) AS has_interface_record,
                   EXISTS (
                       SELECT 1 FROM mcp_tool_calls AS inspect_call
                       WHERE inspect_call.task_id = task.id
                         AND inspect_call.tool_name = 'inspect_container_errors'
                         AND inspect_call.status = 'ok'
                   ) AS inspected_container_errors,
                   EXISTS (
                       SELECT 1 FROM mcp_tool_calls AS apply_call
                       WHERE apply_call.task_id = task.id
                         AND apply_call.tool_name = 'apply_workspace_changes'
                         AND apply_call.status = 'ok'
                   ) AS applied_workspace_changes
            FROM mcp_tasks AS task
            WHERE task.id = %s AND task.workspace_id IS NOT NULL
            """,
            (task_id,),
        )
        row = db_cursor.fetchone()
        if row is None:
            raise AiTaskVisualizationError("任务不存在", code="task_not_found")
        if status != "resolved":
            return

        intent_type = str(row["intent_type"])
        missing: list[str] = []
        if intent_type == "interface_execute" and not row["has_interface_record"]:
            missing.append("execute_forwarding_request 产生的接口执行记录")
        if intent_type == "data_query" and not row["has_data_record"]:
            missing.append("save_data_visualization_query 产生的数据条件记录")
        if (
            intent_type in {"bug_investigate", "bug_fix"}
            and bool(row["intent_error_signal"])
            and not row["inspected_container_errors"]
        ):
            missing.append("inspect_container_errors 完成的注册容器错误检查")
        if intent_type == "bug_fix" and not row["applied_workspace_changes"]:
            missing.append("apply_workspace_changes 完成的工作空间更新")
        if missing:
            raise AiTaskVisualizationError(
                "任务意图要求的步骤尚未完成：" + "；".join(missing),
                code="intent_required_steps_missing",
            )

    @staticmethod
    def _chain_health(
        item: AiTaskVisualizationListItem,
        row: dict[str, Any],
        result: AiTaskResult | None,
    ) -> list[AiTaskChainHealthItem]:
        if item.running_call_count > 0:
            mcp_status = "running"
            mcp_summary = f"{item.running_call_count} 次调用仍在执行"
        elif item.tool_error_count > 0 and result is not None and result.status == "resolved":
            mcp_status = "attention"
            mcp_summary = (
                f"已完成，期间 {item.tool_error_count} 次调用失败后恢复 / "
                f"共 {item.tool_call_count} 次调用"
            )
        elif item.tool_error_count > 0:
            mcp_status = "failed"
            mcp_summary = f"{item.tool_error_count} 次失败 / {item.tool_call_count} 次调用"
        elif item.tool_call_count > 0:
            mcp_status = "healthy"
            mcp_summary = f"{item.tool_call_count} 次调用均已完成"
        else:
            mcp_status = "unused"
            mcp_summary = "本任务未调用 Context Router MCP"

        data_succeeded = int(row["data_succeeded_count"])
        data_failed = int(row["data_failed_count"])
        data_pending = int(row["data_pending_count"])
        if data_failed > 0 and data_succeeded > 0:
            data_status = "attention"
            data_summary = f"{data_succeeded} 次成功，{data_failed} 次失败"
        elif data_failed > 0:
            data_status = "failed"
            data_summary = f"{data_failed} 次查询失败"
        elif data_pending > 0:
            data_status = "running"
            data_summary = f"{data_pending} 个查询条件待执行"
        elif data_succeeded > 0:
            data_status = "healthy"
            data_summary = f"{data_succeeded} 次查询成功"
        else:
            data_status = "unused"
            data_summary = "本任务未保存数据查询条件"

        if item.interface_failed_count > 0 and item.interface_success_count > 0:
            interface_status = "attention"
            interface_summary = (
                f"{item.interface_success_count} 次成功，{item.interface_failed_count} 次失败"
            )
        elif item.interface_failed_count > 0:
            interface_status = "failed"
            interface_summary = f"{item.interface_failed_count} 次请求失败"
        elif item.interface_success_count > 0:
            interface_status = "healthy"
            interface_summary = f"{item.interface_success_count} 次请求成功"
        else:
            interface_status = "unused"
            interface_summary = "本任务未执行接口请求"

        if item.error_event_count > 0:
            log_status = "attention"
            log_summary = f"已保存 {item.error_event_count} 个错误事件"
        else:
            log_status = "unused"
            log_summary = "本任务未保存错误日志记录"

        if result is None:
            conclusion_status = "attention"
            conclusion_summary = "AI 尚未写入结构化任务结论"
        elif result.status == "resolved":
            conclusion_status = "healthy"
            conclusion_summary = f"已完成并记录 {len(result.verification)} 项验证"
        elif result.status == "investigating":
            conclusion_status = "running"
            conclusion_summary = "AI 已写入阶段性排查结论"
        else:
            conclusion_status = "failed"
            conclusion_summary = "任务因明确阻塞未完成"

        return [
            AiTaskChainHealthItem(
                key="mcp", label="MCP 调用", status=mcp_status, summary=mcp_summary
            ),
            AiTaskChainHealthItem(
                key="data", label="数据查询", status=data_status, summary=data_summary
            ),
            AiTaskChainHealthItem(
                key="interface",
                label="接口请求",
                status=interface_status,
                summary=interface_summary,
            ),
            AiTaskChainHealthItem(
                key="log", label="错误日志", status=log_status, summary=log_summary
            ),
            AiTaskChainHealthItem(
                key="conclusion",
                label="任务结论",
                status=conclusion_status,
                summary=conclusion_summary,
            ),
        ]

    @staticmethod
    def _read_result(db_cursor: Any, task_id: int) -> AiTaskResult | None:
        db_cursor.execute(
            """
            SELECT task_id, status, summary, root_cause, code_locations,
                   suggested_actions, verification, source, revision,
                   created_at, updated_at, finalized_at
            FROM ai_task_visualization_results
            WHERE task_id = %s
            """,
            (task_id,),
        )
        row = db_cursor.fetchone()
        if row is None:
            return None
        return AiTaskResult(
            task_id=int(row["task_id"]),
            status=str(row["status"]),
            summary=str(row["summary"]),
            root_cause=str(row["root_cause"]) if row["root_cause"] else None,
            code_locations=[
                AiTaskCodeLocation.model_validate(item) for item in row["code_locations"]
            ],
            suggested_actions=[str(item) for item in row["suggested_actions"]],
            verification=[
                AiTaskVerificationItem.model_validate(item) for item in row["verification"]
            ],
            source=str(row["source"]),
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finalized_at=row["finalized_at"],
        )

    @staticmethod
    def _timeline_event(row: dict[str, Any]) -> AiTaskTimelineEvent:
        return AiTaskTimelineEvent(
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            title=redact_text(str(row["title"])),
            status=str(row["status"]),
            occurred_at=row["occurred_at"],
            summary=redact_text(str(row["summary"] or "")),
            artifact_type=str(row["artifact_type"]),
            artifact_id=str(row["artifact_id"]),
        )

    @staticmethod
    def _timeline_cte() -> str:
        return """
        WITH timeline AS (
            SELECT call.task_id,
                   'mcp:' || call.id::text AS event_id,
                   'mcp_call'::text AS event_type,
                   call.tool_name::text AS title,
                   call.status::text AS status,
                   call.started_at AS occurred_at,
                   CASE
                       WHEN call.status = 'error' THEN
                           COALESCE(call.error_code, '工具调用失败')
                       WHEN call.duration_ms IS NOT NULL THEN
                           call.duration_ms::text || ' ms'
                       ELSE '工具调用已记录'
                   END AS summary,
                   'mcp'::text AS artifact_type,
                   call.id::text AS artifact_id
            FROM mcp_tool_calls AS call
            WHERE call.server_name = 'context-router'
              AND call.source IN ('server', 'legacy')
            UNION ALL
            SELECT record.task_id,
                   'data:' || record.id,
                   'data_query', record.table_name,
                   record.execution_status,
                   COALESCE(record.executed_at, record.created_at),
                   record.database_key || '.' || record.schema_name || '.' ||
                       record.table_name || ' · ' || record.keyword,
                   'data', record.id
            FROM ai_data_query_records AS record
            JOIN mcp_tasks AS owner ON owner.id = record.task_id
                                   AND owner.workspace_id = record.workspace_id
            WHERE record.task_id IS NOT NULL
            UNION ALL
            SELECT log.task_id,
                   'interface:' || log.id,
                   'interface_request', interface.name,
                   CASE WHEN log.success THEN 'succeeded' ELSE 'failed' END,
                   log.created_at,
                   upper(interface.method) || ' ' || interface.path || ' · ' ||
                       COALESCE(log.status_code::text, '-') || ' · ' ||
                       COALESCE(log.duration_ms::text, '0') || ' ms',
                   'interface', log.id
            FROM interface_forwarding_logs AS log
            JOIN mcp_tasks AS owner ON owner.id = log.task_id
                                   AND owner.workspace_id = log.workspace_id
            JOIN interface_forwarding_interfaces AS interface ON interface.id = log.interface_id
            WHERE log.task_id IS NOT NULL
            UNION ALL
            SELECT record.task_id,
                   'log:' || record.id,
                   'log_investigation', record.error_title, record.severity,
                   record.updated_at,
                   record.container_name || ' · ' || record.occurrence_count::text || ' 个错误事件',
                   'log', record.id
            FROM ai_log_investigations AS record
            JOIN mcp_tasks AS owner ON owner.id = record.task_id
                                   AND owner.workspace_id = record.workspace_id
            WHERE record.task_id IS NOT NULL
            UNION ALL
            SELECT result.task_id,
                   'result:' || result.task_id::text,
                   'task_result', '任务诊断结论', result.status,
                   result.updated_at, result.summary,
                   'result', result.task_id::text
            FROM ai_task_visualization_results AS result
        )
        """
