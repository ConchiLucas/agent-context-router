from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import psycopg

from context_router.schemas.document_read_stats import (
    DocumentReadStatItem,
    DocumentReadTaskItem,
)


class DocumentReadStatsRepositoryError(RuntimeError):
    pass


class DocumentReadStatsStore(Protocol):
    def get_document_read_stats(
        self,
        *,
        workspace_id: str | None = None,
        limit: int = 50,
    ) -> list[DocumentReadStatItem]: ...

    def get_document_read_tasks(
        self,
        document_id: str,
        *,
        limit: int = 50,
    ) -> list[DocumentReadTaskItem]: ...


class PostgresDocumentReadStatsRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def get_document_read_stats(
        self,
        *,
        workspace_id: str | None = None,
        limit: int = 50,
    ) -> list[DocumentReadStatItem]:
        if not self._database_url:
            raise DocumentReadStatsRepositoryError("数据库尚未配置")

        safe_limit = min(max(limit, 1), 200)

        where_clauses = [
            "i.document_id NOT LIKE %s",
            "i.document_id != %s",
        ]
        params: list[object] = ["%/AGENTS.md", "AGENTS.md"]

        if workspace_id:
            where_clauses.append("c.task_id IN (SELECT id FROM mcp_tasks WHERE workspace_id = %s)")
            params.append(workspace_id)

        where_sql = " AND ".join(where_clauses)
        params.append(safe_limit)

        query = f"""
            SELECT
                i.document_id,
                MAX(i.document_path)                  AS document_path,
                COUNT(*)                              AS read_count,
                COUNT(DISTINCT c.task_id)             AS task_count,
                MAX(c.created_at)                     AS last_read_at
            FROM mcp_document_read_items i
            JOIN mcp_document_read_calls c ON c.id = i.read_call_id
            WHERE {where_sql}
            GROUP BY i.document_id
            ORDER BY read_count DESC, last_read_at DESC
            LIMIT %s
        """

        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(query, params).fetchall()
        except psycopg.Error as exc:
            raise DocumentReadStatsRepositoryError("查询文档阅读统计数据失败") from exc

        return [
            DocumentReadStatItem(
                document_id=str(row[0]),
                document_path=str(row[1]) if row[1] is not None else None,
                read_count=int(row[2]),
                task_count=int(row[3]),
                last_read_at=row[4],
            )
            for row in rows
        ]

    def get_document_read_tasks(
        self,
        document_id: str,
        *,
        limit: int = 50,
    ) -> list[DocumentReadTaskItem]:
        if not self._database_url:
            raise DocumentReadStatsRepositoryError("数据库尚未配置")

        safe_limit = min(max(limit, 1), 200)

        query = """
            SELECT
                t.id                                  AS task_id,
                t.task,
                t.agent_name,
                t.cwd,
                t.workspace_name,
                t.active_project_name,
                t.created_at,
                COUNT(*)                              AS read_count,
                ARRAY_AGG(DISTINCT i.requested_section)
                    FILTER (WHERE i.requested_section IS NOT NULL AND i.requested_section != '')
                                                      AS sections
            FROM mcp_document_read_items i
            JOIN mcp_document_read_calls c ON c.id = i.read_call_id
            JOIN mcp_tasks t ON t.id = c.task_id
            WHERE i.document_id = %s
            GROUP BY t.id, t.task, t.agent_name, t.cwd,
                     t.workspace_name, t.active_project_name, t.created_at
            ORDER BY t.created_at DESC
            LIMIT %s
        """

        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(query, (document_id, safe_limit)).fetchall()
        except psycopg.Error as exc:
            raise DocumentReadStatsRepositoryError("查询文档关联任务失败") from exc

        results: list[DocumentReadTaskItem] = []
        for row in rows:
            sections_raw = row[8]
            sections = list(sections_raw) if sections_raw else []
            results.append(
                DocumentReadTaskItem(
                    task_id=int(row[0]),
                    task=str(row[1]),
                    agent_name=str(row[2]) if row[2] is not None else None,
                    cwd=str(row[3]),
                    workspace_name=str(row[4]) if row[4] is not None else None,
                    active_project_name=str(row[5]) if row[5] is not None else None,
                    created_at=row[6],
                    read_count=int(row[7]),
                    sections=sections,
                )
            )
        return results


class InMemoryDocumentReadStatsRepository:
    def get_document_read_stats(
        self,
        *,
        workspace_id: str | None = None,
        limit: int = 50,
    ) -> list[DocumentReadStatItem]:
        return []

    def get_document_read_tasks(
        self,
        document_id: str,
        *,
        limit: int = 50,
    ) -> list[DocumentReadTaskItem]:
        return []

