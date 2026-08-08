from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb


class SystemGuideRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SystemGuideRecord:
    id: str
    guide_key: str
    document: dict[str, Any]
    include_in_prepare: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class SystemGuideStore(Protocol):
    def list_guides(self) -> list[SystemGuideRecord]: ...

    def get_guide(self, guide_id: str) -> SystemGuideRecord: ...

    def get_guide_by_key(self, guide_key: str) -> SystemGuideRecord: ...

    def create_guide(
        self,
        *,
        guide_key: str,
        document: dict[str, Any],
        include_in_prepare: bool,
        sort_order: int,
    ) -> SystemGuideRecord: ...

    def update_guide(
        self,
        guide_id: str,
        *,
        guide_key: str,
        document: dict[str, Any],
        include_in_prepare: bool,
        sort_order: int,
    ) -> SystemGuideRecord: ...

    def delete_guide(self, guide_id: str) -> None: ...


class InMemorySystemGuideRepository:
    def __init__(self, records: list[SystemGuideRecord] | None = None) -> None:
        self._records = {item.id: item for item in records or []}

    def list_guides(self) -> list[SystemGuideRecord]:
        return sorted(
            self._records.values(),
            key=lambda item: (item.sort_order, item.created_at, item.id),
        )

    def get_guide(self, guide_id: str) -> SystemGuideRecord:
        record = self._records.get(guide_id)
        if record is None:
            raise SystemGuideRepositoryError("系统文档不存在")
        return record

    def get_guide_by_key(self, guide_key: str) -> SystemGuideRecord:
        record = next(
            (item for item in self._records.values() if item.guide_key == guide_key),
            None,
        )
        if record is None:
            raise SystemGuideRepositoryError("系统文档不存在")
        return record

    def create_guide(
        self,
        *,
        guide_key: str,
        document: dict[str, Any],
        include_in_prepare: bool,
        sort_order: int,
    ) -> SystemGuideRecord:
        if any(item.guide_key == guide_key for item in self._records.values()):
            raise SystemGuideRepositoryError("系统文档 key 已存在")
        now = datetime.now(UTC)
        record = SystemGuideRecord(
            id=uuid4().hex,
            guide_key=guide_key,
            document=document,
            include_in_prepare=include_in_prepare,
            sort_order=sort_order,
            created_at=now,
            updated_at=now,
        )
        self._records[record.id] = record
        return record

    def update_guide(
        self,
        guide_id: str,
        *,
        guide_key: str,
        document: dict[str, Any],
        include_in_prepare: bool,
        sort_order: int,
    ) -> SystemGuideRecord:
        current = self.get_guide(guide_id)
        if any(
            item.id != guide_id and item.guide_key == guide_key for item in self._records.values()
        ):
            raise SystemGuideRepositoryError("系统文档 key 已存在")
        record = replace(
            current,
            guide_key=guide_key,
            document=document,
            include_in_prepare=include_in_prepare,
            sort_order=sort_order,
            updated_at=datetime.now(UTC),
        )
        self._records[guide_id] = record
        return record

    def delete_guide(self, guide_id: str) -> None:
        self.get_guide(guide_id)
        del self._records[guide_id]


class PostgresSystemGuideRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def list_guides(self) -> list[SystemGuideRecord]:
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """SELECT id, guide_key, document, include_in_prepare, sort_order,
                              created_at, updated_at
                       FROM system_guides
                       ORDER BY sort_order, created_at, id"""
                ).fetchall()
        except psycopg.Error as exc:
            raise SystemGuideRepositoryError("系统文档读取失败") from exc
        return [self._record(row) for row in rows]

    def get_guide(self, guide_id: str) -> SystemGuideRecord:
        return self._get("id", guide_id)

    def get_guide_by_key(self, guide_key: str) -> SystemGuideRecord:
        return self._get("guide_key", guide_key)

    def _get(self, column: str, value: str) -> SystemGuideRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    f"""SELECT id, guide_key, document, include_in_prepare, sort_order,
                               created_at, updated_at
                        FROM system_guides WHERE {column} = %s""",  # noqa: S608
                    (value,),
                ).fetchone()
        except psycopg.Error as exc:
            raise SystemGuideRepositoryError("系统文档读取失败") from exc
        if row is None:
            raise SystemGuideRepositoryError("系统文档不存在")
        return self._record(row)

    def create_guide(
        self,
        *,
        guide_key: str,
        document: dict[str, Any],
        include_in_prepare: bool,
        sort_order: int,
    ) -> SystemGuideRecord:
        guide_id = uuid4().hex
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """INSERT INTO system_guides
                       (id, guide_key, document, include_in_prepare, sort_order)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (guide_id, guide_key, Jsonb(document), include_in_prepare, sort_order),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise SystemGuideRepositoryError("系统文档 key 已存在") from exc
        except psycopg.Error as exc:
            raise SystemGuideRepositoryError("系统文档写入失败") from exc
        return self.get_guide(guide_id)

    def update_guide(
        self,
        guide_id: str,
        *,
        guide_key: str,
        document: dict[str, Any],
        include_in_prepare: bool,
        sort_order: int,
    ) -> SystemGuideRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                result = connection.execute(
                    """UPDATE system_guides
                       SET guide_key = %s, document = %s, include_in_prepare = %s,
                           sort_order = %s, updated_at = CURRENT_TIMESTAMP
                       WHERE id = %s""",
                    (guide_key, Jsonb(document), include_in_prepare, sort_order, guide_id),
                )
                if result.rowcount == 0:
                    raise SystemGuideRepositoryError("系统文档不存在")
        except psycopg.errors.UniqueViolation as exc:
            raise SystemGuideRepositoryError("系统文档 key 已存在") from exc
        except SystemGuideRepositoryError:
            raise
        except psycopg.Error as exc:
            raise SystemGuideRepositoryError("系统文档更新失败") from exc
        return self.get_guide(guide_id)

    def delete_guide(self, guide_id: str) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                result = connection.execute(
                    "DELETE FROM system_guides WHERE id = %s",
                    (guide_id,),
                )
                if result.rowcount == 0:
                    raise SystemGuideRepositoryError("系统文档不存在")
        except SystemGuideRepositoryError:
            raise
        except psycopg.Error as exc:
            raise SystemGuideRepositoryError("系统文档删除失败") from exc

    @staticmethod
    def _record(row: tuple[object, ...]) -> SystemGuideRecord:
        return SystemGuideRecord(
            id=str(row[0]),
            guide_key=str(row[1]),
            document=dict(row[2]),
            include_in_prepare=bool(row[3]),
            sort_order=int(row[4]),
            created_at=row[5],
            updated_at=row[6],
        )
