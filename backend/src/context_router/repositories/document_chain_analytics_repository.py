from __future__ import annotations

from typing import Protocol

import psycopg

from context_router.schemas.document_chain_analytics import (
    AgentComparisonItem,
    BrokenLinkAlertItem,
    DocumentChainAnalyticsResponse,
    DocumentHealthMatrixItem,
    RetrievalFunnelMetrics,
)


class DocumentChainAnalyticsRepositoryError(RuntimeError):
    pass


class DocumentChainAnalyticsStore(Protocol):
    def get_chain_analytics(
        self,
        *,
        workspace_id: str | None = None,
        limit: int = 50,
    ) -> DocumentChainAnalyticsResponse: ...


class PostgresDocumentChainAnalyticsRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def get_chain_analytics(
        self,
        *,
        workspace_id: str | None = None,
        limit: int = 50,
    ) -> DocumentChainAnalyticsResponse:
        if not self._database_url:
            return DocumentChainAnalyticsResponse(
                funnel=RetrievalFunnelMetrics(
                    total_tasks=0,
                    direct_hit_tasks=0,
                    search_then_read_tasks=0,
                    deep_search_tasks=0,
                    direct_hit_rate=0.0,
                    search_rate=0.0,
                    avg_reads_per_task=0.0,
                    avg_searches_per_task=0.0,
                ),
                health_matrix=[],
                alerts=[],
                agent_comparison=[],
            )

        try:
            with psycopg.connect(self._database_url) as conn:
                funnel = self._get_funnel_metrics(conn, workspace_id)
                health_matrix = self._get_health_matrix(conn, workspace_id, limit)
                alerts = self._get_alerts(conn, workspace_id)
                agent_comparison = self._get_agent_comparison(conn, workspace_id)

                return DocumentChainAnalyticsResponse(
                    funnel=funnel,
                    health_matrix=health_matrix,
                    alerts=alerts,
                    agent_comparison=agent_comparison,
                )
        except psycopg.Error as exc:
            raise DocumentChainAnalyticsRepositoryError(
                f"数据库查询文档链路分析失败: {exc}"
            ) from exc

    def _get_funnel_metrics(
        self, conn: psycopg.Connection, workspace_id: str | None
    ) -> RetrievalFunnelMetrics:
        where_sql = ""
        params: list[object] = []
        if workspace_id:
            where_sql = "WHERE t.workspace_name = %s"
            params.append(workspace_id)

        sql = f"""
            WITH task_stats AS (
                SELECT
                    t.id AS task_id,
                    COUNT(tc.id) FILTER (WHERE tc.tool_name = 'prepare_task_context') AS prepare_count,
                    COUNT(tc.id) FILTER (WHERE tc.tool_name = 'search_context_documents') AS search_count,
                    COUNT(tc.id) FILTER (WHERE tc.tool_name = 'read_context_document') AS read_count
                FROM mcp_tasks t
                LEFT JOIN mcp_tool_calls tc ON tc.task_id = t.id
                {where_sql}
                GROUP BY t.id
            )
            SELECT
                COUNT(*) AS total_tasks,
                COUNT(*) FILTER (WHERE search_count = 0 AND read_count > 0) AS direct_hit_tasks,
                COUNT(*) FILTER (WHERE search_count > 0 AND search_count <= 2) AS search_then_read_tasks,
                COUNT(*) FILTER (WHERE search_count > 2) AS deep_search_tasks,
                COALESCE(AVG(read_count), 0.0) AS avg_reads,
                COALESCE(AVG(search_count), 0.0) AS avg_searches
            FROM task_stats;
        """
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        if not row or row[0] == 0:
            return RetrievalFunnelMetrics(
                total_tasks=0,
                direct_hit_tasks=0,
                search_then_read_tasks=0,
                deep_search_tasks=0,
                direct_hit_rate=0.0,
                search_rate=0.0,
                avg_reads_per_task=0.0,
                avg_searches_per_task=0.0,
            )

        total = row[0]
        direct_hits = row[1] or 0
        search_then_read = row[2] or 0
        deep_search = row[3] or 0
        avg_reads = float(row[4] or 0.0)
        avg_searches = float(row[5] or 0.0)

        searched_tasks = total - direct_hits  # Tasks that performed search or didn't direct hit

        return RetrievalFunnelMetrics(
            total_tasks=total,
            direct_hit_tasks=direct_hits,
            search_then_read_tasks=search_then_read,
            deep_search_tasks=deep_search,
            direct_hit_rate=round(direct_hits / total, 4) if total > 0 else 0.0,
            search_rate=round(searched_tasks / total, 4) if total > 0 else 0.0,
            avg_reads_per_task=round(avg_reads, 2),
            avg_searches_per_task=round(avg_searches, 2),
        )

    def _get_health_matrix(
        self, conn: psycopg.Connection, workspace_id: str | None, limit: int
    ) -> list[DocumentHealthMatrixItem]:
        where_sql = "WHERE i.document_id NOT LIKE %s AND i.document_id != %s"
        params: list[object] = ["%/AGENTS.md", "AGENTS.md"]

        if workspace_id:
            where_sql += " AND c.workspace_name = %s"
            params.append(workspace_id)

        params.append(limit)

        sql = f"""
            WITH document_reads AS (
                SELECT
                    i.document_id,
                    MAX(i.document_path) AS document_path,
                    COUNT(DISTINCT i.id) AS read_count,
                    COUNT(DISTINCT c.task_id) AS task_count
                FROM mcp_document_read_items i
                JOIN mcp_document_read_calls c ON c.id = i.read_call_id
                {where_sql}
                GROUP BY i.document_id
            ),
            post_read_searches AS (
                SELECT
                    i.document_id,
                    COUNT(DISTINCT tc_search.id) AS search_after_read_count
                FROM mcp_document_read_items i
                JOIN mcp_document_read_calls c ON c.id = i.read_call_id
                JOIN mcp_tool_calls tc_read ON tc_read.id = c.tool_call_id
                JOIN mcp_tool_calls tc_search ON tc_search.task_id = c.task_id
                    AND tc_search.tool_name = 'search_context_documents'
                    AND tc_search.id > tc_read.id
                GROUP BY i.document_id
            )
            SELECT
                dr.document_id,
                dr.document_path,
                dr.read_count,
                dr.task_count,
                COALESCE(prs.search_after_read_count, 0) AS search_after_read_count
            FROM document_reads dr
            LEFT JOIN post_read_searches prs ON prs.document_id = dr.document_id
            ORDER BY dr.read_count DESC
            LIMIT %s;
        """

        cur = conn.execute(sql, params)
        rows = cur.fetchall()

        if not rows:
            return []

        avg_reads = sum(r[2] for r in rows) / len(rows)

        results: list[DocumentHealthMatrixItem] = []
        for r in rows:
            doc_id, path, read_cnt, task_cnt, search_after_cnt = r
            rate = round(search_after_cnt / read_cnt, 4) if read_cnt > 0 else 0.0

            is_high_freq = read_cnt >= avg_reads
            is_ineffective = rate >= 0.35

            if is_high_freq and is_ineffective:
                category = "high_freq_ineffective"
            elif is_high_freq and not is_ineffective:
                category = "high_freq_effective"
            elif not is_high_freq and is_ineffective:
                category = "low_freq_ineffective"
            else:
                category = "low_freq_effective"

            results.append(
                DocumentHealthMatrixItem(
                    document_id=doc_id,
                    document_path=path,
                    read_count=read_cnt,
                    task_count=task_cnt,
                    search_after_read_count=search_after_cnt,
                    search_after_read_rate=rate,
                    health_category=category,
                )
            )

        return results

    def _get_alerts(
        self, conn: psycopg.Connection, workspace_id: str | None
    ) -> list[BrokenLinkAlertItem]:
        params: list[object] = []
        where_sql = ""
        if workspace_id:
            where_sql = "WHERE t.workspace_name = %s"

        sql = f"""
            -- 1. Read errors
            SELECT
                'read_error' AS alert_type,
                t.id AS task_id,
                t.task AS task_prompt,
                t.agent_name,
                '读取文档失败 (Tool Status Error)' AS message,
                t.created_at
            FROM mcp_tool_calls tc
            JOIN mcp_tasks t ON t.id = tc.task_id
            WHERE tc.tool_name = 'read_context_document' AND tc.status = 'error'
            
            UNION ALL
            
            -- 2. Search no results
            SELECT
                'search_no_results' AS alert_type,
                t.id AS task_id,
                t.task AS task_prompt,
                t.agent_name,
                CONCAT('搜索工具调用无结果 (Tool Call ID: ', tc.id, ')') AS message,
                t.created_at
            FROM mcp_tool_calls tc
            JOIN mcp_tasks t ON t.id = tc.task_id
            WHERE tc.tool_name = 'search_context_documents' AND (tc.result_summary->>'hits' = '0' OR tc.status = 'error')

            UNION ALL

            -- 3. Loop search (searches >= 3)
            SELECT
                'loop_search' AS alert_type,
                t.id AS task_id,
                t.task AS task_prompt,
                t.agent_name,
                CONCAT('单任务发起高频搜索 (共 ', COUNT(tc.id), ' 次搜索)') AS message,
                t.created_at
            FROM mcp_tasks t
            JOIN mcp_tool_calls tc ON tc.task_id = t.id
            WHERE tc.tool_name = 'search_context_documents'
            GROUP BY t.id, t.task, t.agent_name, t.created_at
            HAVING COUNT(tc.id) >= 3

            UNION ALL

            -- 4. Deep traversal (reads >= 5)
            SELECT
                'deep_traversal' AS alert_type,
                t.id AS task_id,
                t.task AS task_prompt,
                t.agent_name,
                CONCAT('单任务深度遍历多个文档 (共 ', COUNT(tc.id), ' 次阅读)') AS message,
                t.created_at
            FROM mcp_tasks t
            JOIN mcp_tool_calls tc ON tc.task_id = t.id
            WHERE tc.tool_name = 'read_context_document'
            GROUP BY t.id, t.task, t.agent_name, t.created_at
            HAVING COUNT(tc.id) >= 5

            ORDER BY created_at DESC
            LIMIT 30;
        """

        cur = conn.execute(sql, params)
        rows = cur.fetchall()

        alerts: list[BrokenLinkAlertItem] = []
        for r in rows:
            alert_type, task_id, prompt, agent_name, msg, created_at = r
            alerts.append(
                BrokenLinkAlertItem(
                    alert_type=alert_type,
                    task_id=task_id,
                    task_prompt=prompt,
                    agent_name=agent_name or "Unknown Agent",
                    message=msg,
                    created_at=created_at,
                )
            )

        return alerts

    def _get_agent_comparison(
        self, conn: psycopg.Connection, workspace_id: str | None
    ) -> list[AgentComparisonItem]:
        where_sql = ""
        params: list[object] = []
        if workspace_id:
            where_sql = "WHERE t.workspace_name = %s"
            params.append(workspace_id)

        sql = f"""
            WITH agent_stats AS (
                SELECT
                    COALESCE(t.agent_name, 'Unknown Agent') AS agent_name,
                    t.id AS task_id,
                    COUNT(tc.id) FILTER (WHERE tc.tool_name = 'search_context_documents') AS search_count,
                    COUNT(tc.id) FILTER (WHERE tc.tool_name = 'read_context_document') AS read_count
                FROM mcp_tasks t
                LEFT JOIN mcp_tool_calls tc ON tc.task_id = t.id
                {where_sql}
                GROUP BY COALESCE(t.agent_name, 'Unknown Agent'), t.id
            )
            SELECT
                agent_name,
                COUNT(*) AS total_tasks,
                COALESCE(AVG(search_count), 0.0) AS avg_searches,
                COALESCE(AVG(read_count), 0.0) AS avg_reads,
                COUNT(*) FILTER (WHERE search_count = 0 AND read_count > 0) AS direct_hits
            FROM agent_stats
            GROUP BY agent_name
            ORDER BY total_tasks DESC;
        """

        cur = conn.execute(sql, params)
        rows = cur.fetchall()

        result: list[AgentComparisonItem] = []
        for r in rows:
            name, total, avg_searches, avg_reads, direct_hits = r
            direct_rate = round(direct_hits / total, 4) if total > 0 else 0.0
            result.append(
                AgentComparisonItem(
                    agent_name=name,
                    total_tasks=total,
                    avg_searches=round(float(avg_searches), 2),
                    avg_reads=round(float(avg_reads), 2),
                    direct_hit_rate=direct_rate,
                )
            )

        return result


class InMemoryDocumentChainAnalyticsRepository:
    def get_chain_analytics(
        self,
        *,
        workspace_id: str | None = None,
        limit: int = 50,
    ) -> DocumentChainAnalyticsResponse:
        return DocumentChainAnalyticsResponse(
            funnel=RetrievalFunnelMetrics(
                total_tasks=0,
                direct_hit_tasks=0,
                search_then_read_tasks=0,
                deep_search_tasks=0,
                direct_hit_rate=0.0,
                search_rate=0.0,
                avg_reads_per_task=0.0,
                avg_searches_per_task=0.0,
            ),
            health_matrix=[],
            alerts=[],
            agent_comparison=[],
        )
