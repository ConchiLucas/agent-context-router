from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from context_router.database.errors import DatabaseConnectorError
from context_router.database.manager import ConnectorManager, ConnectorManagerError
from context_router.database.models import (
    ConnectorSpec,
    DatabaseObject,
    DatabaseObjectType,
    EffectiveQueryPolicy,
    SearchDetail,
    SearchObjectsRequest,
)
from context_router.repositories.data_source_repository import (
    DataSourceRepositoryError,
    DataSourceStore,
    ResolvedProjectDatabase,
)
from context_router.repositories.table_relation_repository import (
    TableJoinEvidenceRecord,
    TableJoinRelationRecord,
    TableRelationBuildRecord,
    TableRelationConfigRevisionError,
    TableRelationDefaultDatabaseConfigRecord,
    TableRelationRepositoryError,
    TableRelationStore,
    TableRelationWarningRecord,
)
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
from context_router.schemas.table_relations import (
    ObservedTableJoin,
    TableIdentity,
    TableJoinColumnPair,
    TableJoinEvidence,
    TableRelationBuildStatus,
    TableRelationContextResult,
    TableRelationDatabaseScope,
    TableRelationDefaultDatabaseConfiguration,
    TableRelationDefaultDatabaseOption,
    TableRelationDefaultDatabaseProject,
    TableRelationDetailLevel,
    TableRelationProjectBuildStatus,
    TableRelationSqlWhitelistConfiguration,
    TableRelationSqlWhitelistRule,
    TableRelationTableList,
    TableRelationTableOption,
    TableRelationWarningCategory,
    TableRelationWarningDisposition,
    TableRelationWarningItem,
    TableRelationWarningList,
    TableRelationWarningProjectSummary,
)
from context_router.services.project_registry import (
    ProjectRegistry,
    ProjectRegistryError,
    ProjectSnapshot,
)
from context_router.services.sql_join_analyzer import (
    AnalyzerWarning,
    MetadataColumnResolution,
    ObservedJoinFact,
    SqlAutomaticWhitelist,
    SqlFileCollector,
    SqlMetadataProvider,
    SqlObservedJoinAnalyzer,
)
from context_router.services.sql_preprocessing import (
    SqlPreprocessorProfileError,
    SqlPreprocessorProfileLoader,
)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

_AUTOMATIC_WHITELIST_RULES = (
    TableRelationSqlWhitelistRule(
        code="automatic_ddl",
        label="DDL",
        description="CREATE、ALTER、DROP、TRUNCATE 等结构语句不参与表关联扫描。",
    ),
    TableRelationSqlWhitelistRule(
        code="automatic_single_table_query",
        label="单表查询",
        description="只读取一张物理表且不包含 JOIN 的查询不参与扫描。",
    ),
    TableRelationSqlWhitelistRule(
        code="automatic_write_without_query",
        label="纯 INSERT / UPDATE",
        description="不包含查询、JOIN、子查询或第二张表的 INSERT / UPDATE 不参与扫描。",
    ),
)


class TableRelationServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _BuildTarget:
    database: ResolvedProjectDatabase
    project_root: Path
    workspace_root: Path


class ConnectorTableMetadataProvider(SqlMetadataProvider):
    _RETRYABLE_CODES = frozenset({"connection_failed", "query_timeout"})

    def __init__(
        self,
        *,
        database: ResolvedProjectDatabase,
        connector_manager: ConnectorManager,
    ) -> None:
        self._database = database
        self._connector_manager = connector_manager
        self._cache: dict[tuple[str, str], tuple[DatabaseObject | None, str | None]] = {}
        self._spec = ConnectorSpec(
            data_source_id=database.data_source_id,
            config_version=database.config_version,
            database_id=database.database_id,
            database_updated_at=database.database_updated_at,
            engine=database.engine,
            remote_name=database.database_remote_name,
            connection_config=database.connection_config,
        )
        self._policy = EffectiveQueryPolicy(
            engine=database.engine,
            current_database=database.database_remote_name,
            readonly=True,
            allowed_schemas=tuple(database.allowed_schemas),
            max_rows=max(1, database.max_rows),
            max_result_bytes=max(1, database.max_result_bytes),
            query_timeout_ms=max(1, database.query_timeout_ms),
        )

    def resolve_column(
        self,
        *,
        database_key: str,
        schema_name: str | None,
        table_name: str,
        column_name: str,
    ) -> tuple[str, str, str] | None:
        return self.resolve_column_detailed(
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
            column_name=column_name,
        ).resolved

    def resolve_column_detailed(
        self,
        *,
        database_key: str,
        schema_name: str | None,
        table_name: str,
        column_name: str,
    ) -> MetadataColumnResolution:
        if database_key.casefold() != self._database.mcp_alias.casefold():
            return MetadataColumnResolution(None, "metadata")
        remote_schema = self._database.database_remote_name
        if schema_name and schema_name.casefold() != remote_schema.casefold():
            return MetadataColumnResolution(None, "table_not_found")
        table, table_failure = self._table(remote_schema, table_name)
        if table is None:
            return MetadataColumnResolution(None, table_failure or "table_not_found")
        columns = table.details.get("columns")
        if not isinstance(columns, list):
            return MetadataColumnResolution(None, "metadata")
        matches = [
            item
            for item in columns
            if isinstance(item, dict)
            and str(item.get("name") or "").casefold() == column_name.casefold()
        ]
        if not matches:
            return MetadataColumnResolution(None, "column_not_found")
        if len(matches) > 1:
            return MetadataColumnResolution(None, "column_ambiguous")
        return MetadataColumnResolution(
            (remote_schema, table.name, str(matches[0]["name"])),
        )

    def _table(
        self,
        schema_name: str,
        table_name: str,
    ) -> tuple[DatabaseObject | None, str | None]:
        key = schema_name.casefold(), table_name.casefold()
        if key in self._cache:
            return self._cache[key]
        request = SearchObjectsRequest(
            object_type=DatabaseObjectType.TABLE,
            schema=schema_name,
            glob=table_name,
            detail=SearchDetail.FULL,
            limit=2,
        )
        result = None
        for attempt in range(3):
            try:
                with self._connector_manager.lease(self._spec) as connector:
                    result = connector.search_objects(request, self._policy)
                break
            except (DatabaseConnectorError, ConnectorManagerError) as exc:
                if exc.code not in self._RETRYABLE_CODES or attempt == 2:
                    raise
                time.sleep(0.05 * (2**attempt))
        if result is None:  # pragma: no cover - defensive; loop either returns or raises
            raise DatabaseConnectorError("catalog_query_failed", "数据库元数据读取失败")
        objects = [
            item
            for item in result.objects
            if isinstance(item, DatabaseObject)
            and item.name.casefold() == table_name.casefold()
            and (item.schema or schema_name).casefold() == schema_name.casefold()
        ]
        if not objects:
            resolved = (None, "table_not_found")
        elif len(objects) > 1:
            resolved = (None, "table_ambiguous")
        else:
            resolved = (objects[0], None)
        self._cache[key] = resolved
        return resolved


class TableRelationService:
    _WARNING_LABELS = {
        "sql_parse_failed": "SQL 语法无法解析",
        "sql_template_fragment_ignored": "动态 SQL 片段已忽略",
        "join_using_unresolved": "JOIN USING 归属不明确",
        "join_or_unsupported": "OR 关联条件暂不支持",
        "join_column_unresolved": "表或字段无法唯一确认",
        "join_derived_relation_unsupported": "CTE 或派生表关系未采集",
        "join_unqualified_column_unsupported": "未限定表别名的字段未采集",
        "join_correlated_reference_unsupported": "相关子查询外层字段未采集",
        "join_alias_unresolved": "表别名无法确认",
        "join_alias_ambiguous": "表别名存在歧义",
        "join_metadata_unresolved": "默认数据库缺少表或字段",
        "join_metadata_table_not_found": "默认数据库缺少表",
        "join_metadata_column_not_found": "默认数据库缺少字段",
        "join_metadata_table_ambiguous": "默认数据库表无法唯一确认",
        "join_metadata_column_ambiguous": "默认数据库字段无法唯一确认",
        "join_non_equality_ignored": "非等值关联未采集",
        "where_relation_unsupported": "WHERE 跨表等值暂未采集",
        "template_candidate_parse_failed": "模板候选 SQL 无法解析",
        "template_candidate_limit_exceeded": "模板候选达到安全上限",
        "template_block_unclosed": "模板条件块未闭合",
        "template_directive_unsupported": "模板指令暂不支持",
        "template_loop_ignored": "循环模板块已忽略",
        "dynamic_identifier_unsupported": "动态表名或字段名暂不支持",
        "template_expression_unsupported": "模板表达式位置暂不支持",
        "migration_sql_ignored": "迁移或 DDL SQL 已安全跳过",
        "source_sql_invalid": "预处理后仍无有效 SQL",
    }
    _WARNING_CLASSIFICATIONS = {
        "sql_parse_failed": "source_error",
        "source_sql_invalid": "source_error",
        "template_candidate_parse_failed": "preprocessor",
        "template_candidate_limit_exceeded": "preprocessor",
        "template_block_unclosed": "preprocessor",
        "template_directive_unsupported": "preprocessor",
        "template_expression_unsupported": "preprocessor",
        "sql_template_fragment_ignored": "preprocessor",
        "join_using_unresolved": "metadata",
        "join_column_unresolved": "metadata",
        "join_alias_unresolved": "source_error",
        "join_alias_ambiguous": "source_error",
        "join_metadata_unresolved": "metadata",
        "join_metadata_table_not_found": "metadata",
        "join_metadata_column_not_found": "metadata",
        "join_metadata_table_ambiguous": "metadata",
        "join_metadata_column_ambiguous": "metadata",
        "join_derived_relation_unsupported": "safe_skip",
        "join_unqualified_column_unsupported": "safe_skip",
        "join_correlated_reference_unsupported": "safe_skip",
        "migration_sql_ignored": "safe_skip",
        "join_or_unsupported": "safe_skip",
        "join_non_equality_ignored": "safe_skip",
        "where_relation_unsupported": "safe_skip",
        "template_loop_ignored": "safe_skip",
        "dynamic_identifier_unsupported": "safe_skip",
    }

    def __init__(
        self,
        *,
        registry: ProjectRegistry,
        task_repository: TaskReader,
        data_source_repository: DataSourceStore,
        repository: TableRelationStore,
        connector_manager: ConnectorManager,
        collector: SqlFileCollector | None = None,
        analyzer: SqlObservedJoinAnalyzer | None = None,
        automatic_whitelist: SqlAutomaticWhitelist | None = None,
        profile_loader: SqlPreprocessorProfileLoader | None = None,
    ) -> None:
        self._registry = registry
        self._task_repository = task_repository
        self._data_source_repository = data_source_repository
        self._repository = repository
        self._connector_manager = connector_manager
        self._collector = collector or SqlFileCollector()
        self._analyzer = analyzer or SqlObservedJoinAnalyzer()
        self._automatic_whitelist = automatic_whitelist or SqlAutomaticWhitelist()
        self._profile_loader = profile_loader or SqlPreprocessorProfileLoader()

    def get_sql_whitelist(
        self,
        workspace_id: str,
        project_id: str,
    ) -> TableRelationSqlWhitelistConfiguration:
        project = self._project_for_workspace(workspace_id, project_id)
        try:
            paths = self._repository.get_sql_whitelist(workspace_id, project_id)
            builds = self._repository.list_builds(workspace_id)
            warnings = self._repository.list_warnings(workspace_id)
        except TableRelationRepositoryError as exc:
            raise TableRelationServiceError(
                "table_relation_repository_error", "表关联 SQL 白名单读取失败"
            ) from exc
        config = self._default_config(workspace_id)
        active_keys = {
            (item.project_id.casefold(), item.database_key.casefold())
            for item in builds
            if item.project_id == project_id and item.config_revision == config.revision
        }
        stored = {item.casefold() for item in paths}
        suggested = sorted(
            {
                item.source_path
                for item in warnings
                if (item.project_id.casefold(), item.database_key.casefold()) in active_keys
                and self._warning_disposition(item.code) == "attention"
                and item.source_path.casefold() not in stored
            },
            key=str.casefold,
        )
        return TableRelationSqlWhitelistConfiguration(
            workspace_id=workspace_id,
            project_id=project_id,
            project_name=project.name,
            paths=list(paths),
            suggested_paths=suggested,
            automatic_rules=list(_AUTOMATIC_WHITELIST_RULES),
        )

    def replace_sql_whitelist(
        self,
        *,
        workspace_id: str,
        project_id: str,
        paths: list[str],
    ) -> TableRelationSqlWhitelistConfiguration:
        self._project_for_workspace(workspace_id, project_id)
        normalized = self._normalize_whitelist_paths(paths)
        try:
            self._repository.replace_sql_whitelist(
                workspace_id=workspace_id,
                project_id=project_id,
                source_paths=normalized,
            )
        except TableRelationRepositoryError as exc:
            raise TableRelationServiceError(
                "table_relation_repository_error", "表关联 SQL 白名单保存失败"
            ) from exc
        return self.get_sql_whitelist(workspace_id, project_id)

    def get_default_database_configuration(
        self,
        workspace_id: str,
    ) -> TableRelationDefaultDatabaseConfiguration:
        databases = self._eligible_databases(workspace_id)
        config = self._default_config(workspace_id)
        selected = dict(config.targets)
        grouped: dict[str, list[ResolvedProjectDatabase]] = {}
        for database in databases:
            grouped.setdefault(database.project_id, []).append(database)
        projects: list[TableRelationDefaultDatabaseProject] = []
        configured_count = 0
        for project_id, options in grouped.items():
            selected_link_id = selected.get(project_id)
            valid_selection = any(item.link_id == selected_link_id for item in options)
            if valid_selection:
                configured_count += 1
            projects.append(
                TableRelationDefaultDatabaseProject(
                    project_id=project_id,
                    project_name=options[0].project_name,
                    selected_project_database_id=(selected_link_id if valid_selection else None),
                    options=[
                        TableRelationDefaultDatabaseOption(
                            project_database_id=item.link_id,
                            database_key=item.mcp_alias,
                            schema_name=item.database_remote_name,
                            data_source_name=item.data_source_name,
                            display_name=item.database_display_name or item.database_remote_name,
                            selected=item.link_id == selected_link_id,
                        )
                        for item in sorted(
                            options,
                            key=lambda value: (
                                value.database_remote_name.casefold(),
                                value.mcp_alias.casefold(),
                            ),
                        )
                    ],
                )
            )
        projects.sort(key=lambda item: (item.project_name.casefold(), item.project_id))
        return TableRelationDefaultDatabaseConfiguration(
            workspace_id=workspace_id,
            revision=config.revision,
            configured=bool(projects) and configured_count == len(projects),
            eligible_project_count=len(projects),
            configured_project_count=configured_count,
            projects=projects,
        )

    def replace_default_databases(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        defaults: list[tuple[str, str]],
    ) -> TableRelationDefaultDatabaseConfiguration:
        databases = self._eligible_databases(workspace_id)
        options = {(item.project_id, item.link_id): item for item in databases}
        eligible_projects = {item.project_id for item in databases}
        selected_projects = [project_id for project_id, _ in defaults]
        if len(set(selected_projects)) != len(selected_projects):
            raise TableRelationServiceError(
                "table_relation_default_database_duplicate_project",
                "同一个项目只能选择一个表关联默认数据库",
            )
        if set(selected_projects) != eligible_projects:
            missing = sorted(eligible_projects - set(selected_projects))
            unknown = sorted(set(selected_projects) - eligible_projects)
            detail = []
            if missing:
                detail.append(f"缺少项目：{', '.join(missing)}")
            if unknown:
                detail.append(f"无效项目：{', '.join(unknown)}")
            raise TableRelationServiceError(
                "table_relation_default_database_incomplete",
                "必须为每个可用后端项目选择一个默认数据库；" + "；".join(detail),
            )
        invalid = [
            (project_id, link_id)
            for project_id, link_id in defaults
            if (project_id, link_id) not in options
        ]
        if invalid:
            raise TableRelationServiceError(
                "table_relation_default_database_invalid",
                "默认数据库必须是该项目已授权、可用且只读的 MySQL/MariaDB 数据库",
            )
        try:
            self._repository.replace_default_databases(
                workspace_id=workspace_id,
                expected_revision=expected_revision,
                targets=defaults,
            )
        except TableRelationConfigRevisionError as exc:
            raise TableRelationServiceError(
                "table_relation_default_database_revision_conflict",
                str(exc),
            ) from exc
        except TableRelationRepositoryError as exc:
            raise TableRelationServiceError(
                "table_relation_repository_error",
                "表关联默认数据库保存失败",
            ) from exc
        return self.get_default_database_configuration(workspace_id)

    def rebuild(
        self,
        workspace_id: str,
        *,
        failed_only: bool = False,
        project_id: str | None = None,
    ) -> TableRelationBuildStatus:
        config = self._require_complete_default_config(workspace_id)
        targets = self._targets(workspace_id, config)
        if not targets:
            raise TableRelationServiceError(
                "table_relation_database_not_configured",
                "工作空间没有可用于 SQL 表关联校验的 MySQL 或 MariaDB 数据库",
            )
        if project_id is not None:
            targets = [target for target in targets if target.database.project_id == project_id]
            if not targets:
                raise TableRelationServiceError(
                    "table_relation_project_not_found",
                    "项目不属于当前工作空间，或没有配置表关联默认数据库",
                )
        if failed_only:
            failed_targets = {
                (item.project_id, item.database_key.casefold())
                for item in self._repository.list_builds(workspace_id)
                if item.status == "failed" and item.config_revision == config.revision
            }
            targets = [
                target
                for target in targets
                if (
                    target.database.project_id,
                    target.database.mcp_alias.casefold(),
                )
                in failed_targets
            ]
            if not targets:
                return self.get_status(workspace_id)
        try:
            profiles = self._profile_loader.load(targets[0].workspace_root)
        except SqlPreprocessorProfileError as exc:
            raise TableRelationServiceError(
                "table_relation_preprocessor_profile_invalid",
                str(exc),
            ) from exc
        failures: list[str] = []
        for target in targets:
            generation_id = uuid4().hex
            database = target.database
            self._repository.mark_building(
                workspace_id=workspace_id,
                project_id=database.project_id,
                project_name=database.project_name,
                database_key=database.mcp_alias,
                generation_id=generation_id,
                config_revision=config.revision,
            )
            analyzer_warnings: list[AnalyzerWarning] = []
            try:
                sources = self._collector.collect(
                    workspace_id=workspace_id,
                    project_id=database.project_id,
                    project_name=database.project_name,
                    project_root=target.project_root,
                    database_key=database.mcp_alias,
                    dialect="mysql",
                )
                custom_whitelist = {
                    item.casefold()
                    for item in self._repository.get_sql_whitelist(
                        workspace_id,
                        database.project_id,
                    )
                }
                sources = [
                    source
                    for source in sources
                    if source.source_path.casefold() not in custom_whitelist
                    and self._automatic_whitelist.classify(source) is None
                ]
                metadata = ConnectorTableMetadataProvider(
                    database=database,
                    connector_manager=self._connector_manager,
                )
                facts: list[ObservedJoinFact] = []
                statement_count = 0
                for source in sources:
                    excluded_profile = profiles.excluded_by(
                        project_name=source.project_name,
                        source_path=source.source_path,
                        dialect=source.dialect,
                    )
                    if excluded_profile is not None:
                        analyzer_warnings.append(
                            AnalyzerWarning(
                                source_path=source.source_path,
                                code="migration_sql_ignored",
                                message=(
                                    "路径被工作空间 SQL Profile 排除，未作为运行时表关联 SQL 解析"
                                ),
                                expression=excluded_profile.profile_id,
                            )
                        )
                        continue
                    profile = profiles.match(
                        project_name=source.project_name,
                        source_path=source.source_path,
                        dialect=source.dialect,
                    )
                    source_facts, source_warnings, parsed_count = self._analyzer.analyze(
                        source, metadata, profile
                    )
                    facts.extend(source_facts)
                    statement_count += parsed_count
                    analyzer_warnings.extend(source_warnings)
                relations = self._aggregate(workspace_id, facts)
                warning_records = self._aggregate_warnings(database, analyzer_warnings)
                warning_previews = [self._warning_preview(item) for item in warning_records[:20]]
                build = TableRelationBuildRecord(
                    workspace_id=workspace_id,
                    project_id=database.project_id,
                    project_name=database.project_name,
                    database_key=database.mcp_alias,
                    generation_id=generation_id,
                    status="building",
                    sql_file_count=len(sources),
                    statement_count=statement_count,
                    relation_count=len(relations),
                    warnings=tuple(warning_previews),
                    error_message=None,
                    started_at=datetime.now(UTC),
                    finished_at=None,
                    warning_count=sum(item.occurrence_count for item in warning_records),
                    config_revision=config.revision,
                )
                self._repository.publish(
                    build=build,
                    relations=relations,
                    warning_records=warning_records,
                )
            except Exception as exc:
                message = self._safe_error(exc)
                failures.append(f"{database.project_name}/{database.mcp_alias}: {message}")
                warning_records = self._aggregate_warnings(database, analyzer_warnings)
                self._repository.mark_failed(
                    workspace_id=workspace_id,
                    project_id=database.project_id,
                    project_name=database.project_name,
                    database_key=database.mcp_alias,
                    generation_id=generation_id,
                    error_message=message,
                    warnings=[self._warning_preview(item) for item in warning_records[:20]],
                    warning_records=warning_records,
                )
        status = self.get_status(workspace_id)
        if failures and status.ready_project_count == 0:
            raise TableRelationServiceError(
                "table_relation_build_failed",
                "；".join(failures[:5]),
            )
        return status

    def _project_for_workspace(self, workspace_id: str, project_id: str) -> ProjectSnapshot:
        try:
            project = self._registry.get_snapshot(project_id)
        except ProjectRegistryError as exc:
            raise TableRelationServiceError(
                "table_relation_project_not_found", "项目不属于当前工作空间"
            ) from exc
        if project.workspace_id != workspace_id or project.project_kind != "backend":
            raise TableRelationServiceError(
                "table_relation_project_not_found", "项目不属于当前工作空间"
            )
        return project

    @staticmethod
    def _normalize_whitelist_paths(paths: list[str]) -> list[str]:
        normalized: dict[str, str] = {}
        for path in paths:
            value = path.strip().replace("\\", "/")
            candidate = PurePosixPath(value)
            if (
                not value
                or len(value) > 1000
                or candidate.is_absolute()
                or ".." in candidate.parts
                or candidate.suffix.casefold() != ".sql"
            ):
                raise TableRelationServiceError(
                    "table_relation_sql_whitelist_invalid_path",
                    "白名单只能保存项目内、不包含上级目录的 .sql 相对路径",
                )
            canonical = candidate.as_posix()
            normalized.setdefault(canonical.casefold(), canonical)
        if len(normalized) > 1000:
            raise TableRelationServiceError(
                "table_relation_sql_whitelist_too_large",
                "每个项目最多保存 1000 条 SQL 白名单路径",
            )
        return sorted(normalized.values(), key=str.casefold)

    def get_status(
        self,
        workspace_id: str,
    ) -> TableRelationBuildStatus:
        configuration = self.get_default_database_configuration(workspace_id)
        config = self._default_config(workspace_id)
        try:
            builds = self._repository.list_builds(workspace_id)
            warning_records = self._repository.list_warnings(workspace_id)
        except TableRelationRepositoryError as exc:
            raise TableRelationServiceError(
                "table_relation_repository_error", "表关联构建状态读取失败"
            ) from exc
        configured_projects = {project_id for project_id, _ in config.targets}
        builds = [
            item
            for item in builds
            if item.config_revision == config.revision and item.project_id in configured_projects
        ]
        active_warning_keys = {
            (item.project_id.casefold(), item.database_key.casefold()) for item in builds
        }
        warning_records = [
            item
            for item in warning_records
            if (item.project_id.casefold(), item.database_key.casefold()) in active_warning_keys
        ]
        attention_warning_count = sum(
            item.occurrence_count
            for item in warning_records
            if self._warning_disposition(item.code) == "attention"
        )
        expected_skip_count = sum(
            item.occurrence_count
            for item in warning_records
            if self._warning_disposition(item.code) == "expected"
        )
        project_statuses = self._project_build_statuses(
            configuration=configuration,
            builds=builds,
            warning_records=warning_records,
        )
        if not configuration.configured:
            return TableRelationBuildStatus(
                workspace_id=workspace_id,
                status="missing",
                project_count=configuration.eligible_project_count,
                ready_project_count=0,
                sql_file_count=0,
                statement_count=0,
                relation_count=0,
                warning_count=0,
                warnings=["请先为每个可用后端项目配置表关联默认数据库"],
                config_revision=config.revision,
                eligible_project_count=configuration.eligible_project_count,
                configured_project_count=configuration.configured_project_count,
                projects=project_statuses,
            )
        if not builds:
            return TableRelationBuildStatus(
                workspace_id=workspace_id,
                status="missing",
                project_count=configuration.eligible_project_count,
                ready_project_count=0,
                sql_file_count=0,
                statement_count=0,
                relation_count=0,
                warning_count=0,
                config_revision=config.revision,
                eligible_project_count=configuration.eligible_project_count,
                configured_project_count=configuration.configured_project_count,
                projects=project_statuses,
            )
        built_projects = {item.project_id for item in builds}
        missing_build_count = max(
            0,
            configuration.eligible_project_count - len(built_projects),
        )
        status = (
            "building"
            if any(item.status == "building" for item in builds)
            else "partial"
            if any(item.status == "failed" for item in builds)
            and any(item.status == "ready" for item in builds)
            else "failed"
            if all(item.status == "failed" for item in builds)
            else "partial"
            if missing_build_count > 0
            else "ready"
        )
        warning_previews = [warning for build in builds for warning in build.warnings]
        latest = max(
            (item.finished_at or item.started_at for item in builds if item.started_at),
            default=None,
        )
        return TableRelationBuildStatus(
            workspace_id=workspace_id,
            status=status,
            generation_id=(
                builds[0].generation_id
                if len({item.generation_id for item in builds}) == 1
                else None
            ),
            project_count=configuration.eligible_project_count,
            ready_project_count=sum(item.status == "ready" for item in builds),
            sql_file_count=sum(item.sql_file_count for item in builds),
            statement_count=sum(item.statement_count for item in builds),
            relation_count=sum(item.relation_count for item in builds),
            warning_count=sum(item.warning_count for item in builds),
            attention_warning_count=attention_warning_count,
            expected_skip_count=expected_skip_count,
            warnings=warning_previews[:20],
            error_message="；".join(item.error_message for item in builds if item.error_message)
            or None,
            started_at=min((item.started_at for item in builds if item.started_at), default=None),
            finished_at=latest if status != "building" else None,
            config_revision=config.revision,
            eligible_project_count=configuration.eligible_project_count,
            configured_project_count=configuration.configured_project_count,
            projects=project_statuses,
        )

    def _project_build_statuses(
        self,
        *,
        configuration: TableRelationDefaultDatabaseConfiguration,
        builds: list[TableRelationBuildRecord],
        warning_records: list[TableRelationWarningRecord],
    ) -> list[TableRelationProjectBuildStatus]:
        builds_by_project = {item.project_id: item for item in builds}
        warning_counts: dict[tuple[str, str], tuple[int, int]] = {}
        for warning in warning_records:
            key = (warning.project_id.casefold(), warning.database_key.casefold())
            attention, expected = warning_counts.get(key, (0, 0))
            if self._warning_disposition(warning.code) == "attention":
                attention += warning.occurrence_count
            else:
                expected += warning.occurrence_count
            warning_counts[key] = (attention, expected)

        result: list[TableRelationProjectBuildStatus] = []
        for project in configuration.projects:
            selected_option = next((item for item in project.options if item.selected), None)
            build = builds_by_project.get(project.project_id)
            database_key = selected_option.database_key if selected_option else None
            if build is None:
                result.append(
                    TableRelationProjectBuildStatus(
                        project_id=project.project_id,
                        project_name=project.project_name,
                        database_key=database_key,
                        status="missing",
                        sql_file_count=0,
                        statement_count=0,
                        relation_count=0,
                        warning_count=0,
                    )
                )
                continue
            attention, expected = warning_counts.get(
                (build.project_id.casefold(), build.database_key.casefold()),
                (0, 0),
            )
            result.append(
                TableRelationProjectBuildStatus(
                    project_id=build.project_id,
                    project_name=build.project_name,
                    database_key=build.database_key,
                    status=build.status,
                    sql_file_count=build.sql_file_count,
                    statement_count=build.statement_count,
                    relation_count=build.relation_count,
                    warning_count=build.warning_count,
                    attention_warning_count=attention,
                    expected_skip_count=expected,
                    error_message=build.error_message,
                    started_at=build.started_at,
                    finished_at=build.finished_at,
                )
            )
        return result

    def list_tables(
        self,
        workspace_id: str,
        query: str = "",
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> TableRelationTableList:
        relations = self._ready_relations(workspace_id)
        counts: dict[tuple[str, str, str, str], tuple[TableIdentity, int]] = {}
        for relation in relations:
            for identity in self._relation_identities(relation):
                key = self._identity_key(identity)
                current = counts.get(key)
                counts[key] = (identity, 1 if current is None else current[1] + 1)
        normalized_query = query.strip().casefold()
        options = [
            TableRelationTableOption(**identity.model_dump(), relation_count=count)
            for identity, count in counts.values()
            if not normalized_query or normalized_query in identity.table_name.casefold()
        ]
        options.sort(
            key=lambda item: (
                item.table_name.casefold(),
                item.database_key.casefold(),
                item.project_name.casefold(),
            )
        )
        total = len(options)
        page = options[offset : offset + limit]
        next_offset = offset + len(page)
        has_more = next_offset < total
        return TableRelationTableList(
            workspace_id=workspace_id,
            total=total,
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=next_offset if has_more else None,
            tables=page,
        )

    def list_warnings(
        self,
        workspace_id: str,
        *,
        code: str | None = None,
        project_id: str | None = None,
        disposition: TableRelationWarningDisposition | None = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> TableRelationWarningList:
        try:
            records = self._repository.list_warnings(workspace_id)
        except TableRelationRepositoryError as exc:
            raise TableRelationServiceError(
                "table_relation_repository_error", "表关联跳过提示读取失败"
            ) from exc
        active_keys = self._active_build_keys(workspace_id)
        records = [
            item
            for item in records
            if (item.project_id.casefold(), item.database_key.casefold()) in active_keys
        ]
        attention_total = sum(
            item.occurrence_count
            for item in records
            if self._warning_disposition(item.code) == "attention"
        )
        expected_total = sum(
            item.occurrence_count
            for item in records
            if self._warning_disposition(item.code) == "expected"
        )
        scoped_records = [
            item
            for item in records
            if disposition is None or self._warning_disposition(item.code) == disposition
        ]
        project_counts: dict[tuple[str, str, str], int] = {}
        for item in scoped_records:
            key = item.project_id, item.project_name, item.database_key
            project_counts[key] = project_counts.get(key, 0) + item.occurrence_count
        projects = [
            TableRelationWarningProjectSummary(
                project_id=item_project_id,
                project_name=project_name,
                database_key=database_key,
                count=count,
            )
            for (item_project_id, project_name, database_key), count in sorted(
                project_counts.items(),
                key=lambda entry: (-entry[1], entry[0][1].casefold(), entry[0][2].casefold()),
            )
        ]
        category_counts: dict[str, int] = {}
        for item in scoped_records:
            category_counts[item.code] = category_counts.get(item.code, 0) + item.occurrence_count
        categories = [
            TableRelationWarningCategory(
                code=item_code,
                label=self._warning_label(item_code),
                classification=self._warning_classification(item_code),
                disposition=self._warning_disposition(item_code),
                count=count,
            )
            for item_code, count in sorted(
                category_counts.items(), key=lambda entry: (-entry[1], entry[0])
            )
        ]
        normalized_code = code.strip() if code else None
        normalized_project_id = project_id.strip() if project_id else None
        normalized_query = query.strip().casefold()
        filtered = [
            item
            for item in scoped_records
            if (not normalized_code or item.code == normalized_code)
            and (not normalized_project_id or item.project_id == normalized_project_id)
            and (
                not normalized_query
                or normalized_query in item.source_path.casefold()
                or normalized_query in item.project_name.casefold()
                or normalized_query in item.database_key.casefold()
                or normalized_query in item.message.casefold()
                or normalized_query in (item.expression or "").casefold()
            )
        ]
        total = sum(item.occurrence_count for item in filtered)
        selected = filtered[offset : offset + limit]
        return TableRelationWarningList(
            workspace_id=workspace_id,
            total=total,
            attention_total=attention_total,
            expected_total=expected_total,
            limit=limit,
            offset=offset,
            categories=categories,
            projects=projects,
            warnings=[
                TableRelationWarningItem(
                    project_id=item.project_id,
                    project_name=item.project_name,
                    database_key=item.database_key,
                    source_path=item.source_path,
                    code=item.code,
                    category=self._warning_label(item.code),
                    classification=self._warning_classification(item.code),
                    disposition=self._warning_disposition(item.code),
                    message=_ANSI_ESCAPE_RE.sub("", item.message),
                    expression=item.expression,
                    occurrence_count=item.occurrence_count,
                )
                for item in selected
            ],
        )

    def context_for_workspace(
        self,
        *,
        workspace_id: str,
        table: str,
        database_key: str | None = None,
        schema: str | None = None,
        detail_level: TableRelationDetailLevel = "full",
        relation_limit: int | None = None,
        relation_offset: int = 0,
        evidence_limit_per_join: int = 10,
        task_id: int | None = None,
    ) -> TableRelationContextResult:
        if relation_limit is not None and not 1 <= relation_limit <= 100:
            raise TableRelationServiceError(
                "table_relation_invalid_limit", "relation_limit 必须在 1 到 100 之间"
            )
        if relation_offset < 0:
            raise TableRelationServiceError(
                "table_relation_invalid_offset", "relation_offset 不能小于 0"
            )
        if not 1 <= evidence_limit_per_join <= 20:
            raise TableRelationServiceError(
                "table_relation_invalid_evidence_limit",
                "evidence_limit_per_join 必须在 1 到 20 之间",
            )
        normalized_table = table.strip().casefold()
        if not normalized_table or "*" in normalized_table or "%" in normalized_table:
            raise TableRelationServiceError(
                "table_relation_exact_table_required", "必须提供不带通配符的精确表名"
            )
        relations = self._ready_relations(workspace_id)
        matches: dict[tuple[str, str, str, str], TableIdentity] = {}
        for relation in relations:
            for identity in self._relation_identities(relation):
                if identity.table_name.casefold() != normalized_table:
                    continue
                if database_key and identity.database_key.casefold() != database_key.casefold():
                    continue
                if schema and identity.schema_name.casefold() != schema.casefold():
                    continue
                matches[self._identity_key(identity)] = identity
        if not matches:
            raise TableRelationServiceError(
                "table_relation_table_not_found",
                "工作空间默认数据库的表关联索引中没有这张表",
            )
        if len(matches) != 1:
            candidates = ", ".join(
                f"{item.project_name}/{item.database_key}/{item.schema_name}/{item.table_name}"
                for item in sorted(matches.values(), key=lambda value: self._identity_key(value))
            )
            raise TableRelationServiceError(
                "table_relation_ambiguous_table",
                f"表名存在歧义，请指定 database_key/schema：{candidates}",
            )
        root = next(iter(matches.values()))
        root_key = self._identity_key(root)
        selected = sorted(
            (
                relation
                for relation in relations
                if root_key
                in {self._identity_key(item) for item in self._relation_identities(relation)}
            ),
            key=lambda relation: relation.relation_id,
        )
        total_relation_count = len(selected)
        page_end = relation_offset + relation_limit if relation_limit is not None else None
        selected_page = selected[relation_offset:page_end]
        related: dict[tuple[str, str, str, str], TableIdentity] = {}
        joins: list[ObservedTableJoin] = []
        for relation in selected_page:
            table_a, table_b = self._relation_identities(relation)
            other = table_b if self._identity_key(table_a) == root_key else table_a
            related[self._identity_key(other)] = other
            selected_evidence = (
                relation.evidences[:evidence_limit_per_join] if detail_level != "compact" else ()
            )
            joins.append(
                ObservedTableJoin(
                    relation_id=relation.relation_id,
                    table_a=table_a,
                    table_b=table_b,
                    column_pairs=[
                        TableJoinColumnPair(column_a=left, column_b=right)
                        for left, right in relation.column_pairs
                    ],
                    statement_count=len(
                        {
                            (evidence.source_path, evidence.sql_statement)
                            for evidence in relation.evidences
                        }
                    ),
                    source_file_count=len(
                        {evidence.source_path for evidence in relation.evidences}
                    ),
                    evidence_total=len(relation.evidences),
                    evidence_returned=len(selected_evidence),
                    evidence_truncated=len(selected_evidence) < len(relation.evidences),
                    evidence=(
                        [
                            TableJoinEvidence(
                                source_path=evidence.source_path,
                                join_expression=evidence.join_expression,
                                sql_statement=(
                                    evidence.sql_statement if detail_level == "full" else None
                                ),
                                preprocess_profile_id=evidence.preprocess_profile_id,
                                preprocess_profile_hash=(
                                    evidence.preprocess_profile_hash
                                    if detail_level == "full"
                                    else None
                                ),
                                preprocess_candidate_id=(
                                    evidence.preprocess_candidate_id
                                    if detail_level == "full"
                                    else None
                                ),
                                applied_rules=list(evidence.applied_rules),
                                template_derived=evidence.template_derived,
                            )
                            for evidence in selected_evidence
                        ]
                        if detail_level != "compact"
                        else []
                    ),
                )
            )
        returned_relation_count = len(joins)
        next_offset_value = relation_offset + returned_relation_count
        has_more = next_offset_value < total_relation_count
        return TableRelationContextResult(
            workspace_id=workspace_id,
            task_id=task_id,
            detail_level=detail_level,
            relation_database_scope=TableRelationDatabaseScope(
                config_revision=self._default_config(workspace_id).revision,
                database_key=root.database_key,
                schema_name=root.schema_name,
            ),
            root_table=root,
            related_tables=sorted(related.values(), key=lambda item: self._identity_key(item)),
            joins=joins,
            total_relation_count=total_relation_count,
            returned_relation_count=returned_relation_count,
            has_more=has_more,
            next_offset=next_offset_value if has_more else None,
        )

    def context_for_task(
        self,
        *,
        task_id: int,
        table: str,
        database_key: str | None = None,
        schema: str | None = None,
        detail_level: TableRelationDetailLevel = "evidence",
        relation_limit: int = 20,
        relation_offset: int = 0,
        evidence_limit_per_join: int = 5,
    ) -> TableRelationContextResult:
        try:
            task = self._task_repository.get_task(task_id)
        except TaskRepositoryError as exc:
            raise TableRelationServiceError("task_not_found", "任务不存在，请重新 prepare") from exc
        if task.scope != "workspace" or not task.workspace_id:
            raise TableRelationServiceError(
                "workspace_task_required", "表关联工具需要 Workspace task"
            )
        try:
            self._registry.get_workspace_snapshot_for_task(
                workspace_id=task.workspace_id,
                workspace_key=task.workspace_key,
            )
        except ProjectRegistryError as exc:
            raise TableRelationServiceError(
                "workspace_unavailable", "任务绑定的工作空间当前不可用，请重新 prepare"
            ) from exc
        return self.context_for_workspace(
            workspace_id=task.workspace_id,
            table=table,
            database_key=database_key,
            schema=schema,
            detail_level=detail_level,
            relation_limit=relation_limit,
            relation_offset=relation_offset,
            evidence_limit_per_join=evidence_limit_per_join,
            task_id=task_id,
        )

    def _ready_relations(
        self,
        workspace_id: str,
    ) -> list[TableJoinRelationRecord]:
        status = self.get_status(workspace_id)
        if status.status not in {"ready", "partial"}:
            raise TableRelationServiceError(
                "table_relation_index_not_ready",
                "表关联索引尚未构建完成，请先刷新表关联",
            )
        try:
            relations = self._repository.list_relations(workspace_id)
        except TableRelationRepositoryError as exc:
            raise TableRelationServiceError(
                "table_relation_repository_error", "表关联关系读取失败"
            ) from exc
        active_keys = self._active_build_keys(workspace_id)
        return [
            relation
            for relation in relations
            if (relation.project_id.casefold(), relation.database_key.casefold()) in active_keys
        ]

    def _default_config(
        self,
        workspace_id: str,
    ) -> TableRelationDefaultDatabaseConfigRecord:
        try:
            return self._repository.get_default_database_config(workspace_id)
        except TableRelationRepositoryError as exc:
            raise TableRelationServiceError(
                "table_relation_repository_error",
                "表关联默认数据库配置读取失败",
            ) from exc

    def _eligible_databases(self, workspace_id: str) -> list[ResolvedProjectDatabase]:
        try:
            snapshot = self._registry.get_workspace_snapshot(workspace_id)
            databases = self._data_source_repository.list_workspace_databases_for_mcp(workspace_id)
        except (ProjectRegistryError, DataSourceRepositoryError) as exc:
            raise TableRelationServiceError(
                "table_relation_workspace_unavailable", "工作空间或数据库授权暂时不可用"
            ) from exc
        projects = {project.id: project for project in snapshot.projects}
        eligible: list[ResolvedProjectDatabase] = []
        seen: set[str] = set()
        for database in databases:
            project = projects.get(database.project_id)
            if (
                project is None
                or project.project_kind != "backend"
                or database.engine not in {"mysql", "mariadb"}
                or not database.readonly
                or not database.database_available
                or database.database_system
                or database.link_id in seen
            ):
                continue
            seen.add(database.link_id)
            eligible.append(database)
        return sorted(
            eligible,
            key=lambda item: (
                item.project_name.casefold(),
                item.database_remote_name.casefold(),
                item.mcp_alias.casefold(),
            ),
        )

    def _require_complete_default_config(
        self,
        workspace_id: str,
    ) -> TableRelationDefaultDatabaseConfigRecord:
        config = self._default_config(workspace_id)
        eligible = self._eligible_databases(workspace_id)
        options = {(item.project_id, item.link_id) for item in eligible}
        eligible_projects = {item.project_id for item in eligible}
        selected_projects = {project_id for project_id, _ in config.targets}
        if (
            config.revision < 1
            or not eligible_projects
            or selected_projects != eligible_projects
            or any(target not in options for target in config.targets)
        ):
            raise TableRelationServiceError(
                "table_relation_default_database_not_configured",
                "请先为每个可用后端项目配置一个表关联默认数据库",
            )
        return config

    def _active_build_keys(self, workspace_id: str) -> frozenset[tuple[str, str]]:
        config = self._require_complete_default_config(workspace_id)
        configured_projects = {project_id.casefold() for project_id, _ in config.targets}
        try:
            builds = self._repository.list_builds(workspace_id)
        except TableRelationRepositoryError as exc:
            raise TableRelationServiceError(
                "table_relation_repository_error",
                "表关联构建状态读取失败",
            ) from exc
        return frozenset(
            (item.project_id.casefold(), item.database_key.casefold())
            for item in builds
            if item.config_revision == config.revision
            and item.project_id.casefold() in configured_projects
        )

    def _targets(
        self,
        workspace_id: str,
        config: TableRelationDefaultDatabaseConfigRecord,
    ) -> list[_BuildTarget]:
        try:
            snapshot = self._registry.get_workspace_snapshot(workspace_id)
        except ProjectRegistryError as exc:
            raise TableRelationServiceError(
                "table_relation_workspace_unavailable", "工作空间暂时不可用"
            ) from exc
        projects = {project.id: project for project in snapshot.projects}
        databases = {
            (item.project_id, item.link_id): item for item in self._eligible_databases(workspace_id)
        }
        targets: list[_BuildTarget] = []
        for project_id, link_id in config.targets:
            database = databases.get((project_id, link_id))
            project = projects.get(project_id)
            if database is None or project is None:
                raise TableRelationServiceError(
                    "table_relation_default_database_not_configured",
                    "表关联默认数据库已经失效，请重新配置",
                )
            targets.append(
                _BuildTarget(
                    database=database,
                    project_root=project.resolved_project_root,
                    workspace_root=snapshot.resolved_root_path,
                )
            )
        return sorted(
            targets,
            key=lambda item: (
                item.database.project_name.casefold(),
                item.database.database_remote_name.casefold(),
            ),
        )

    @classmethod
    def _aggregate(
        cls,
        workspace_id: str,
        facts: list[ObservedJoinFact],
    ) -> list[TableJoinRelationRecord]:
        grouped: dict[
            tuple[tuple[str, str, str, str], tuple[str, str, str, str]],
            dict[str, Any],
        ] = {}
        for fact in facts:
            left_table = fact.left.table_key
            right_table = fact.right.table_key
            swap = right_table < left_table
            first = fact.right if swap else fact.left
            second = fact.left if swap else fact.right
            key = first.table_key, second.table_key
            group = grouped.setdefault(
                key,
                {"first": first, "second": second, "pairs": set(), "evidences": set()},
            )
            group["pairs"].add((first.column_name, second.column_name))
            group["evidences"].add(
                (
                    fact.source_path,
                    fact.join_expression,
                    fact.sql_statement,
                    fact.preprocess_profile_id or "",
                    fact.preprocess_profile_hash or "",
                    fact.preprocess_candidate_id or "",
                    fact.applied_rules,
                    fact.template_derived,
                )
            )
        records: list[TableJoinRelationRecord] = []
        for key, group in grouped.items():
            first = group["first"]
            second = group["second"]
            identity = "\0".join([workspace_id, *key[0], *key[1]])
            relation_id = hashlib.sha256(identity.encode()).hexdigest()
            records.append(
                TableJoinRelationRecord(
                    relation_id=relation_id,
                    workspace_id=workspace_id,
                    project_id=first.project_id,
                    project_name=first.project_name,
                    database_key=first.database_key,
                    table_a_schema=first.schema_name,
                    table_a_name=first.table_name,
                    table_b_schema=second.schema_name,
                    table_b_name=second.table_name,
                    column_pairs=tuple(sorted(group["pairs"])),
                    evidences=tuple(
                        TableJoinEvidenceRecord(
                            source_path=path,
                            join_expression=expression,
                            sql_statement=statement,
                            preprocess_profile_id=profile_id or None,
                            preprocess_profile_hash=profile_hash or None,
                            preprocess_candidate_id=candidate_id or None,
                            applied_rules=rules,
                            template_derived=template_derived,
                        )
                        for (
                            path,
                            expression,
                            statement,
                            profile_id,
                            profile_hash,
                            candidate_id,
                            rules,
                            template_derived,
                        ) in sorted(group["evidences"])
                    ),
                )
            )
        return sorted(records, key=lambda item: item.relation_id)

    @classmethod
    def _aggregate_warnings(
        cls,
        database: ResolvedProjectDatabase,
        warnings: list[AnalyzerWarning],
    ) -> list[TableRelationWarningRecord]:
        grouped: dict[tuple[str, str, str, str | None], int] = {}
        for warning in warnings:
            key = (
                warning.source_path,
                warning.code,
                warning.message,
                warning.expression,
            )
            grouped[key] = grouped.get(key, 0) + 1
        return [
            TableRelationWarningRecord(
                project_id=database.project_id,
                project_name=database.project_name,
                database_key=database.mcp_alias,
                source_path=source_path,
                code=code,
                message=message,
                expression=expression,
                occurrence_count=count,
            )
            for (source_path, code, message, expression), count in sorted(
                grouped.items(), key=lambda item: (*item[0][:3], item[0][3] or "")
            )
        ]

    @classmethod
    def _warning_label(cls, code: str) -> str:
        return cls._WARNING_LABELS.get(code, "其他未采集原因")

    @classmethod
    def _warning_classification(cls, code: str) -> str:
        return cls._WARNING_CLASSIFICATIONS.get(code, "source_error")

    @classmethod
    def _warning_disposition(cls, code: str) -> TableRelationWarningDisposition:
        if cls._WARNING_CLASSIFICATIONS.get(code) == "safe_skip":
            return "expected"
        return "attention"

    @classmethod
    def _warning_preview(cls, warning: TableRelationWarningRecord) -> str:
        suffix = f"（{warning.occurrence_count} 次）" if warning.occurrence_count > 1 else ""
        return (
            f"{warning.source_path}: {cls._warning_label(warning.code)}: {warning.message}{suffix}"
        )[:1000]

    @staticmethod
    def _relation_identities(
        relation: TableJoinRelationRecord,
    ) -> tuple[TableIdentity, TableIdentity]:
        common = {
            "project_id": relation.project_id,
            "project_name": relation.project_name,
            "database_key": relation.database_key,
        }
        return (
            TableIdentity(
                **common,
                schema_name=relation.table_a_schema,
                table_name=relation.table_a_name,
            ),
            TableIdentity(
                **common,
                schema_name=relation.table_b_schema,
                table_name=relation.table_b_name,
            ),
        )

    @staticmethod
    def _identity_key(identity: TableIdentity) -> tuple[str, str, str, str]:
        return (
            identity.project_id,
            identity.database_key.casefold(),
            identity.schema_name.casefold(),
            identity.table_name.casefold(),
        )

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, TableRelationRepositoryError | TableRelationServiceError):
            return str(exc)[:500]
        if isinstance(exc, ConnectorManagerError):
            return f"{exc.code}: {exc}"[:500]
        if isinstance(exc, DatabaseConnectorError):
            return f"{exc.code}: {exc}"[:500]
        return "SQL表关联扫描或元数据校验失败"
