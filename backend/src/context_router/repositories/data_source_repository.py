from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb


class DataSourceRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DataSourceRecord:
    id: str
    name: str
    category: str
    engine: str
    description: str
    connection_config: dict[str, Any]
    enabled: bool
    config_version: int
    database_count: int
    project_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DataSourceDatabaseRecord:
    id: str
    data_source_id: str
    remote_name: str
    display_name: str
    namespace_type: str
    available: bool
    system_database: bool
    metadata: dict[str, Any]
    project_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectDatabaseLinkRecord:
    id: str
    project_id: str
    project_name: str
    database_id: str
    database_name: str
    data_source_id: str
    data_source_name: str
    engine: str
    alias: str
    purpose: str
    enabled: bool
    readonly: bool
    allowed_schemas: list[str]
    max_rows: int
    max_result_bytes: int
    query_timeout_ms: int
    created_at: datetime
    updated_at: datetime


class DataSourceStore(Protocol):
    def list_data_sources(self) -> list[DataSourceRecord]: ...
    def get_data_source(self, data_source_id: str) -> DataSourceRecord: ...
    def create_data_source(self, record: DataSourceRecord) -> None: ...
    def update_data_source(self, record: DataSourceRecord) -> None: ...
    def delete_data_source(self, data_source_id: str) -> None: ...
    def list_databases(self, data_source_id: str) -> list[DataSourceDatabaseRecord]: ...
    def get_database(self, database_id: str) -> DataSourceDatabaseRecord: ...
    def create_database(self, record: DataSourceDatabaseRecord) -> None: ...
    def update_database(self, record: DataSourceDatabaseRecord) -> None: ...
    def delete_database(self, database_id: str) -> None: ...
    def sync_databases(
        self, data_source_id: str, records: list[DataSourceDatabaseRecord]
    ) -> None: ...
    def list_links(
        self, *, project_id: str | None = None, database_id: str | None = None
    ) -> list[ProjectDatabaseLinkRecord]: ...
    def create_link(self, record: ProjectDatabaseLinkRecord) -> None: ...
    def update_link(self, record: ProjectDatabaseLinkRecord) -> None: ...
    def delete_link(self, link_id: str) -> None: ...
    def replace_project_links(
        self, project_id: str, records: list[ProjectDatabaseLinkRecord]
    ) -> None: ...


class InMemoryDataSourceRepository:
    def __init__(self) -> None:
        self._sources: dict[str, DataSourceRecord] = {}
        self._databases: dict[str, DataSourceDatabaseRecord] = {}
        self._links: dict[str, ProjectDatabaseLinkRecord] = {}

    def list_data_sources(self) -> list[DataSourceRecord]:
        return [self._hydrate_source(item) for item in self._sources.values()]

    def get_data_source(self, data_source_id: str) -> DataSourceRecord:
        record = self._sources.get(data_source_id)
        if record is None:
            raise DataSourceRepositoryError("数据源不存在")
        return self._hydrate_source(record)

    def create_data_source(self, record: DataSourceRecord) -> None:
        if any(item.name == record.name for item in self._sources.values()):
            raise DataSourceRepositoryError("数据源名称已存在")
        self._sources[record.id] = record

    def update_data_source(self, record: DataSourceRecord) -> None:
        self.get_data_source(record.id)
        if any(
            item.id != record.id and item.name == record.name for item in self._sources.values()
        ):
            raise DataSourceRepositoryError("数据源名称已存在")
        self._sources[record.id] = record

    def delete_data_source(self, data_source_id: str) -> None:
        self.get_data_source(data_source_id)
        database_ids = {
            item.id for item in self._databases.values() if item.data_source_id == data_source_id
        }
        self._links = {
            key: item for key, item in self._links.items() if item.database_id not in database_ids
        }
        self._databases = {
            key: item
            for key, item in self._databases.items()
            if item.data_source_id != data_source_id
        }
        del self._sources[data_source_id]

    def list_databases(self, data_source_id: str) -> list[DataSourceDatabaseRecord]:
        self.get_data_source(data_source_id)
        return [
            self._hydrate_database(item)
            for item in self._databases.values()
            if item.data_source_id == data_source_id
        ]

    def get_database(self, database_id: str) -> DataSourceDatabaseRecord:
        record = self._databases.get(database_id)
        if record is None:
            raise DataSourceRepositoryError("数据库不存在")
        return self._hydrate_database(record)

    def create_database(self, record: DataSourceDatabaseRecord) -> None:
        self.get_data_source(record.data_source_id)
        if any(
            item.data_source_id == record.data_source_id and item.remote_name == record.remote_name
            for item in self._databases.values()
        ):
            raise DataSourceRepositoryError("该数据源下已经存在同名数据库")
        self._databases[record.id] = record

    def update_database(self, record: DataSourceDatabaseRecord) -> None:
        self.get_database(record.id)
        if any(
            item.id != record.id
            and item.data_source_id == record.data_source_id
            and item.remote_name == record.remote_name
            for item in self._databases.values()
        ):
            raise DataSourceRepositoryError("该数据源下已经存在同名数据库")
        self._databases[record.id] = record

    def delete_database(self, database_id: str) -> None:
        self.get_database(database_id)
        self._links = {
            key: item for key, item in self._links.items() if item.database_id != database_id
        }
        del self._databases[database_id]

    def sync_databases(self, data_source_id: str, records: list[DataSourceDatabaseRecord]) -> None:
        self.get_data_source(data_source_id)
        discovered_by_name = {record.remote_name: record for record in records}
        existing_by_name = {
            record.remote_name: record
            for record in self._databases.values()
            if record.data_source_id == data_source_id
        }
        now = max((record.updated_at for record in records), default=None)
        for existing in existing_by_name.values():
            if existing.remote_name not in discovered_by_name:
                self._databases[existing.id] = replace(
                    existing,
                    available=False,
                    updated_at=now or existing.updated_at,
                )
        for discovered in records:
            existing = existing_by_name.get(discovered.remote_name)
            if existing is None:
                self._databases[discovered.id] = discovered
                continue
            self._databases[existing.id] = replace(
                existing,
                namespace_type=discovered.namespace_type,
                available=True,
                system_database=discovered.system_database,
                metadata=discovered.metadata,
                updated_at=discovered.updated_at,
            )

    def list_links(
        self, *, project_id: str | None = None, database_id: str | None = None
    ) -> list[ProjectDatabaseLinkRecord]:
        return [
            item
            for item in self._links.values()
            if (project_id is None or item.project_id == project_id)
            and (database_id is None or item.database_id == database_id)
        ]

    def create_link(self, record: ProjectDatabaseLinkRecord) -> None:
        self.get_database(record.database_id)
        if any(
            item.project_id == record.project_id and item.database_id == record.database_id
            for item in self._links.values()
        ):
            raise DataSourceRepositoryError("项目已经关联这个数据库")
        self._links[record.id] = record

    def update_link(self, record: ProjectDatabaseLinkRecord) -> None:
        if record.id not in self._links:
            raise DataSourceRepositoryError("项目数据库关联不存在")
        self._links[record.id] = record

    def delete_link(self, link_id: str) -> None:
        if link_id not in self._links:
            raise DataSourceRepositoryError("项目数据库关联不存在")
        del self._links[link_id]

    def replace_project_links(
        self, project_id: str, records: list[ProjectDatabaseLinkRecord]
    ) -> None:
        retained = {key: item for key, item in self._links.items() if item.project_id != project_id}
        retained.update({record.id: record for record in records})
        self._links = retained

    def _hydrate_source(self, record: DataSourceRecord) -> DataSourceRecord:
        database_ids = {
            item.id for item in self._databases.values() if item.data_source_id == record.id
        }
        project_ids = {
            item.project_id for item in self._links.values() if item.database_id in database_ids
        }
        return replace(
            record,
            database_count=len(database_ids),
            project_count=len(project_ids),
        )

    def _hydrate_database(self, record: DataSourceDatabaseRecord) -> DataSourceDatabaseRecord:
        return replace(
            record,
            project_count=sum(1 for item in self._links.values() if item.database_id == record.id),
        )


class PostgresDataSourceRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.strip()

    def list_data_sources(self) -> list[DataSourceRecord]:
        with self._connect("数据源读取失败") as connection:
            rows = connection.execute(
                self._source_select() + " GROUP BY source.id ORDER BY source.created_at, source.id"
            ).fetchall()
        return [self._source_record(row) for row in rows]

    def get_data_source(self, data_source_id: str) -> DataSourceRecord:
        with self._connect("数据源读取失败") as connection:
            row = connection.execute(
                self._source_select() + " WHERE source.id = %s GROUP BY source.id",
                (data_source_id,),
            ).fetchone()
        if row is None:
            raise DataSourceRepositoryError("数据源不存在")
        return self._source_record(row)

    def create_data_source(self, record: DataSourceRecord) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """INSERT INTO data_sources
                    (id, name, category, engine, description, connection_config, enabled,
                     config_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        record.id,
                        record.name,
                        record.category,
                        record.engine,
                        record.description,
                        Jsonb(record.connection_config),
                        record.enabled,
                        record.config_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError("数据源名称已存在") from exc
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("数据源写入失败") from exc

    def update_data_source(self, record: DataSourceRecord) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    """UPDATE data_sources SET name=%s, category=%s, engine=%s,
                    description=%s, connection_config=%s, enabled=%s, config_version=%s,
                    updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                    (
                        record.name,
                        record.category,
                        record.engine,
                        record.description,
                        Jsonb(record.connection_config),
                        record.enabled,
                        record.config_version,
                        record.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise DataSourceRepositoryError("数据源不存在")
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError("数据源名称已存在") from exc
        except DataSourceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("数据源更新失败") from exc

    def delete_data_source(self, data_source_id: str) -> None:
        self._delete("data_sources", data_source_id, "数据源不存在", "数据源删除失败")

    def list_databases(self, data_source_id: str) -> list[DataSourceDatabaseRecord]:
        self.get_data_source(data_source_id)
        with self._connect("数据库清单读取失败") as connection:
            rows = connection.execute(
                self._database_select()
                + " WHERE database.data_source_id=%s"
                + " GROUP BY database.id"
                + " ORDER BY database.system_database, database.remote_name",
                (data_source_id,),
            ).fetchall()
        return [self._database_record(row) for row in rows]

    def get_database(self, database_id: str) -> DataSourceDatabaseRecord:
        with self._connect("数据库读取失败") as connection:
            row = connection.execute(
                self._database_select() + " WHERE database.id=%s GROUP BY database.id",
                (database_id,),
            ).fetchone()
        if row is None:
            raise DataSourceRepositoryError("数据库不存在")
        return self._database_record(row)

    def create_database(self, record: DataSourceDatabaseRecord) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """INSERT INTO data_source_databases
                    (id, data_source_id, remote_name, display_name, namespace_type,
                     available, system_database, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        record.id,
                        record.data_source_id,
                        record.remote_name,
                        record.display_name,
                        record.namespace_type,
                        record.available,
                        record.system_database,
                        Jsonb(record.metadata),
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError("该数据源下已经存在同名数据库") from exc
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("数据库写入失败") from exc

    def update_database(self, record: DataSourceDatabaseRecord) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    """UPDATE data_source_databases SET remote_name=%s, display_name=%s,
                    namespace_type=%s, available=%s, system_database=%s, metadata=%s,
                    updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                    (
                        record.remote_name,
                        record.display_name,
                        record.namespace_type,
                        record.available,
                        record.system_database,
                        Jsonb(record.metadata),
                        record.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise DataSourceRepositoryError("数据库不存在")
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError("该数据源下已经存在同名数据库") from exc
        except DataSourceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("数据库更新失败") from exc

    def delete_database(self, database_id: str) -> None:
        self._delete("data_source_databases", database_id, "数据库不存在", "数据库删除失败")

    def sync_databases(self, data_source_id: str, records: list[DataSourceDatabaseRecord]) -> None:
        database_names = [record.remote_name for record in records]
        try:
            with psycopg.connect(self._database_url) as connection:
                if database_names:
                    connection.execute(
                        """UPDATE data_source_databases
                        SET available=false, updated_at=CURRENT_TIMESTAMP
                        WHERE data_source_id=%s AND NOT (remote_name=ANY(%s))""",
                        (data_source_id, database_names),
                    )
                for record in records:
                    connection.execute(
                        """INSERT INTO data_source_databases
                        (id, data_source_id, remote_name, display_name, namespace_type,
                         available, system_database, metadata)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (data_source_id, remote_name) DO UPDATE SET
                          namespace_type=EXCLUDED.namespace_type,
                          available=EXCLUDED.available,
                          system_database=EXCLUDED.system_database,
                          metadata=EXCLUDED.metadata,
                          updated_at=CURRENT_TIMESTAMP""",
                        (
                            record.id,
                            record.data_source_id,
                            record.remote_name,
                            record.display_name,
                            record.namespace_type,
                            record.available,
                            record.system_database,
                            Jsonb(record.metadata),
                        ),
                    )
        except psycopg.errors.ForeignKeyViolation as exc:
            raise DataSourceRepositoryError("数据源不存在") from exc
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("数据库清单同步失败") from exc

    def list_links(
        self, *, project_id: str | None = None, database_id: str | None = None
    ) -> list[ProjectDatabaseLinkRecord]:
        where: list[str] = []
        params: list[str] = []
        if project_id is not None:
            where.append("link.project_id=%s")
            params.append(project_id)
        if database_id is not None:
            where.append("link.database_id=%s")
            params.append(database_id)
        suffix = (" WHERE " + " AND ".join(where)) if where else ""
        with self._connect("项目数据库关联读取失败") as connection:
            rows = connection.execute(
                self._link_select() + suffix + " ORDER BY link.created_at, link.id", params
            ).fetchall()
        return [self._link_record(row) for row in rows]

    def create_link(self, record: ProjectDatabaseLinkRecord) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """INSERT INTO project_databases
                    (id, project_id, database_id, alias, purpose, enabled, readonly,
                     allowed_schemas, max_rows, max_result_bytes, query_timeout_ms)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        record.id,
                        record.project_id,
                        record.database_id,
                        record.alias,
                        record.purpose,
                        record.enabled,
                        record.readonly,
                        Jsonb(record.allowed_schemas),
                        record.max_rows,
                        record.max_result_bytes,
                        record.query_timeout_ms,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError("项目已经关联这个数据库") from exc
        except psycopg.errors.ForeignKeyViolation as exc:
            raise DataSourceRepositoryError("项目或数据库不存在") from exc
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("项目数据库关联写入失败") from exc

    def update_link(self, record: ProjectDatabaseLinkRecord) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    """UPDATE project_databases SET alias=%s, purpose=%s, enabled=%s,
                    readonly=%s, allowed_schemas=%s, max_rows=%s, max_result_bytes=%s,
                    query_timeout_ms=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                    (
                        record.alias,
                        record.purpose,
                        record.enabled,
                        record.readonly,
                        Jsonb(record.allowed_schemas),
                        record.max_rows,
                        record.max_result_bytes,
                        record.query_timeout_ms,
                        record.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise DataSourceRepositoryError("项目数据库关联不存在")
        except DataSourceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("项目数据库关联更新失败") from exc

    def delete_link(self, link_id: str) -> None:
        self._delete("project_databases", link_id, "项目数据库关联不存在", "项目数据库关联删除失败")

    def replace_project_links(
        self, project_id: str, records: list[ProjectDatabaseLinkRecord]
    ) -> None:
        database_ids = [record.database_id for record in records]
        try:
            with psycopg.connect(self._database_url) as connection:
                if database_ids:
                    connection.execute(
                        """DELETE FROM project_databases
                        WHERE project_id=%s AND NOT (database_id=ANY(%s))""",
                        (project_id, database_ids),
                    )
                else:
                    connection.execute(
                        "DELETE FROM project_databases WHERE project_id=%s",
                        (project_id,),
                    )
                for record in records:
                    connection.execute(
                        """INSERT INTO project_databases
                        (id, project_id, database_id, alias, purpose, enabled, readonly,
                         allowed_schemas, max_rows, max_result_bytes, query_timeout_ms)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (project_id, database_id) DO NOTHING""",
                        (
                            record.id,
                            record.project_id,
                            record.database_id,
                            record.alias,
                            record.purpose,
                            record.enabled,
                            record.readonly,
                            Jsonb(record.allowed_schemas),
                            record.max_rows,
                            record.max_result_bytes,
                            record.query_timeout_ms,
                        ),
                    )
        except psycopg.errors.ForeignKeyViolation as exc:
            raise DataSourceRepositoryError("项目或数据库不存在") from exc
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("项目数据库关联批量更新失败") from exc

    def _delete(self, table: str, record_id: str, missing: str, failed: str) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(f"DELETE FROM {table} WHERE id=%s", (record_id,))
                if cursor.rowcount == 0:
                    raise DataSourceRepositoryError(missing)
        except DataSourceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DataSourceRepositoryError(failed) from exc

    def _connect(self, message: str):
        try:
            return psycopg.connect(self._database_url)
        except psycopg.Error as exc:
            raise DataSourceRepositoryError(message) from exc

    @staticmethod
    def _source_select() -> str:
        return """SELECT source.id, source.name, source.category, source.engine,
        source.description, source.connection_config, source.enabled, source.config_version,
        COUNT(DISTINCT database.id), COUNT(DISTINCT link.project_id),
        source.created_at, source.updated_at
        FROM data_sources AS source
        LEFT JOIN data_source_databases AS database ON database.data_source_id=source.id
        LEFT JOIN project_databases AS link ON link.database_id=database.id"""

    @staticmethod
    def _database_select() -> str:
        return """SELECT database.id, database.data_source_id, database.remote_name,
        database.display_name, database.namespace_type, database.available,
        database.system_database, database.metadata, COUNT(link.id),
        database.created_at, database.updated_at
        FROM data_source_databases AS database
        LEFT JOIN project_databases AS link ON link.database_id=database.id"""

    @staticmethod
    def _link_select() -> str:
        return """SELECT link.id, link.project_id, project.name, link.database_id,
        database.remote_name, source.id, source.name, source.engine, link.alias,
        link.purpose, link.enabled, link.readonly, link.allowed_schemas, link.max_rows,
        link.max_result_bytes, link.query_timeout_ms, link.created_at, link.updated_at
        FROM project_databases AS link
        JOIN document_projects AS project ON project.id=link.project_id
        JOIN data_source_databases AS database ON database.id=link.database_id
        JOIN data_sources AS source ON source.id=database.data_source_id"""

    @staticmethod
    def _source_record(row: tuple[object, ...]) -> DataSourceRecord:
        return DataSourceRecord(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            dict(row[5]),
            bool(row[6]),
            int(row[7]),
            int(row[8]),
            int(row[9]),
            row[10],
            row[11],
        )

    @staticmethod
    def _database_record(row: tuple[object, ...]) -> DataSourceDatabaseRecord:
        return DataSourceDatabaseRecord(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            bool(row[5]),
            bool(row[6]),
            dict(row[7]),
            int(row[8]),
            row[9],
            row[10],
        )

    @staticmethod
    def _link_record(row: tuple[object, ...]) -> ProjectDatabaseLinkRecord:
        return ProjectDatabaseLinkRecord(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
            str(row[6]),
            str(row[7]),
            str(row[8]),
            str(row[9]),
            bool(row[10]),
            bool(row[11]),
            list(row[12]),
            int(row[13]),
            int(row[14]),
            int(row[15]),
            row[16],
            row[17],
        )
