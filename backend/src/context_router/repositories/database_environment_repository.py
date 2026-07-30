from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

import psycopg
from psycopg.types.json import Jsonb

DatabaseEnvironment = Literal["test", "uat"]
_ENVIRONMENTS: tuple[DatabaseEnvironment, ...] = ("test", "uat")
_MCP_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MAX_ENVIRONMENT_JSON_BYTES = 256 * 1024
_MAX_ENVIRONMENT_JSON_DEPTH = 20
_MAX_ENVIRONMENT_JSON_NODES = 10_000
_MAX_SAFE_JSON_INTEGER = (1 << 53) - 1


class DatabaseEnvironmentRepositoryError(RuntimeError):
    def __init__(self, message: str, *, code: str = "database_environment_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DatabaseEnvironmentConfigRecord:
    workspace_id: str
    active_environment: DatabaseEnvironment | None
    revision: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentPayloadsRecord:
    workspace_id: str
    configured: bool
    environments: dict[DatabaseEnvironment, Any]


@dataclass(frozen=True, slots=True)
class EnvironmentConfigurationSnapshot:
    config: DatabaseEnvironmentConfigRecord
    selector_configured: bool
    payloads: EnvironmentPayloadsRecord


@dataclass(frozen=True, slots=True)
class DatabaseEnvironmentMappingWrite:
    id: str
    workspace_id: str
    project_id: str
    logical_name: str
    mcp_alias: str
    test_link_id: str
    uat_link_id: str


@dataclass(frozen=True, slots=True)
class DatabaseEnvironmentMappingRecord:
    id: str
    workspace_id: str
    project_id: str
    logical_name: str
    mcp_alias: str
    targets: dict[DatabaseEnvironment, str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ResolvedEnvironmentMappingTarget:
    mapping_id: str
    workspace_id: str
    project_id: str
    logical_name: str
    mcp_alias: str
    environment: DatabaseEnvironment
    link_id: str


class DatabaseEnvironmentStore(Protocol):
    def get_active_config(self, workspace_id: str) -> DatabaseEnvironmentConfigRecord: ...

    def get_environment_snapshot(
        self,
        workspace_id: str,
    ) -> EnvironmentConfigurationSnapshot: ...

    def get_environment_payloads(self, workspace_id: str) -> EnvironmentPayloadsRecord: ...

    def list_mappings(self, workspace_id: str) -> list[DatabaseEnvironmentMappingRecord]: ...

    def replace_mappings(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        mappings: list[DatabaseEnvironmentMappingWrite],
    ) -> DatabaseEnvironmentConfigRecord: ...

    def switch_environment(
        self,
        *,
        workspace_id: str,
        environment: DatabaseEnvironment,
        expected_revision: int,
    ) -> DatabaseEnvironmentConfigRecord: ...

    def replace_environment_payloads(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        environments: dict[DatabaseEnvironment, Any],
    ) -> DatabaseEnvironmentConfigRecord: ...

    def resolve_mapping(
        self,
        *,
        workspace_id: str,
        environment: DatabaseEnvironment,
        mcp_alias: str,
    ) -> ResolvedEnvironmentMappingTarget: ...

    def list_mapping_targets(
        self,
        *,
        workspace_id: str,
        environment: DatabaseEnvironment,
    ) -> list[ResolvedEnvironmentMappingTarget]: ...


class InMemoryDatabaseEnvironmentRepository:
    def __init__(self) -> None:
        self._configs: dict[str, DatabaseEnvironmentConfigRecord] = {}
        self._mappings: dict[str, DatabaseEnvironmentMappingRecord] = {}
        self._environment_payloads: dict[str, dict[DatabaseEnvironment, Any]] = {}

    def get_active_config(self, workspace_id: str) -> DatabaseEnvironmentConfigRecord:
        return self._configs.get(workspace_id, _unconfigured_config(workspace_id))

    def get_environment_snapshot(
        self,
        workspace_id: str,
    ) -> EnvironmentConfigurationSnapshot:
        configured = workspace_id in self._configs
        return EnvironmentConfigurationSnapshot(
            config=self.get_active_config(workspace_id),
            selector_configured=configured,
            payloads=self.get_environment_payloads(workspace_id),
        )

    def get_environment_payloads(self, workspace_id: str) -> EnvironmentPayloadsRecord:
        values = self._environment_payloads.get(workspace_id, _empty_environment_payloads())
        return EnvironmentPayloadsRecord(
            workspace_id=workspace_id,
            configured=workspace_id in self._environment_payloads,
            environments=copy.deepcopy(values),
        )

    def list_mappings(self, workspace_id: str) -> list[DatabaseEnvironmentMappingRecord]:
        return sorted(
            (
                mapping
                for mapping in self._mappings.values()
                if mapping.workspace_id == workspace_id
            ),
            key=lambda item: (item.project_id, item.mcp_alias.casefold(), item.id),
        )

    def replace_mappings(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        mappings: list[DatabaseEnvironmentMappingWrite],
    ) -> DatabaseEnvironmentConfigRecord:
        current = self.get_active_config(workspace_id)
        _ensure_revision(current.revision, expected_revision)
        _validate_mapping_writes(workspace_id, mappings)
        existing_ids = {
            mapping.id
            for mapping in self._mappings.values()
            if mapping.workspace_id != workspace_id
        }
        if existing_ids.intersection(mapping.id for mapping in mappings):
            raise DatabaseEnvironmentRepositoryError("环境映射 ID 已被其他工作空间使用")

        previous_by_id = {
            mapping.id: mapping
            for mapping in self._mappings.values()
            if mapping.workspace_id == workspace_id
        }
        self._mappings = {
            mapping_id: mapping
            for mapping_id, mapping in self._mappings.items()
            if mapping.workspace_id != workspace_id
        }
        now = datetime.now(UTC)
        for mapping in mappings:
            previous = previous_by_id.get(mapping.id)
            self._mappings[mapping.id] = DatabaseEnvironmentMappingRecord(
                id=mapping.id,
                workspace_id=workspace_id,
                project_id=mapping.project_id,
                logical_name=mapping.logical_name,
                mcp_alias=mapping.mcp_alias,
                targets={
                    "test": mapping.test_link_id,
                    "uat": mapping.uat_link_id,
                },
                created_at=previous.created_at if previous is not None else now,
                updated_at=now,
            )

        saved = DatabaseEnvironmentConfigRecord(
            workspace_id=workspace_id,
            active_environment=current.active_environment or "uat",
            revision=current.revision + 1,
            created_at=current.created_at or now,
            updated_at=now,
        )
        self._configs[workspace_id] = saved
        return saved

    def switch_environment(
        self,
        *,
        workspace_id: str,
        environment: DatabaseEnvironment,
        expected_revision: int,
    ) -> DatabaseEnvironmentConfigRecord:
        _ensure_environment(environment)
        current = self.get_active_config(workspace_id)
        selector_configured = workspace_id in self._configs
        payloads_configured = workspace_id in self._environment_payloads
        if not selector_configured:
            raise DatabaseEnvironmentRepositoryError("工作空间尚未配置环境")
        _ensure_revision(current.revision, expected_revision)
        mappings = self.list_mappings(workspace_id)
        if mappings:
            for mapping in mappings:
                if set(mapping.targets) != set(_ENVIRONMENTS):
                    raise DatabaseEnvironmentRepositoryError("数据库环境映射不完整，无法切换")
        elif not payloads_configured:
            raise DatabaseEnvironmentRepositoryError("工作空间环境配置不完整")
        now = datetime.now(UTC)
        saved = DatabaseEnvironmentConfigRecord(
            workspace_id=workspace_id,
            active_environment=environment,
            revision=current.revision + 1,
            created_at=current.created_at,
            updated_at=now,
        )
        self._configs[workspace_id] = saved
        return saved

    def replace_environment_payloads(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        environments: dict[DatabaseEnvironment, Any],
    ) -> DatabaseEnvironmentConfigRecord:
        _validate_environment_payloads(environments)
        current = self.get_active_config(workspace_id)
        _ensure_revision(current.revision, expected_revision)
        now = datetime.now(UTC)
        saved = DatabaseEnvironmentConfigRecord(
            workspace_id=workspace_id,
            active_environment=current.active_environment or "uat",
            revision=current.revision + 1,
            created_at=current.created_at or now,
            updated_at=now,
        )
        self._environment_payloads[workspace_id] = copy.deepcopy(environments)
        self._configs[workspace_id] = saved
        return saved

    def resolve_mapping(
        self,
        *,
        workspace_id: str,
        environment: DatabaseEnvironment,
        mcp_alias: str,
    ) -> ResolvedEnvironmentMappingTarget:
        normalized_alias = mcp_alias.strip().casefold()
        target = next(
            (
                item
                for item in self.list_mapping_targets(
                    workspace_id=workspace_id,
                    environment=environment,
                )
                if item.mcp_alias.casefold() == normalized_alias
            ),
            None,
        )
        if target is None:
            raise DatabaseEnvironmentRepositoryError(
                "当前环境没有这个数据库映射",
                code="database_mapping_not_found",
            )
        return target

    def list_mapping_targets(
        self,
        *,
        workspace_id: str,
        environment: DatabaseEnvironment,
    ) -> list[ResolvedEnvironmentMappingTarget]:
        _ensure_environment(environment)
        return [
            ResolvedEnvironmentMappingTarget(
                mapping_id=mapping.id,
                workspace_id=mapping.workspace_id,
                project_id=mapping.project_id,
                logical_name=mapping.logical_name,
                mcp_alias=mapping.mcp_alias,
                environment=environment,
                link_id=mapping.targets[environment],
            )
            for mapping in self.list_mappings(workspace_id)
            if environment in mapping.targets
        ]


class PostgresDatabaseEnvironmentRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.strip()

    def get_active_config(self, workspace_id: str) -> DatabaseEnvironmentConfigRecord:
        return self.get_environment_snapshot(workspace_id).config

    def get_environment_snapshot(
        self,
        workspace_id: str,
    ) -> EnvironmentConfigurationSnapshot:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    SELECT
                        requested.workspace_id,
                        config.active_environment,
                        config.revision,
                        config.created_at,
                        config.updated_at,
                        config.workspace_id IS NOT NULL AS selector_configured,
                        test.payload,
                        test.workspace_id IS NOT NULL AS test_configured,
                        uat.payload,
                        uat.workspace_id IS NOT NULL AS uat_configured
                    FROM (VALUES (%s::varchar)) AS requested(workspace_id)
                    LEFT JOIN workspace_database_environment_configs AS config
                        ON config.workspace_id = requested.workspace_id
                    LEFT JOIN workspace_environment_payloads AS test
                        ON test.workspace_id = requested.workspace_id
                       AND test.environment = 'test'
                    LEFT JOIN workspace_environment_payloads AS uat
                        ON uat.workspace_id = requested.workspace_id
                       AND uat.environment = 'uat'
                    """,
                    (workspace_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise DatabaseEnvironmentRepositoryError("数据库环境配置读取失败") from exc
        if row is None:
            raise DatabaseEnvironmentRepositoryError("数据库环境配置读取失败")
        selector_configured = bool(row[5])
        config = (
            DatabaseEnvironmentConfigRecord(
                workspace_id=str(row[0]),
                active_environment=cast(DatabaseEnvironment | None, row[1]),
                revision=int(row[2]),
                created_at=cast(datetime, row[3]),
                updated_at=cast(datetime, row[4]),
            )
            if selector_configured
            else _unconfigured_config(workspace_id)
        )
        environments = _empty_environment_payloads()
        if bool(row[7]):
            environments["test"] = row[6]
        if bool(row[9]):
            environments["uat"] = row[8]
        return EnvironmentConfigurationSnapshot(
            config=config,
            selector_configured=selector_configured,
            payloads=EnvironmentPayloadsRecord(
                workspace_id=workspace_id,
                configured=bool(row[7]) and bool(row[9]),
                environments=environments,
            ),
        )

    def get_environment_payloads(self, workspace_id: str) -> EnvironmentPayloadsRecord:
        return self.get_environment_snapshot(workspace_id).payloads

    def list_mappings(self, workspace_id: str) -> list[DatabaseEnvironmentMappingRecord]:
        try:
            with psycopg.connect(self._database_url) as connection:
                return self._list_mappings(connection, workspace_id)
        except psycopg.Error as exc:
            raise DatabaseEnvironmentRepositoryError("数据库环境映射读取失败") from exc

    def replace_mappings(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        mappings: list[DatabaseEnvironmentMappingWrite],
    ) -> DatabaseEnvironmentConfigRecord:
        _validate_mapping_writes(workspace_id, mappings)
        try:
            with psycopg.connect(self._database_url) as connection:
                self._lock_workspace(connection, workspace_id)
                current = self._locked_config(connection, workspace_id)
                _ensure_revision(current.revision, expected_revision)
                self._validate_physical_targets(connection, workspace_id, mappings)
                self._ensure_mapping_ids_available(connection, workspace_id, mappings)

                connection.execute(
                    "DELETE FROM project_database_environment_mappings WHERE workspace_id = %s",
                    (workspace_id,),
                )
                for mapping in mappings:
                    connection.execute(
                        """
                        INSERT INTO project_database_environment_mappings (
                            id, workspace_id, project_id, logical_name, mcp_alias
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            mapping.id,
                            workspace_id,
                            mapping.project_id,
                            mapping.logical_name,
                            mapping.mcp_alias,
                        ),
                    )
                    with connection.cursor() as cursor:
                        cursor.executemany(
                            """
                            INSERT INTO project_database_environment_targets (
                                mapping_id, environment, project_database_id
                            )
                            VALUES (%s, %s, %s)
                            """,
                            (
                                (mapping.id, "test", mapping.test_link_id),
                                (mapping.id, "uat", mapping.uat_link_id),
                            ),
                        )

                next_revision = current.revision + 1
                active_environment = current.active_environment or "uat"
                row = connection.execute(
                    """
                    INSERT INTO workspace_database_environment_configs (
                        workspace_id, active_environment, revision
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (workspace_id) DO UPDATE SET
                        active_environment = EXCLUDED.active_environment,
                        revision = EXCLUDED.revision,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING workspace_id, active_environment, revision,
                              created_at, updated_at
                    """,
                    (workspace_id, active_environment, next_revision),
                ).fetchone()
        except DatabaseEnvironmentRepositoryError:
            raise
        except psycopg.errors.UniqueViolation as exc:
            raise DatabaseEnvironmentRepositoryError(
                "工作空间内环境映射 MCP 别名或目标重复"
            ) from exc
        except psycopg.errors.ForeignKeyViolation as exc:
            raise DatabaseEnvironmentRepositoryError("项目或数据库授权不存在") from exc
        except psycopg.Error as exc:
            raise DatabaseEnvironmentRepositoryError("数据库环境映射保存失败") from exc
        if row is None:
            raise DatabaseEnvironmentRepositoryError("数据库环境配置保存后没有返回结果")
        return _config_record(row)

    def switch_environment(
        self,
        *,
        workspace_id: str,
        environment: DatabaseEnvironment,
        expected_revision: int,
    ) -> DatabaseEnvironmentConfigRecord:
        _ensure_environment(environment)
        try:
            with psycopg.connect(self._database_url) as connection:
                self._lock_workspace(connection, workspace_id)
                current = self._locked_config(connection, workspace_id)
                payload_count = int(
                    connection.execute(
                        """
                        SELECT count(*)
                        FROM workspace_environment_payloads
                        WHERE workspace_id = %s
                          AND environment IN ('test', 'uat')
                        """,
                        (workspace_id,),
                    ).fetchone()[0]
                )
                if current.active_environment is None:
                    raise DatabaseEnvironmentRepositoryError("工作空间尚未配置环境")
                _ensure_revision(current.revision, expected_revision)
                mappings = self._list_mappings(connection, workspace_id)
                if mappings:
                    mappings = self._list_mapping_writes(connection, workspace_id)
                    self._validate_physical_targets(connection, workspace_id, mappings)
                elif payload_count != len(_ENVIRONMENTS):
                    raise DatabaseEnvironmentRepositoryError("工作空间环境配置不完整")
                row = connection.execute(
                    """
                    UPDATE workspace_database_environment_configs
                    SET active_environment = %s,
                        revision = revision + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE workspace_id = %s
                    RETURNING workspace_id, active_environment, revision,
                              created_at, updated_at
                    """,
                    (environment, workspace_id),
                ).fetchone()
        except DatabaseEnvironmentRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DatabaseEnvironmentRepositoryError("数据库环境切换失败") from exc
        if row is None:
            raise DatabaseEnvironmentRepositoryError("数据库环境配置不存在")
        return _config_record(row)

    def replace_environment_payloads(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        environments: dict[DatabaseEnvironment, Any],
    ) -> DatabaseEnvironmentConfigRecord:
        _validate_environment_payloads(environments)
        try:
            with psycopg.connect(self._database_url) as connection:
                self._lock_workspace(connection, workspace_id)
                current = self._locked_config(connection, workspace_id)
                _ensure_revision(current.revision, expected_revision)
                next_revision = current.revision + 1
                active_environment = current.active_environment or "uat"
                row = connection.execute(
                    """
                    INSERT INTO workspace_database_environment_configs (
                        workspace_id, active_environment, revision
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (workspace_id) DO UPDATE SET
                        active_environment = EXCLUDED.active_environment,
                        revision = EXCLUDED.revision,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING workspace_id, active_environment, revision,
                              created_at, updated_at
                    """,
                    (workspace_id, active_environment, next_revision),
                ).fetchone()
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO workspace_environment_payloads (
                            workspace_id, environment, payload
                        )
                        VALUES (%s, %s, %s)
                        ON CONFLICT (workspace_id, environment) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            (workspace_id, "test", Jsonb(environments["test"])),
                            (workspace_id, "uat", Jsonb(environments["uat"])),
                        ),
                    )
        except DatabaseEnvironmentRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DatabaseEnvironmentRepositoryError("环境 JSON 配置保存失败") from exc
        if row is None:
            raise DatabaseEnvironmentRepositoryError("工作空间环境配置不存在")
        return _config_record(row)

    def resolve_mapping(
        self,
        *,
        workspace_id: str,
        environment: DatabaseEnvironment,
        mcp_alias: str,
    ) -> ResolvedEnvironmentMappingTarget:
        _ensure_environment(environment)
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    self._resolved_select()
                    + """
                    WHERE mapping.workspace_id = %s
                      AND target.environment = %s
                      AND lower(mapping.mcp_alias) = lower(%s)
                    """,
                    (workspace_id, environment, mcp_alias.strip()),
                ).fetchone()
        except psycopg.Error as exc:
            raise DatabaseEnvironmentRepositoryError("数据库环境映射读取失败") from exc
        if row is None:
            raise DatabaseEnvironmentRepositoryError(
                "当前环境没有这个数据库映射",
                code="database_mapping_not_found",
            )
        return _resolved_record(row)

    def list_mapping_targets(
        self,
        *,
        workspace_id: str,
        environment: DatabaseEnvironment,
    ) -> list[ResolvedEnvironmentMappingTarget]:
        _ensure_environment(environment)
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    self._resolved_select()
                    + """
                    WHERE mapping.workspace_id = %s
                      AND target.environment = %s
                    ORDER BY lower(mapping.mcp_alias), mapping.id
                    """,
                    (workspace_id, environment),
                ).fetchall()
        except psycopg.Error as exc:
            raise DatabaseEnvironmentRepositoryError("数据库环境映射读取失败") from exc
        return [_resolved_record(row) for row in rows]

    @staticmethod
    def _lock_workspace(connection: psycopg.Connection[Any], workspace_id: str) -> None:
        row = connection.execute(
            "SELECT id FROM workspaces WHERE id = %s FOR UPDATE",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise DatabaseEnvironmentRepositoryError("工作空间不存在")

    @staticmethod
    def _locked_config(
        connection: psycopg.Connection[Any],
        workspace_id: str,
    ) -> DatabaseEnvironmentConfigRecord:
        row = connection.execute(
            """
            SELECT workspace_id, active_environment, revision,
                   created_at, updated_at
            FROM workspace_database_environment_configs
            WHERE workspace_id = %s
            FOR UPDATE
            """,
            (workspace_id,),
        ).fetchone()
        return _config_record(row) if row is not None else _unconfigured_config(workspace_id)

    @staticmethod
    def _ensure_mapping_ids_available(
        connection: psycopg.Connection[Any],
        workspace_id: str,
        mappings: list[DatabaseEnvironmentMappingWrite],
    ) -> None:
        mapping_ids = [mapping.id for mapping in mappings]
        if not mapping_ids:
            return
        conflict = connection.execute(
            """
            SELECT id
            FROM project_database_environment_mappings
            WHERE id = ANY(%s) AND workspace_id <> %s
            LIMIT 1
            """,
            (mapping_ids, workspace_id),
        ).fetchone()
        if conflict is not None:
            raise DatabaseEnvironmentRepositoryError("环境映射 ID 已被其他工作空间使用")

    @staticmethod
    def _validate_physical_targets(
        connection: psycopg.Connection[Any],
        workspace_id: str,
        mappings: list[DatabaseEnvironmentMappingWrite],
    ) -> None:
        link_ids = [
            link_id
            for mapping in mappings
            for link_id in (mapping.test_link_id, mapping.uat_link_id)
        ]
        if not link_ids:
            return
        rows = connection.execute(
            """
            SELECT
                link.id,
                link.workspace_id,
                link.project_id,
                project.project_kind,
                link.readonly,
                database.remote_name,
                database.namespace_type,
                database.available,
                database.system_database,
                source.engine
            FROM project_databases AS link
            JOIN document_projects AS project ON project.id = link.project_id
            JOIN data_source_databases AS database ON database.id = link.database_id
            JOIN data_sources AS source ON source.id = database.data_source_id
            WHERE link.id = ANY(%s)
            FOR UPDATE OF link, project, database, source
            """,
            (link_ids,),
        ).fetchall()
        by_id = {str(row[0]): row for row in rows}
        if len(by_id) != len(set(link_ids)):
            raise DatabaseEnvironmentRepositoryError("环境映射包含不存在的数据库授权")

        used_by_environment: dict[DatabaseEnvironment, set[str]] = {
            "test": set(),
            "uat": set(),
        }
        for mapping in mappings:
            engines: set[str] = set()
            namespace_types: set[str] = set()
            for environment, link_id in (
                ("test", mapping.test_link_id),
                ("uat", mapping.uat_link_id),
            ):
                if link_id in used_by_environment[environment]:
                    raise DatabaseEnvironmentRepositoryError("同一环境不能重复使用数据库授权")
                used_by_environment[environment].add(link_id)
                row = by_id[link_id]
                if str(row[1]) != workspace_id or str(row[2]) != mapping.project_id:
                    raise DatabaseEnvironmentRepositoryError("数据库授权不属于当前工作空间项目")
                if str(row[3]) != "backend":
                    raise DatabaseEnvironmentRepositoryError("仅后端项目可以配置数据库环境映射")
                if not bool(row[4]):
                    raise DatabaseEnvironmentRepositoryError("环境目标必须保持只读")
                if not bool(row[7]) or bool(row[8]):
                    raise DatabaseEnvironmentRepositoryError("环境目标数据库当前不可用")
                namespace_types.add(str(row[6]))
                engines.add(str(row[9]))
            if len(engines) != 1:
                raise DatabaseEnvironmentRepositoryError("同一环境映射的数据库类型必须一致")
            if len(namespace_types) != 1:
                raise DatabaseEnvironmentRepositoryError("同一环境映射的命名空间类型必须一致")

    @classmethod
    def _list_mappings(
        cls,
        connection: psycopg.Connection[Any],
        workspace_id: str,
    ) -> list[DatabaseEnvironmentMappingRecord]:
        rows = connection.execute(
            """
            SELECT
                mapping.id,
                mapping.workspace_id,
                mapping.project_id,
                mapping.logical_name,
                mapping.mcp_alias,
                mapping.created_at,
                mapping.updated_at,
                target.environment,
                target.project_database_id
            FROM project_database_environment_mappings AS mapping
            LEFT JOIN project_database_environment_targets AS target
                ON target.mapping_id = mapping.id
            WHERE mapping.workspace_id = %s
            ORDER BY mapping.project_id, lower(mapping.mcp_alias), mapping.id,
                     target.environment
            """,
            (workspace_id,),
        ).fetchall()
        by_id: dict[str, DatabaseEnvironmentMappingRecord] = {}
        for row in rows:
            mapping_id = str(row[0])
            record = by_id.get(mapping_id)
            if record is None:
                record = DatabaseEnvironmentMappingRecord(
                    id=mapping_id,
                    workspace_id=str(row[1]),
                    project_id=str(row[2]),
                    logical_name=str(row[3]),
                    mcp_alias=str(row[4]),
                    targets={},
                    created_at=cast(datetime, row[5]),
                    updated_at=cast(datetime, row[6]),
                )
                by_id[mapping_id] = record
            if row[7] is not None and row[8] is not None:
                record.targets[cast(DatabaseEnvironment, str(row[7]))] = str(row[8])
        return list(by_id.values())

    @classmethod
    def _list_mapping_writes(
        cls,
        connection: psycopg.Connection[Any],
        workspace_id: str,
    ) -> list[DatabaseEnvironmentMappingWrite]:
        records = cls._list_mappings(connection, workspace_id)
        if not records:
            raise DatabaseEnvironmentRepositoryError("至少需要一条数据库环境映射才能切换")
        writes: list[DatabaseEnvironmentMappingWrite] = []
        for record in records:
            if "test" not in record.targets or "uat" not in record.targets:
                raise DatabaseEnvironmentRepositoryError("数据库环境映射不完整，无法切换")
            writes.append(
                DatabaseEnvironmentMappingWrite(
                    id=record.id,
                    workspace_id=record.workspace_id,
                    project_id=record.project_id,
                    logical_name=record.logical_name,
                    mcp_alias=record.mcp_alias,
                    test_link_id=record.targets["test"],
                    uat_link_id=record.targets["uat"],
                )
            )
        return writes

    @staticmethod
    def _resolved_select() -> str:
        return """
        SELECT
            mapping.id,
            mapping.workspace_id,
            mapping.project_id,
            mapping.logical_name,
            mapping.mcp_alias,
            target.environment,
            target.project_database_id
        FROM project_database_environment_mappings AS mapping
        JOIN project_database_environment_targets AS target
            ON target.mapping_id = mapping.id
        JOIN workspace_database_environment_configs AS config
            ON config.workspace_id = mapping.workspace_id
        """


def _ensure_environment(environment: str) -> None:
    if environment not in _ENVIRONMENTS:
        raise DatabaseEnvironmentRepositoryError("数据库环境必须是 test 或 uat")


def _ensure_revision(current: int, expected: int) -> None:
    if current != expected:
        raise DatabaseEnvironmentRepositoryError(
            "数据库环境配置已被其他操作更新，请刷新后重试",
            code="database_environment_revision_conflict",
        )


def _empty_environment_payloads() -> dict[DatabaseEnvironment, Any]:
    return {"test": {}, "uat": {}}


def _validate_environment_payloads(
    environments: dict[DatabaseEnvironment, Any],
) -> None:
    if set(environments) != set(_ENVIRONMENTS):
        raise DatabaseEnvironmentRepositoryError("环境 JSON 必须同时包含 test 和 uat")
    total_bytes = 0
    try:
        for payload in environments.values():
            if not isinstance(payload, dict):
                raise DatabaseEnvironmentRepositoryError("每个环境配置的顶层必须是 JSON 对象")
            _validate_environment_json_tree(payload)
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            total_bytes += len(serialized.encode("utf-8"))
            if total_bytes > _MAX_ENVIRONMENT_JSON_BYTES:
                raise DatabaseEnvironmentRepositoryError(
                    "TEST 与 UAT 环境 JSON 合计不能超过 256 KiB"
                )
    except DatabaseEnvironmentRepositoryError:
        raise
    except (RecursionError, TypeError, ValueError) as exc:
        raise DatabaseEnvironmentRepositoryError("环境配置必须是有效 JSON") from exc


def _validate_environment_json_tree(payload: dict[str, Any]) -> None:
    node_count = 0
    stack: list[tuple[Any, int]] = [(payload, 1)]
    while stack:
        value, depth = stack.pop()
        node_count += 1
        if node_count > _MAX_ENVIRONMENT_JSON_NODES:
            raise DatabaseEnvironmentRepositoryError("环境 JSON 节点数量不能超过 10000")
        if depth > _MAX_ENVIRONMENT_JSON_DEPTH:
            raise DatabaseEnvironmentRepositoryError("环境 JSON 嵌套不能超过 20 层")
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise DatabaseEnvironmentRepositoryError("环境 JSON 对象键必须是字符串")
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
        elif isinstance(value, bool) or value is None or isinstance(value, str):
            continue
        elif isinstance(value, int):
            if abs(value) > _MAX_SAFE_JSON_INTEGER:
                raise DatabaseEnvironmentRepositoryError(
                    "环境 JSON 整数超出前端安全范围，请改用字符串"
                )
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise DatabaseEnvironmentRepositoryError("环境 JSON 数字必须是有限值")
        else:
            raise DatabaseEnvironmentRepositoryError("环境配置必须是有效 JSON")


def _validate_mapping_writes(
    workspace_id: str,
    mappings: list[DatabaseEnvironmentMappingWrite],
) -> None:
    if not mappings:
        raise DatabaseEnvironmentRepositoryError("至少需要一条数据库环境映射")
    ids: set[str] = set()
    aliases: set[str] = set()
    for mapping in mappings:
        if mapping.workspace_id != workspace_id:
            raise DatabaseEnvironmentRepositoryError("环境映射不属于当前工作空间")
        if mapping.id in ids:
            raise DatabaseEnvironmentRepositoryError("环境映射 ID 不能重复")
        ids.add(mapping.id)
        alias = mapping.mcp_alias.strip()
        if not _MCP_ALIAS_PATTERN.fullmatch(alias):
            raise DatabaseEnvironmentRepositoryError("环境映射 MCP 别名格式不正确")
        if alias.casefold() in aliases:
            raise DatabaseEnvironmentRepositoryError("工作空间内环境映射 MCP 别名不能重复")
        aliases.add(alias.casefold())
        if not mapping.logical_name.strip():
            raise DatabaseEnvironmentRepositoryError("环境映射逻辑名称不能为空")
        if mapping.test_link_id == mapping.uat_link_id:
            raise DatabaseEnvironmentRepositoryError("Test 与 UAT 必须映射到不同数据库授权")


def _unconfigured_config(workspace_id: str) -> DatabaseEnvironmentConfigRecord:
    return DatabaseEnvironmentConfigRecord(
        workspace_id=workspace_id,
        active_environment=None,
        revision=0,
    )


def _config_record(row: tuple[object, ...]) -> DatabaseEnvironmentConfigRecord:
    return DatabaseEnvironmentConfigRecord(
        workspace_id=str(row[0]),
        active_environment=cast(DatabaseEnvironment, str(row[1])),
        revision=int(row[2]),
        created_at=cast(datetime, row[3]),
        updated_at=cast(datetime, row[4]),
    )


def _resolved_record(row: tuple[object, ...]) -> ResolvedEnvironmentMappingTarget:
    return ResolvedEnvironmentMappingTarget(
        mapping_id=str(row[0]),
        workspace_id=str(row[1]),
        project_id=str(row[2]),
        logical_name=str(row[3]),
        mcp_alias=str(row[4]),
        environment=cast(DatabaseEnvironment, str(row[5])),
        link_id=str(row[6]),
    )
