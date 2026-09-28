from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

import psycopg


class ManagedScriptRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ManagedScriptRecord:
    id: str
    slug: str
    name: str
    description: str
    kind: str
    action_key: str
    workspace_id: str | None
    autostart_enabled: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ManagedScriptStore(Protocol):
    def list_all(self) -> list[ManagedScriptRecord]: ...

    def get(self, script_id: str) -> ManagedScriptRecord | None: ...

    def get_by_slug(self, slug: str) -> ManagedScriptRecord | None: ...

    def insert(self, record: ManagedScriptRecord) -> ManagedScriptRecord: ...

    def delete_by_slug(self, slug: str) -> None: ...

    def set_autostart(self, script_id: str, enabled: bool) -> ManagedScriptRecord: ...


def new_managed_script_id() -> str:
    return uuid4().hex


class InMemoryManagedScriptRepository:
    def __init__(self) -> None:
        self._items: dict[str, ManagedScriptRecord] = {}

    def list_all(self) -> list[ManagedScriptRecord]:
        return sorted(
            self._items.values(),
            key=lambda item: (item.kind, item.sort_order, item.name),
        )

    def get(self, script_id: str) -> ManagedScriptRecord | None:
        return self._items.get(script_id)

    def get_by_slug(self, slug: str) -> ManagedScriptRecord | None:
        return next((item for item in self._items.values() if item.slug == slug), None)

    def insert(self, record: ManagedScriptRecord) -> ManagedScriptRecord:
        if self.get_by_slug(record.slug) is not None:
            raise ManagedScriptRepositoryError(f"脚本 {record.slug} 已存在")
        self._items[record.id] = record
        return record

    def delete_by_slug(self, slug: str) -> None:
        current = self.get_by_slug(slug)
        if current is not None:
            del self._items[current.id]

    def set_autostart(self, script_id: str, enabled: bool) -> ManagedScriptRecord:
        current = self._items.get(script_id)
        if current is None:
            raise ManagedScriptRepositoryError("找不到脚本")
        updated = replace(current, autostart_enabled=enabled, updated_at=datetime.now(UTC))
        self._items[script_id] = updated
        return updated


class PostgresManagedScriptRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def list_all(self) -> list[ManagedScriptRecord]:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                rows = connection.execute(
                    """SELECT id, slug, name, description, kind, action_key, workspace_id,
                              autostart_enabled, sort_order, created_at, updated_at
                         FROM managed_scripts
                        ORDER BY kind, sort_order, name"""
                ).fetchall()
        except psycopg.Error as exc:
            raise ManagedScriptRepositoryError("读取脚本管理配置失败") from exc
        return [self._row(row) for row in rows]

    def get(self, script_id: str) -> ManagedScriptRecord | None:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """SELECT id, slug, name, description, kind, action_key, workspace_id,
                              autostart_enabled, sort_order, created_at, updated_at
                         FROM managed_scripts
                        WHERE id = %s""",
                    (script_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise ManagedScriptRepositoryError("读取脚本管理配置失败") from exc
        return None if row is None else self._row(row)

    def get_by_slug(self, slug: str) -> ManagedScriptRecord | None:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """SELECT id, slug, name, description, kind, action_key, workspace_id,
                              autostart_enabled, sort_order, created_at, updated_at
                         FROM managed_scripts
                        WHERE slug = %s""",
                    (slug,),
                ).fetchone()
        except psycopg.Error as exc:
            raise ManagedScriptRepositoryError("读取脚本管理配置失败") from exc
        return None if row is None else self._row(row)

    def insert(self, record: ManagedScriptRecord) -> ManagedScriptRecord:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                connection.execute(
                    """INSERT INTO managed_scripts (
                           id, slug, name, description, kind, action_key, workspace_id,
                           autostart_enabled, sort_order, created_at, updated_at
                       ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        record.id,
                        record.slug,
                        record.name,
                        record.description,
                        record.kind,
                        record.action_key,
                        record.workspace_id,
                        record.autostart_enabled,
                        record.sort_order,
                        record.created_at,
                        record.updated_at,
                    ),
                )
        except psycopg.Error as exc:
            raise ManagedScriptRepositoryError("保存脚本管理配置失败") from exc
        return record

    def delete_by_slug(self, slug: str) -> None:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                connection.execute(
                    "DELETE FROM managed_scripts WHERE slug = %s",
                    (slug,),
                )
        except psycopg.Error as exc:
            raise ManagedScriptRepositoryError("删除脚本管理配置失败") from exc

    def set_autostart(self, script_id: str, enabled: bool) -> ManagedScriptRecord:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """UPDATE managed_scripts
                          SET autostart_enabled = %s,
                              updated_at = NOW()
                        WHERE id = %s
                    RETURNING id, slug, name, description, kind, action_key, workspace_id,
                              autostart_enabled, sort_order, created_at, updated_at""",
                    (enabled, script_id),
                ).fetchone()
        except psycopg.Error as exc:
            raise ManagedScriptRepositoryError("更新项目启动开关失败") from exc
        if row is None:
            raise ManagedScriptRepositoryError("找不到脚本")
        return self._row(row)

    def _require_database_url(self) -> str:
        if not self._database_url:
            raise ManagedScriptRepositoryError("控制面数据库未配置")
        return self._database_url

    @staticmethod
    def _row(row: tuple[object, ...]) -> ManagedScriptRecord:
        return ManagedScriptRecord(
            id=str(row[0]),
            slug=str(row[1]),
            name=str(row[2]),
            description=str(row[3]),
            kind=str(row[4]),
            action_key=str(row[5]),
            workspace_id=None if row[6] is None else str(row[6]),
            autostart_enabled=bool(row[7]),
            sort_order=int(row[8]),
            created_at=row[9],  # type: ignore[arg-type]
            updated_at=row[10],  # type: ignore[arg-type]
        )
