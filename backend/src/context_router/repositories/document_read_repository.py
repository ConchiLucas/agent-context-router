from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import psycopg


class DocumentReadRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DocumentReadItemWrite:
    position: int
    document_id: str
    document_path: str | None
    requested_section: str | None
    status: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentReadItemRecord(DocumentReadItemWrite):
    id: int = 0


@dataclass(frozen=True, slots=True)
class DocumentReadCallRecord:
    id: int
    task_id: int
    created_at: datetime
    items: list[DocumentReadItemRecord]


class DocumentReadStore(Protocol):
    def create_read_call(
        self,
        *,
        task_id: int,
        items: list[DocumentReadItemWrite],
    ) -> int: ...

    def list_read_calls(self, task_id: int) -> list[DocumentReadCallRecord]: ...


class PostgresDocumentReadRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def create_read_call(
        self,
        *,
        task_id: int,
        items: list[DocumentReadItemWrite],
    ) -> int:
        if not self._database_url:
            raise DocumentReadRepositoryError("任务数据库尚未配置")

        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    INSERT INTO mcp_document_read_calls (task_id)
                    VALUES (%s)
                    RETURNING id
                    """,
                    (task_id,),
                ).fetchone()
                if row is None:
                    raise DocumentReadRepositoryError("读取调用写入后没有返回调用号")
                read_call_id = int(row[0])
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO mcp_document_read_items (
                            read_call_id,
                            position,
                            document_id,
                            document_path,
                            requested_section,
                            status,
                            error_code
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                read_call_id,
                                item.position,
                                item.document_id,
                                item.document_path,
                                item.requested_section,
                                item.status,
                                item.error_code,
                            )
                            for item in items
                        ],
                    )
        except DocumentReadRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DocumentReadRepositoryError("文档读取记录写入失败") from exc
        return read_call_id

    def list_read_calls(self, task_id: int) -> list[DocumentReadCallRecord]:
        if not self._database_url:
            raise DocumentReadRepositoryError("任务数据库尚未配置")

        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        read_call.id,
                        read_call.task_id,
                        read_call.created_at,
                        item.id,
                        item.position,
                        item.document_id,
                        item.document_path,
                        item.requested_section,
                        item.status,
                        item.error_code
                    FROM mcp_document_read_calls AS read_call
                    LEFT JOIN mcp_document_read_items AS item
                        ON item.read_call_id = read_call.id
                    WHERE read_call.task_id = %s
                    ORDER BY read_call.id, item.position
                    """,
                    (task_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise DocumentReadRepositoryError("文档读取历史读取失败") from exc

        calls: list[DocumentReadCallRecord] = []
        current_call_id: int | None = None
        current_items: list[DocumentReadItemRecord] = []
        current_task_id = task_id
        current_created_at: datetime | None = None

        for row in rows:
            call_id = int(row[0])
            if current_call_id is not None and call_id != current_call_id:
                calls.append(
                    DocumentReadCallRecord(
                        id=current_call_id,
                        task_id=current_task_id,
                        created_at=current_created_at,  # type: ignore[arg-type]
                        items=current_items,
                    )
                )
                current_items = []

            current_call_id = call_id
            current_task_id = int(row[1])
            current_created_at = row[2]
            if row[3] is not None:
                current_items.append(
                    DocumentReadItemRecord(
                        id=int(row[3]),
                        position=int(row[4]),
                        document_id=str(row[5]),
                        document_path=str(row[6]) if row[6] is not None else None,
                        requested_section=str(row[7]) if row[7] is not None else None,
                        status=str(row[8]),
                        error_code=str(row[9]) if row[9] is not None else None,
                    )
                )

        if current_call_id is not None and current_created_at is not None:
            calls.append(
                DocumentReadCallRecord(
                    id=current_call_id,
                    task_id=current_task_id,
                    created_at=current_created_at,
                    items=current_items,
                )
            )
        return calls
