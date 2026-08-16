from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class TableRelationRepositoryError(RuntimeError):
    pass


class TableRelationConfigRevisionError(TableRelationRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class TableRelationDefaultDatabaseConfigRecord:
    workspace_id: str
    revision: int
    targets: tuple[tuple[str, str], ...]
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TableJoinEvidenceRecord:
    source_path: str
    join_expression: str
    sql_statement: str
    preprocess_profile_id: str | None = None
    preprocess_profile_hash: str | None = None
    preprocess_candidate_id: str | None = None
    applied_rules: tuple[str, ...] = ()
    template_derived: bool = False


@dataclass(frozen=True, slots=True)
class TableJoinRelationRecord:
    relation_id: str
    workspace_id: str
    project_id: str
    project_name: str
    database_key: str
    table_a_schema: str
    table_a_name: str
    table_b_schema: str
    table_b_name: str
    column_pairs: tuple[tuple[str, str], ...]
    evidences: tuple[TableJoinEvidenceRecord, ...]


@dataclass(frozen=True, slots=True)
class TableRelationWarningRecord:
    project_id: str
    project_name: str
    database_key: str
    source_path: str
    code: str
    message: str
    expression: str | None = None
    occurrence_count: int = 1


@dataclass(frozen=True, slots=True)
class TableRelationAutomaticFileRecord:
    project_id: str
    project_name: str
    database_key: str
    source_path: str
    rule_code: str
    statement_bytes: int


@dataclass(frozen=True, slots=True)
class TableRelationBuildRecord:
    workspace_id: str
    project_id: str
    project_name: str
    database_key: str
    generation_id: str | None
    status: str
    sql_file_count: int
    statement_count: int
    relation_count: int
    warnings: tuple[str, ...]
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    warning_count: int = 0
    config_revision: int = 0
    automatic_file_count: int | None = None


class TableRelationStore(Protocol):
    def get_default_database_config(
        self, workspace_id: str
    ) -> TableRelationDefaultDatabaseConfigRecord: ...

    def replace_default_databases(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        targets: list[tuple[str, str]],
    ) -> TableRelationDefaultDatabaseConfigRecord: ...

    def mark_building(
        self,
        *,
        workspace_id: str,
        project_id: str,
        project_name: str,
        database_key: str,
        generation_id: str,
        config_revision: int = 0,
    ) -> None: ...

    def publish(
        self,
        *,
        build: TableRelationBuildRecord,
        relations: list[TableJoinRelationRecord],
        warning_records: list[TableRelationWarningRecord] | None = None,
        automatic_files: list[TableRelationAutomaticFileRecord] | None = None,
    ) -> None: ...

    def mark_failed(
        self,
        *,
        workspace_id: str,
        project_id: str,
        project_name: str,
        database_key: str,
        generation_id: str,
        error_message: str,
        warnings: list[str],
        warning_records: list[TableRelationWarningRecord] | None = None,
        automatic_files: list[TableRelationAutomaticFileRecord] | None = None,
    ) -> None: ...

    def list_builds(self, workspace_id: str) -> list[TableRelationBuildRecord]: ...

    def list_relations(self, workspace_id: str) -> list[TableJoinRelationRecord]: ...

    def list_warnings(self, workspace_id: str) -> list[TableRelationWarningRecord]: ...

    def list_automatic_files(
        self,
        workspace_id: str,
        *,
        rule_code: str,
        project_id: str | None = None,
    ) -> list[TableRelationAutomaticFileRecord]: ...

    def get_sql_whitelist(self, workspace_id: str, project_id: str) -> tuple[str, ...]: ...

    def replace_sql_whitelist(
        self,
        *,
        workspace_id: str,
        project_id: str,
        source_paths: list[str],
    ) -> tuple[str, ...]: ...


class InMemoryTableRelationRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._builds: dict[tuple[str, str, str], TableRelationBuildRecord] = {}
        self._relations: dict[tuple[str, str, str], list[TableJoinRelationRecord]] = {}
        self._warnings: dict[tuple[str, str, str], list[TableRelationWarningRecord]] = {}
        self._automatic_files: dict[
            tuple[str, str, str], list[TableRelationAutomaticFileRecord]
        ] = {}
        self._default_configs: dict[str, TableRelationDefaultDatabaseConfigRecord] = {}
        self._sql_whitelists: dict[tuple[str, str], tuple[str, ...]] = {}

    def get_default_database_config(
        self, workspace_id: str
    ) -> TableRelationDefaultDatabaseConfigRecord:
        return self._default_configs.get(
            workspace_id,
            TableRelationDefaultDatabaseConfigRecord(
                workspace_id=workspace_id,
                revision=0,
                targets=(),
            ),
        )

    def replace_default_databases(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        targets: list[tuple[str, str]],
    ) -> TableRelationDefaultDatabaseConfigRecord:
        current = self.get_default_database_config(workspace_id)
        if current.revision != expected_revision:
            raise TableRelationConfigRevisionError("表关联默认数据库配置已被其他操作更新")
        normalized = tuple(sorted(set(targets)))
        if len(normalized) != len(targets):
            raise TableRelationRepositoryError("默认数据库项目或关联不能重复")
        record = TableRelationDefaultDatabaseConfigRecord(
            workspace_id=workspace_id,
            revision=current.revision + 1,
            targets=normalized,
            updated_at=datetime.now(UTC),
        )
        self._default_configs[workspace_id] = record
        return record

    @staticmethod
    def _key(workspace_id: str, project_id: str, database_key: str) -> tuple[str, str, str]:
        return workspace_id, project_id, database_key.casefold()

    def mark_building(
        self,
        *,
        workspace_id: str,
        project_id: str,
        project_name: str,
        database_key: str,
        generation_id: str,
        config_revision: int = 0,
    ) -> None:
        effective_revision = (
            config_revision or self.get_default_database_config(workspace_id).revision
        )
        with self._lock:
            self._builds[self._key(workspace_id, project_id, database_key)] = (
                TableRelationBuildRecord(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    project_name=project_name,
                    database_key=database_key,
                    generation_id=generation_id,
                    status="building",
                    sql_file_count=0,
                    statement_count=0,
                    relation_count=0,
                    warnings=(),
                    error_message=None,
                    started_at=datetime.now(UTC),
                    finished_at=None,
                    warning_count=0,
                    config_revision=effective_revision,
                )
            )

    def publish(
        self,
        *,
        build: TableRelationBuildRecord,
        relations: list[TableJoinRelationRecord],
        warning_records: list[TableRelationWarningRecord] | None = None,
        automatic_files: list[TableRelationAutomaticFileRecord] | None = None,
    ) -> None:
        key = self._key(build.workspace_id, build.project_id, build.database_key)
        with self._lock:
            current = self._builds.get(key)
            if current is None or current.generation_id != build.generation_id:
                raise TableRelationRepositoryError("表关联构建批次已经变化")
            self._relations[key] = list(relations)
            self._warnings[key] = list(warning_records or [])
            if automatic_files is not None:
                self._automatic_files[key] = list(automatic_files)
            self._builds[key] = replace(
                build,
                status="ready",
                finished_at=datetime.now(UTC),
                config_revision=current.config_revision,
                automatic_file_count=(
                    len(automatic_files)
                    if automatic_files is not None
                    else build.automatic_file_count
                ),
            )

    def mark_failed(
        self,
        *,
        workspace_id: str,
        project_id: str,
        project_name: str,
        database_key: str,
        generation_id: str,
        error_message: str,
        warnings: list[str],
        warning_records: list[TableRelationWarningRecord] | None = None,
        automatic_files: list[TableRelationAutomaticFileRecord] | None = None,
    ) -> None:
        key = self._key(workspace_id, project_id, database_key)
        with self._lock:
            current = self._builds.get(key)
            started_at = current.started_at if current else datetime.now(UTC)
            self._builds[key] = TableRelationBuildRecord(
                workspace_id=workspace_id,
                project_id=project_id,
                project_name=project_name,
                database_key=database_key,
                generation_id=generation_id,
                status="failed",
                sql_file_count=0,
                statement_count=0,
                relation_count=0,
                warnings=tuple(warnings),
                error_message=error_message,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                warning_count=sum(item.occurrence_count for item in warning_records or []),
                config_revision=current.config_revision if current else 0,
                automatic_file_count=(
                    len(automatic_files) if automatic_files is not None else None
                ),
            )
            self._warnings[key] = list(warning_records or [])
            if automatic_files is not None:
                self._automatic_files[key] = list(automatic_files)

    def list_builds(self, workspace_id: str) -> list[TableRelationBuildRecord]:
        with self._lock:
            return sorted(
                [item for item in self._builds.values() if item.workspace_id == workspace_id],
                key=lambda item: (item.project_name.casefold(), item.database_key.casefold()),
            )

    def list_relations(self, workspace_id: str) -> list[TableJoinRelationRecord]:
        with self._lock:
            records: list[TableJoinRelationRecord] = []
            for key, build in self._builds.items():
                if build.workspace_id == workspace_id and build.status == "ready":
                    records.extend(self._relations.get(key, []))
            return sorted(records, key=lambda item: item.relation_id)

    def list_warnings(self, workspace_id: str) -> list[TableRelationWarningRecord]:
        with self._lock:
            records: list[TableRelationWarningRecord] = []
            for key, build in self._builds.items():
                if build.workspace_id == workspace_id and build.status in {"ready", "failed"}:
                    records.extend(self._warnings.get(key, []))
            return sorted(
                records,
                key=lambda item: (
                    item.code,
                    item.project_name.casefold(),
                    item.database_key.casefold(),
                    item.source_path.casefold(),
                    item.message,
                ),
            )

    def list_automatic_files(
        self,
        workspace_id: str,
        *,
        rule_code: str,
        project_id: str | None = None,
    ) -> list[TableRelationAutomaticFileRecord]:
        with self._lock:
            records: list[TableRelationAutomaticFileRecord] = []
            for key, build in self._builds.items():
                if build.workspace_id != workspace_id or build.status not in {"ready", "failed"}:
                    continue
                if project_id is not None and build.project_id != project_id:
                    continue
                records.extend(
                    item
                    for item in self._automatic_files.get(key, [])
                    if item.rule_code == rule_code
                )
            return sorted(
                records,
                key=lambda item: (
                    item.project_name.casefold(),
                    item.source_path.casefold(),
                    item.project_id,
                ),
            )

    def get_sql_whitelist(self, workspace_id: str, project_id: str) -> tuple[str, ...]:
        with self._lock:
            return self._sql_whitelists.get((workspace_id, project_id), ())

    def replace_sql_whitelist(
        self,
        *,
        workspace_id: str,
        project_id: str,
        source_paths: list[str],
    ) -> tuple[str, ...]:
        normalized = tuple(sorted(set(source_paths), key=str.casefold))
        with self._lock:
            self._sql_whitelists[(workspace_id, project_id)] = normalized
        return normalized


class PostgresTableRelationRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def get_default_database_config(
        self, workspace_id: str
    ) -> TableRelationDefaultDatabaseConfigRecord:
        try:
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                config = connection.execute(
                    """SELECT revision, updated_at
                       FROM workspace_table_relation_configs
                       WHERE workspace_id=%s""",
                    (workspace_id,),
                ).fetchone()
                targets = connection.execute(
                    """SELECT project_id, project_database_id
                       FROM workspace_table_relation_default_databases
                       WHERE workspace_id=%s
                       ORDER BY project_id""",
                    (workspace_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联默认数据库配置读取失败") from exc
        return TableRelationDefaultDatabaseConfigRecord(
            workspace_id=workspace_id,
            revision=int(config["revision"]) if config else 0,
            targets=tuple(
                (str(row["project_id"]), str(row["project_database_id"])) for row in targets
            ),
            updated_at=(
                config["updated_at"]
                if config and isinstance(config["updated_at"], datetime)
                else None
            ),
        )

    def replace_default_databases(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        targets: list[tuple[str, str]],
    ) -> TableRelationDefaultDatabaseConfigRecord:
        normalized = tuple(sorted(set(targets)))
        if len(normalized) != len(targets):
            raise TableRelationRepositoryError("默认数据库项目或关联不能重复")
        try:
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                current = connection.execute(
                    """SELECT revision FROM workspace_table_relation_configs
                       WHERE workspace_id=%s FOR UPDATE""",
                    (workspace_id,),
                ).fetchone()
                current_revision = int(current["revision"]) if current else 0
                if current_revision != expected_revision:
                    raise TableRelationConfigRevisionError("表关联默认数据库配置已被其他操作更新")
                next_revision = current_revision + 1
                connection.execute(
                    """INSERT INTO workspace_table_relation_configs (
                           workspace_id, revision, updated_at
                       ) VALUES (%s, %s, NOW())
                       ON CONFLICT (workspace_id)
                       DO UPDATE SET revision=EXCLUDED.revision, updated_at=NOW()""",
                    (workspace_id, next_revision),
                )
                connection.execute(
                    """DELETE FROM workspace_table_relation_default_databases
                       WHERE workspace_id=%s""",
                    (workspace_id,),
                )
                for project_id, project_database_id in normalized:
                    connection.execute(
                        """INSERT INTO workspace_table_relation_default_databases (
                               workspace_id, project_id, project_database_id, updated_at
                           ) VALUES (%s, %s, %s, NOW())""",
                        (workspace_id, project_id, project_database_id),
                    )
        except TableRelationConfigRevisionError:
            raise
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联默认数据库配置保存失败") from exc
        return self.get_default_database_config(workspace_id)

    def mark_building(
        self,
        *,
        workspace_id: str,
        project_id: str,
        project_name: str,
        database_key: str,
        generation_id: str,
        config_revision: int = 0,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """INSERT INTO table_relation_builds (
                           workspace_id, project_id, project_name, database_key,
                           generation_id, status, config_revision, started_at, finished_at,
                           sql_file_count, statement_count, relation_count, warning_count,
                           warnings, error_message
                       ) VALUES (%s, %s, %s, %s, %s, 'building', %s, NOW(), NULL, 0, 0, 0, 0,
                                 '[]'::jsonb, NULL)
                       ON CONFLICT (workspace_id, project_id, database_key)
                       DO UPDATE SET project_name=EXCLUDED.project_name,
                                     generation_id=EXCLUDED.generation_id,
                                     config_revision=EXCLUDED.config_revision,
                                     status='building', started_at=NOW(), finished_at=NULL,
                                     sql_file_count=0, statement_count=0, relation_count=0,
                                     warning_count=0, warnings='[]'::jsonb,
                                     error_message=NULL, automatic_file_count=NULL""",
                    (
                        workspace_id,
                        project_id,
                        project_name,
                        database_key,
                        generation_id,
                        config_revision,
                    ),
                )
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联构建状态写入失败") from exc

    def publish(
        self,
        *,
        build: TableRelationBuildRecord,
        relations: list[TableJoinRelationRecord],
        warning_records: list[TableRelationWarningRecord] | None = None,
        automatic_files: list[TableRelationAutomaticFileRecord] | None = None,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                status = connection.execute(
                    """SELECT generation_id, status, config_revision FROM table_relation_builds
                       WHERE workspace_id=%s AND project_id=%s AND database_key=%s
                       FOR UPDATE""",
                    (build.workspace_id, build.project_id, build.database_key),
                ).fetchone()
                if status != (build.generation_id, "building", build.config_revision):
                    raise TableRelationRepositoryError("表关联构建批次已经变化")
                connection.execute(
                    """DELETE FROM table_join_relations
                       WHERE workspace_id=%s AND project_id=%s AND database_key=%s""",
                    (build.workspace_id, build.project_id, build.database_key),
                )
                connection.execute(
                    """DELETE FROM table_relation_warnings
                       WHERE workspace_id=%s AND project_id=%s AND database_key=%s""",
                    (build.workspace_id, build.project_id, build.database_key),
                )
                if automatic_files is not None:
                    connection.execute(
                        """DELETE FROM table_relation_automatic_files
                           WHERE workspace_id=%s AND project_id=%s AND database_key=%s""",
                        (build.workspace_id, build.project_id, build.database_key),
                    )
                for relation in relations:
                    connection.execute(
                        """INSERT INTO table_join_relations (
                               id, workspace_id, project_id, project_name, database_key,
                               table_a_schema, table_a_name, table_b_schema, table_b_name,
                               relation_kind, directed, generation_id
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'observed_join',FALSE,%s)""",
                        (
                            relation.relation_id,
                            relation.workspace_id,
                            relation.project_id,
                            relation.project_name,
                            relation.database_key,
                            relation.table_a_schema,
                            relation.table_a_name,
                            relation.table_b_schema,
                            relation.table_b_name,
                            build.generation_id,
                        ),
                    )
                    for position, (column_a, column_b) in enumerate(relation.column_pairs, start=1):
                        connection.execute(
                            """INSERT INTO table_join_column_pairs (
                                   relation_id, position, column_a_name, column_b_name
                               ) VALUES (%s,%s,%s,%s)""",
                            (relation.relation_id, position, column_a, column_b),
                        )
                    for evidence in relation.evidences:
                        connection.execute(
                            """INSERT INTO table_join_evidences (
                                   relation_id, source_kind, source_path,
                                   join_expression, sql_statement, preprocess_profile_id,
                                   preprocess_profile_hash, preprocess_candidate_id,
                                   applied_rules, template_derived
                               ) VALUES (%s,'sql_file',%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (
                                relation.relation_id,
                                evidence.source_path,
                                evidence.join_expression,
                                evidence.sql_statement,
                                evidence.preprocess_profile_id,
                                evidence.preprocess_profile_hash,
                                evidence.preprocess_candidate_id,
                                Jsonb(list(evidence.applied_rules)),
                                evidence.template_derived,
                            ),
                        )
                for warning in warning_records or []:
                    connection.execute(
                        """INSERT INTO table_relation_warnings (
                               workspace_id, project_id, project_name, database_key,
                               generation_id, source_path, code, message, expression,
                               occurrence_count
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            build.workspace_id,
                            warning.project_id,
                            warning.project_name,
                            warning.database_key,
                            build.generation_id,
                            warning.source_path,
                            warning.code,
                            warning.message,
                            warning.expression,
                            warning.occurrence_count,
                        ),
                    )
                for item in automatic_files or []:
                    connection.execute(
                        """INSERT INTO table_relation_automatic_files (
                               workspace_id, project_id, project_name, database_key,
                               generation_id, source_path, rule_code, statement_bytes
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            build.workspace_id,
                            item.project_id,
                            item.project_name,
                            item.database_key,
                            build.generation_id,
                            item.source_path,
                            item.rule_code,
                            item.statement_bytes,
                        ),
                    )
                updated = connection.execute(
                    """UPDATE table_relation_builds
                       SET status='ready', sql_file_count=%s, statement_count=%s,
                           relation_count=%s, warning_count=%s, warnings=%s, error_message=NULL,
                           finished_at=NOW(), automatic_file_count=%s
                       WHERE workspace_id=%s AND project_id=%s AND database_key=%s
                         AND generation_id=%s AND status='building'""",
                    (
                        build.sql_file_count,
                        build.statement_count,
                        len(relations),
                        build.warning_count,
                        Jsonb(list(build.warnings)),
                        None if automatic_files is None else len(automatic_files),
                        build.workspace_id,
                        build.project_id,
                        build.database_key,
                        build.generation_id,
                    ),
                ).rowcount
                if updated != 1:
                    raise TableRelationRepositoryError("表关联构建发布失败")
        except TableRelationRepositoryError:
            raise
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联构建发布失败") from exc

    def mark_failed(
        self,
        *,
        workspace_id: str,
        project_id: str,
        project_name: str,
        database_key: str,
        generation_id: str,
        error_message: str,
        warnings: list[str],
        warning_records: list[TableRelationWarningRecord] | None = None,
        automatic_files: list[TableRelationAutomaticFileRecord] | None = None,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """DELETE FROM table_relation_warnings
                       WHERE workspace_id=%s AND project_id=%s AND database_key=%s""",
                    (workspace_id, project_id, database_key),
                )
                if automatic_files is not None:
                    connection.execute(
                        """DELETE FROM table_relation_automatic_files
                           WHERE workspace_id=%s AND project_id=%s AND database_key=%s""",
                        (workspace_id, project_id, database_key),
                    )
                connection.execute(
                    """INSERT INTO table_relation_builds (
                           workspace_id, project_id, project_name, database_key,
                           generation_id, status, started_at, finished_at,
                           sql_file_count, statement_count, relation_count, warning_count,
                           warnings, error_message, automatic_file_count
                       ) VALUES (%s,%s,%s,%s,%s,'failed',NOW(),NOW(),0,0,0,%s,%s,%s,%s)
                       ON CONFLICT (workspace_id, project_id, database_key)
                       DO UPDATE SET project_name=EXCLUDED.project_name,
                                     generation_id=EXCLUDED.generation_id,
                                     status='failed', finished_at=NOW(),
                                     sql_file_count=0, statement_count=0, relation_count=0,
                                     warning_count=EXCLUDED.warning_count,
                                     warnings=EXCLUDED.warnings,
                                     error_message=EXCLUDED.error_message,
                                     automatic_file_count=EXCLUDED.automatic_file_count""",
                    (
                        workspace_id,
                        project_id,
                        project_name,
                        database_key,
                        generation_id,
                        sum(item.occurrence_count for item in warning_records or []),
                        Jsonb(warnings),
                        error_message[:2000],
                        None if automatic_files is None else len(automatic_files),
                    ),
                )
                for warning in warning_records or []:
                    connection.execute(
                        """INSERT INTO table_relation_warnings (
                               workspace_id, project_id, project_name, database_key,
                               generation_id, source_path, code, message, expression,
                               occurrence_count
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            workspace_id,
                            warning.project_id,
                            warning.project_name,
                            warning.database_key,
                            generation_id,
                            warning.source_path,
                            warning.code,
                            warning.message,
                            warning.expression,
                            warning.occurrence_count,
                        ),
                    )
                for item in automatic_files or []:
                    connection.execute(
                        """INSERT INTO table_relation_automatic_files (
                               workspace_id, project_id, project_name, database_key,
                               generation_id, source_path, rule_code, statement_bytes
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            workspace_id,
                            item.project_id,
                            item.project_name,
                            item.database_key,
                            generation_id,
                            item.source_path,
                            item.rule_code,
                            item.statement_bytes,
                        ),
                    )
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联失败状态写入失败") from exc

    def list_builds(self, workspace_id: str) -> list[TableRelationBuildRecord]:
        try:
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                rows = connection.execute(
                    """SELECT workspace_id, project_id, project_name, database_key,
                              generation_id, status, config_revision,
                              sql_file_count, statement_count,
                              relation_count, warning_count, warnings, error_message,
                              started_at, finished_at, automatic_file_count
                       FROM table_relation_builds WHERE workspace_id=%s
                       ORDER BY project_name, database_key""",
                    (workspace_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联构建状态读取失败") from exc
        return [self._build(row) for row in rows]

    def list_relations(self, workspace_id: str) -> list[TableJoinRelationRecord]:
        try:
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                relation_rows = connection.execute(
                    """SELECT relation.id, relation.workspace_id, relation.project_id,
                              relation.project_name, relation.database_key,
                              relation.table_a_schema, relation.table_a_name,
                              relation.table_b_schema, relation.table_b_name
                       FROM table_join_relations relation
                       JOIN table_relation_builds build
                         ON build.workspace_id=relation.workspace_id
                        AND build.project_id=relation.project_id
                        AND build.database_key=relation.database_key
                        AND build.generation_id=relation.generation_id
                        AND build.status='ready'
                       WHERE relation.workspace_id=%s ORDER BY relation.id""",
                    (workspace_id,),
                ).fetchall()
                if not relation_rows:
                    return []
                ids = [str(row["id"]) for row in relation_rows]
                pair_rows = connection.execute(
                    """SELECT relation_id, column_a_name, column_b_name
                       FROM table_join_column_pairs WHERE relation_id=ANY(%s)
                       ORDER BY relation_id, position""",
                    (ids,),
                ).fetchall()
                evidence_rows = connection.execute(
                    """SELECT relation_id, source_path, join_expression, sql_statement,
                              preprocess_profile_id, preprocess_profile_hash,
                              preprocess_candidate_id, applied_rules, template_derived
                       FROM table_join_evidences WHERE relation_id=ANY(%s)
                       ORDER BY relation_id, source_path, id""",
                    (ids,),
                ).fetchall()
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联关系读取失败") from exc
        pairs: dict[str, list[tuple[str, str]]] = {}
        for row in pair_rows:
            pairs.setdefault(str(row["relation_id"]), []).append(
                (str(row["column_a_name"]), str(row["column_b_name"]))
            )
        evidences: dict[str, list[TableJoinEvidenceRecord]] = {}
        for row in evidence_rows:
            evidences.setdefault(str(row["relation_id"]), []).append(
                TableJoinEvidenceRecord(
                    source_path=str(row["source_path"]),
                    join_expression=str(row["join_expression"]),
                    sql_statement=str(row["sql_statement"]),
                    preprocess_profile_id=(
                        str(row["preprocess_profile_id"]) if row["preprocess_profile_id"] else None
                    ),
                    preprocess_profile_hash=(
                        str(row["preprocess_profile_hash"])
                        if row["preprocess_profile_hash"]
                        else None
                    ),
                    preprocess_candidate_id=(
                        str(row["preprocess_candidate_id"])
                        if row["preprocess_candidate_id"]
                        else None
                    ),
                    applied_rules=tuple(
                        str(item)
                        for item in (
                            row["applied_rules"] if isinstance(row["applied_rules"], list) else []
                        )
                    ),
                    template_derived=bool(row["template_derived"]),
                )
            )
        return [
            TableJoinRelationRecord(
                relation_id=str(row["id"]),
                workspace_id=str(row["workspace_id"]),
                project_id=str(row["project_id"]),
                project_name=str(row["project_name"]),
                database_key=str(row["database_key"]),
                table_a_schema=str(row["table_a_schema"]),
                table_a_name=str(row["table_a_name"]),
                table_b_schema=str(row["table_b_schema"]),
                table_b_name=str(row["table_b_name"]),
                column_pairs=tuple(pairs.get(str(row["id"]), [])),
                evidences=tuple(evidences.get(str(row["id"]), [])),
            )
            for row in relation_rows
        ]

    def list_warnings(self, workspace_id: str) -> list[TableRelationWarningRecord]:
        try:
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                rows = connection.execute(
                    """SELECT warning.project_id, warning.project_name,
                              warning.database_key, warning.source_path, warning.code,
                              warning.message, warning.expression, warning.occurrence_count
                       FROM table_relation_warnings warning
                       JOIN table_relation_builds build
                         ON build.workspace_id=warning.workspace_id
                        AND build.project_id=warning.project_id
                        AND build.database_key=warning.database_key
                        AND build.generation_id=warning.generation_id
                        AND build.status IN ('ready','failed')
                       WHERE warning.workspace_id=%s
                       ORDER BY warning.code, warning.project_name, warning.database_key,
                                warning.source_path, warning.id""",
                    (workspace_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联跳过提示读取失败") from exc
        return [
            TableRelationWarningRecord(
                project_id=str(row["project_id"]),
                project_name=str(row["project_name"]),
                database_key=str(row["database_key"]),
                source_path=str(row["source_path"]),
                code=str(row["code"]),
                message=str(row["message"]),
                expression=str(row["expression"]) if row["expression"] else None,
                occurrence_count=int(row["occurrence_count"]),
            )
            for row in rows
        ]

    def get_sql_whitelist(self, workspace_id: str, project_id: str) -> tuple[str, ...]:
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """SELECT source_path
                       FROM table_relation_sql_whitelist
                       WHERE workspace_id=%s AND project_id=%s
                       ORDER BY LOWER(source_path), source_path""",
                    (workspace_id, project_id),
                ).fetchall()
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联 SQL 白名单读取失败") from exc
        return tuple(str(row[0]) for row in rows)

    def replace_sql_whitelist(
        self,
        *,
        workspace_id: str,
        project_id: str,
        source_paths: list[str],
    ) -> tuple[str, ...]:
        normalized = tuple(sorted(set(source_paths), key=str.casefold))
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """DELETE FROM table_relation_sql_whitelist
                       WHERE workspace_id=%s AND project_id=%s""",
                    (workspace_id, project_id),
                )
                for source_path in normalized:
                    connection.execute(
                        """INSERT INTO table_relation_sql_whitelist (
                               workspace_id, project_id, source_path, updated_at
                           ) VALUES (%s, %s, %s, NOW())""",
                        (workspace_id, project_id, source_path),
                    )
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联 SQL 白名单保存失败") from exc
        return normalized

    def list_automatic_files(
        self,
        workspace_id: str,
        *,
        rule_code: str,
        project_id: str | None = None,
    ) -> list[TableRelationAutomaticFileRecord]:
        try:
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                rows = connection.execute(
                    """SELECT item.project_id, item.project_name, item.database_key,
                              item.source_path, item.rule_code, item.statement_bytes
                       FROM table_relation_automatic_files item
                       JOIN table_relation_builds build
                         ON build.workspace_id=item.workspace_id
                        AND build.project_id=item.project_id
                        AND build.database_key=item.database_key
                        AND build.generation_id=item.generation_id
                        AND build.status IN ('ready','failed')
                       WHERE item.workspace_id=%s AND item.rule_code=%s
                         AND (%s IS NULL OR item.project_id=%s)
                       ORDER BY item.project_name, item.source_path, item.project_id""",
                    (workspace_id, rule_code, project_id, project_id),
                ).fetchall()
        except psycopg.Error as exc:
            raise TableRelationRepositoryError("表关联系统分类读取失败") from exc
        return [
            TableRelationAutomaticFileRecord(
                project_id=str(row["project_id"]),
                project_name=str(row["project_name"]),
                database_key=str(row["database_key"]),
                source_path=str(row["source_path"]),
                rule_code=str(row["rule_code"]),
                statement_bytes=int(row["statement_bytes"]),
            )
            for row in rows
        ]

    @staticmethod
    def _build(row: dict[str, object]) -> TableRelationBuildRecord:
        warnings = row["warnings"] if isinstance(row["warnings"], list) else []
        return TableRelationBuildRecord(
            workspace_id=str(row["workspace_id"]),
            project_id=str(row["project_id"]),
            project_name=str(row["project_name"]),
            database_key=str(row["database_key"]),
            generation_id=str(row["generation_id"]) if row["generation_id"] else None,
            status=str(row["status"]),
            sql_file_count=int(row["sql_file_count"]),
            statement_count=int(row["statement_count"]),
            relation_count=int(row["relation_count"]),
            warnings=tuple(str(item) for item in warnings),
            error_message=str(row["error_message"]) if row["error_message"] else None,
            started_at=row["started_at"] if isinstance(row["started_at"], datetime) else None,
            finished_at=(row["finished_at"] if isinstance(row["finished_at"], datetime) else None),
            warning_count=int(row["warning_count"]),
            config_revision=int(row["config_revision"]),
            automatic_file_count=(
                int(row["automatic_file_count"])
                if row.get("automatic_file_count") is not None
                else None
            ),
        )
