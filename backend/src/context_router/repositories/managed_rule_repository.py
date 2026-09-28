from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

import psycopg


class ManagedRuleRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ManagedRuleRecord:
    id: str
    slug: str
    title: str
    body: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ManagedRuleStore(Protocol):
    def list_all(self) -> list[ManagedRuleRecord]: ...

    def get(self, rule_id: str) -> ManagedRuleRecord | None: ...

    def get_by_slug(self, slug: str) -> ManagedRuleRecord | None: ...

    def insert(self, record: ManagedRuleRecord) -> ManagedRuleRecord: ...

    def update(self, record: ManagedRuleRecord) -> ManagedRuleRecord: ...

    def delete(self, rule_id: str) -> None: ...


def new_managed_rule_id() -> str:
    return uuid4().hex


class InMemoryManagedRuleRepository:
    def __init__(self) -> None:
        self._items: dict[str, ManagedRuleRecord] = {}

    def list_all(self) -> list[ManagedRuleRecord]:
        return sorted(self._items.values(), key=lambda item: (item.sort_order, item.title))

    def get(self, rule_id: str) -> ManagedRuleRecord | None:
        return self._items.get(rule_id)

    def get_by_slug(self, slug: str) -> ManagedRuleRecord | None:
        return next((item for item in self._items.values() if item.slug == slug), None)

    def insert(self, record: ManagedRuleRecord) -> ManagedRuleRecord:
        if self.get_by_slug(record.slug) is not None:
            raise ManagedRuleRepositoryError(f"规则 {record.slug} 已存在")
        self._items[record.id] = record
        return record

    def update(self, record: ManagedRuleRecord) -> ManagedRuleRecord:
        if record.id not in self._items:
            raise ManagedRuleRepositoryError("找不到规则")
        self._items[record.id] = record
        return record

    def delete(self, rule_id: str) -> None:
        if rule_id not in self._items:
            raise ManagedRuleRepositoryError("找不到规则")
        del self._items[rule_id]


class PostgresManagedRuleRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def list_all(self) -> list[ManagedRuleRecord]:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                rows = connection.execute(
                    """SELECT id, slug, title, body, sort_order, created_at, updated_at
                         FROM managed_rules
                        ORDER BY sort_order, title"""
                ).fetchall()
        except psycopg.Error as exc:
            raise ManagedRuleRepositoryError("读取规则失败") from exc
        return [self._row(row) for row in rows]

    def get(self, rule_id: str) -> ManagedRuleRecord | None:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """SELECT id, slug, title, body, sort_order, created_at, updated_at
                         FROM managed_rules
                        WHERE id = %s""",
                    (rule_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise ManagedRuleRepositoryError("读取规则失败") from exc
        return None if row is None else self._row(row)

    def get_by_slug(self, slug: str) -> ManagedRuleRecord | None:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """SELECT id, slug, title, body, sort_order, created_at, updated_at
                         FROM managed_rules
                        WHERE slug = %s""",
                    (slug,),
                ).fetchone()
        except psycopg.Error as exc:
            raise ManagedRuleRepositoryError("读取规则失败") from exc
        return None if row is None else self._row(row)

    def insert(self, record: ManagedRuleRecord) -> ManagedRuleRecord:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                connection.execute(
                    """INSERT INTO managed_rules (
                           id, slug, title, body, sort_order, created_at, updated_at
                       ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        record.id,
                        record.slug,
                        record.title,
                        record.body,
                        record.sort_order,
                        record.created_at,
                        record.updated_at,
                    ),
                )
        except psycopg.Error as exc:
            raise ManagedRuleRepositoryError("保存规则失败") from exc
        return record

    def update(self, record: ManagedRuleRecord) -> ManagedRuleRecord:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """UPDATE managed_rules
                          SET title = %s,
                              body = %s,
                              sort_order = %s,
                              updated_at = %s
                        WHERE id = %s
                    RETURNING id, slug, title, body, sort_order, created_at, updated_at""",
                    (
                        record.title,
                        record.body,
                        record.sort_order,
                        record.updated_at,
                        record.id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise ManagedRuleRepositoryError("更新规则失败") from exc
        if row is None:
            raise ManagedRuleRepositoryError("找不到规则")
        return self._row(row)

    def delete(self, rule_id: str) -> None:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    "DELETE FROM managed_rules WHERE id = %s RETURNING id",
                    (rule_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise ManagedRuleRepositoryError("删除规则失败") from exc
        if row is None:
            raise ManagedRuleRepositoryError("找不到规则")

    def _require_database_url(self) -> str:
        if not self._database_url:
            raise ManagedRuleRepositoryError("控制面数据库未配置")
        return self._database_url

    @staticmethod
    def _row(row: tuple[object, ...]) -> ManagedRuleRecord:
        return ManagedRuleRecord(
            id=str(row[0]),
            slug=str(row[1]),
            title=str(row[2]),
            body=str(row[3]),
            sort_order=int(row[4]),
            created_at=row[5],  # type: ignore[arg-type]
            updated_at=row[6],  # type: ignore[arg-type]
        )


def touch_rule(record: ManagedRuleRecord, **changes: object) -> ManagedRuleRecord:
    return replace(record, **changes, updated_at=datetime.now(UTC))
