from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from context_router.services.sql_preprocessing import (
    SqlPreprocessorPipeline,
    SqlPreprocessProfile,
)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True, slots=True)
class SqlSource:
    workspace_id: str
    project_id: str
    project_name: str
    database_key: str
    dialect: str
    source_path: str
    statement: str


@dataclass(frozen=True, slots=True)
class ResolvedColumn:
    project_id: str
    project_name: str
    database_key: str
    schema_name: str
    table_name: str
    column_name: str

    @property
    def table_key(self) -> tuple[str, str, str, str]:
        return (
            self.project_id,
            self.database_key.casefold(),
            self.schema_name.casefold(),
            self.table_name.casefold(),
        )

    @property
    def qualified_key(self) -> tuple[str, str, str, str, str]:
        return (*self.table_key, self.column_name.casefold())


@dataclass(frozen=True, slots=True)
class ObservedJoinFact:
    left: ResolvedColumn
    right: ResolvedColumn
    source_path: str
    join_expression: str
    sql_statement: str
    preprocess_profile_id: str | None = None
    preprocess_profile_hash: str | None = None
    preprocess_candidate_id: str | None = None
    applied_rules: tuple[str, ...] = ()
    template_derived: bool = False


@dataclass(frozen=True, slots=True)
class AnalyzerWarning:
    source_path: str
    code: str
    message: str
    expression: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataColumnResolution:
    resolved: tuple[str, str, str] | None
    failure: str | None = None


@dataclass(frozen=True, slots=True)
class ColumnResolutionFailure:
    kind: str
    qualifier: str | None
    table_name: str | None
    column_name: str


class SqlMetadataProvider(Protocol):
    def resolve_column(
        self,
        *,
        database_key: str,
        schema_name: str | None,
        table_name: str,
        column_name: str,
    ) -> tuple[str, str, str] | None: ...

    def resolve_column_detailed(
        self,
        *,
        database_key: str,
        schema_name: str | None,
        table_name: str,
        column_name: str,
    ) -> MetadataColumnResolution: ...


class SqlFileCollector:
    _SKIPPED_DIRECTORIES = frozenset(
        {
            ".git",
            ".idea",
            ".next",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "build",
            "dist",
            "node_modules",
            "target",
            "vendor",
        }
    )

    def collect(
        self,
        *,
        workspace_id: str,
        project_id: str,
        project_name: str,
        project_root: Path,
        database_key: str,
        dialect: str,
    ) -> list[SqlSource]:
        sources: list[SqlSource] = []
        sql_paths: list[Path] = []
        for directory, directory_names, file_names in project_root.walk():
            directory_names[:] = sorted(
                name for name in directory_names if name.casefold() not in self._SKIPPED_DIRECTORIES
            )
            sql_paths.extend(
                directory / name for name in sorted(file_names) if name.endswith(".sql")
            )
        for path in sorted(sql_paths):
            if not path.is_file():
                continue
            try:
                statement = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if not statement.strip():
                continue
            sources.append(
                SqlSource(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    project_name=project_name,
                    database_key=database_key,
                    dialect=dialect,
                    source_path=path.relative_to(project_root).as_posix(),
                    statement=statement,
                )
            )
        return sources


class SqlAutomaticWhitelist:
    """Recognize SQL files that cannot contribute cross-table equality joins.

    Classification is deliberately fail-closed: a file is skipped only when
    every parsed statement belongs to one of the explicit safe categories.
    Template fragments or parse failures remain eligible for the normal
    preprocessor/analyzer pipeline.
    """

    _DDL_KEYS = frozenset(
        {
            "alter",
            "comment",
            "create",
            "drop",
            "grant",
            "rename",
            "revoke",
            "truncate",
            "truncatetable",
        }
    )
    _QUERY_KEYS = frozenset({"except", "intersect", "select", "union"})
    _WRITE_KEYS = frozenset({"insert", "update"})

    def classify(self, source: SqlSource) -> str | None:
        normalized, template_removed = SqlObservedJoinAnalyzer._normalize_statement(
            source.statement
        )
        if template_removed:
            return None
        try:
            statements = [
                statement
                for statement in sqlglot.parse(normalized, read=source.dialect)
                if isinstance(statement, exp.Expression)
            ]
        except (ParseError, ValueError):
            return None
        if not statements:
            return None
        reasons = [self._statement_reason(statement) for statement in statements]
        if any(reason is None for reason in reasons):
            return None
        unique = set(reasons)
        return next(iter(unique)) if len(unique) == 1 else "automatic_safe_mixed"

    def _statement_reason(self, statement: exp.Expression) -> str | None:
        if statement.key in self._DDL_KEYS:
            return "automatic_ddl"
        if statement.key in self._QUERY_KEYS and self._is_single_table_query(statement):
            return "automatic_single_table_query"
        if statement.key in self._WRITE_KEYS and self._is_write_without_query(statement):
            return "automatic_write_without_query"
        return None

    @staticmethod
    def _physical_tables(statement: exp.Expression) -> set[str]:
        cte_names = {
            cte.alias_or_name.casefold() for cte in statement.find_all(exp.CTE) if cte.alias_or_name
        }
        return {
            table.name.casefold()
            for table in statement.find_all(exp.Table)
            if table.name and table.name.casefold() not in cte_names
        }

    def _is_single_table_query(self, statement: exp.Expression) -> bool:
        if statement.find(exp.Join) is not None:
            return False
        return len(self._physical_tables(statement)) == 1

    def _is_write_without_query(self, statement: exp.Expression) -> bool:
        if statement.find(exp.Join) is not None:
            return False
        if any(
            nested is not statement and nested.key in self._QUERY_KEYS
            for nested in statement.walk()
        ):
            return False
        return len(self._physical_tables(statement)) <= 1


class SqlObservedJoinAnalyzer:
    """Extract only unambiguous cross-table equality joins.

    The analyzer intentionally does not infer foreign keys, ownership, or data
    flow. Unsupported or ambiguous expressions become warnings and never edges.
    """

    def __init__(self, preprocessor: SqlPreprocessorPipeline | None = None) -> None:
        self._preprocessor = preprocessor or SqlPreprocessorPipeline()

    def analyze(
        self,
        source: SqlSource,
        metadata: SqlMetadataProvider,
        profile: SqlPreprocessProfile | None = None,
    ) -> tuple[list[ObservedJoinFact], list[AnalyzerWarning], int]:
        if profile is None:
            return self._analyze_candidate(source, metadata)
        result = self._preprocessor.process(source.statement, profile)
        warnings = [
            self._warning(source, item.code, item.message, item.expression)
            for item in result.diagnostics
        ]
        facts: list[ObservedJoinFact] = []
        statement_count = 0
        for candidate in result.candidates:
            candidate_facts, candidate_warnings, parsed_count = self._analyze_candidate(
                replace(source, statement=candidate.sql),
                metadata,
                parse_warning_code="template_candidate_parse_failed",
            )
            facts.extend(
                replace(
                    fact,
                    preprocess_profile_id=result.profile_id,
                    preprocess_profile_hash=result.profile_hash,
                    preprocess_candidate_id=candidate.candidate_id,
                    applied_rules=candidate.applied_rules,
                    template_derived=candidate.template_derived,
                )
                for fact in candidate_facts
            )
            warnings.extend(candidate_warnings)
            statement_count += parsed_count
        if result.candidates and statement_count == 0:
            warnings.append(
                self._warning(
                    source,
                    "source_sql_invalid",
                    "所有有界模板候选均无法形成有效 SQL，请检查源文件或补充工作空间预处理规则",
                )
            )
        return facts, warnings, statement_count

    def _analyze_candidate(
        self,
        source: SqlSource,
        metadata: SqlMetadataProvider,
        *,
        parse_warning_code: str = "sql_parse_failed",
    ) -> tuple[list[ObservedJoinFact], list[AnalyzerWarning], int]:
        normalized_statement, template_removed = self._normalize_statement(source.statement)
        warnings: list[AnalyzerWarning] = []
        if template_removed:
            warnings.append(
                self._warning(
                    source,
                    "sql_template_fragment_ignored",
                    "已忽略 <<...>> 动态模板块，只分析块外静态 SQL",
                )
            )
        try:
            statements = [
                statement
                for statement in sqlglot.parse(normalized_statement, read=source.dialect)
                if isinstance(statement, exp.Expression)
            ]
        except (ParseError, ValueError) as exc:
            warnings.append(self._warning(source, parse_warning_code, str(exc)))
            return [], warnings, 0

        facts: list[ObservedJoinFact] = []
        for statement in statements:
            for join in statement.find_all(exp.Join):
                if self._unsupported_join(join):
                    continue
                scope = self._query_scope(join)
                query_scope = scope or statement
                aliases = self._aliases(query_scope)
                derived_aliases = self._derived_aliases(query_scope)
                outer_aliases = self._outer_aliases(query_scope)
                condition = join.args.get("on")
                if condition is None:
                    using_facts, using_warnings = self._using_facts(
                        source=source,
                        statement=statement,
                        join=join,
                        aliases=aliases,
                        derived_aliases=derived_aliases,
                        outer_aliases=outer_aliases,
                        metadata=metadata,
                    )
                    facts.extend(using_facts)
                    warnings.extend(using_warnings)
                    continue
                for group in self._and_groups(condition):
                    if isinstance(group, exp.Or) or group.find(exp.Or) is not None:
                        if self._contains_cross_table_predicate(group):
                            warnings.append(
                                self._warning(
                                    source,
                                    "join_or_unsupported",
                                    "包含 OR 的局部跨表条件无法安全拆分，已跳过该分组",
                                    group.sql(dialect=source.dialect),
                                )
                            )
                        continue
                    equality = group if isinstance(group, exp.EQ) else None
                    if equality is None:
                        if len(list(group.find_all(exp.Column))) >= 2:
                            warnings.append(
                                self._warning(
                                    source,
                                    "join_non_equality_ignored",
                                    "跨字段条件不是直接等值表达式，第一版不建立关系",
                                    group.sql(dialect=source.dialect),
                                )
                            )
                        continue
                    left_expression = equality.this
                    right_expression = equality.expression
                    if not isinstance(left_expression, exp.Column) or not isinstance(
                        right_expression, exp.Column
                    ):
                        continue
                    left, left_failure = self._resolve_detailed(
                        source=source,
                        column=left_expression,
                        aliases=aliases,
                        derived_aliases=derived_aliases,
                        outer_aliases=outer_aliases,
                        metadata=metadata,
                    )
                    right, right_failure = self._resolve_detailed(
                        source=source,
                        column=right_expression,
                        aliases=aliases,
                        derived_aliases=derived_aliases,
                        outer_aliases=outer_aliases,
                        metadata=metadata,
                    )
                    if left is None or right is None:
                        warnings.extend(
                            self._warning(
                                source,
                                warning_code,
                                warning_message,
                                equality.sql(dialect=source.dialect),
                            )
                            for warning_code, warning_message in self._resolution_warnings(
                                source,
                                left_failure,
                                right_failure,
                            )
                        )
                        continue
                    if left.table_key == right.table_key:
                        continue
                    facts.append(
                        ObservedJoinFact(
                            left=left,
                            right=right,
                            source_path=source.source_path,
                            join_expression=equality.sql(dialect=source.dialect),
                            sql_statement=statement.sql(dialect=source.dialect),
                        )
                    )
            aliases = self._aliases(statement)
            where = statement.args.get("where")
            if isinstance(where, exp.Where):
                for equality in where.this.find_all(exp.EQ):
                    left_expression = equality.this
                    right_expression = equality.expression
                    if not isinstance(left_expression, exp.Column) or not isinstance(
                        right_expression, exp.Column
                    ):
                        continue
                    left = self._resolve(
                        source=source,
                        column=left_expression,
                        aliases=aliases,
                        metadata=metadata,
                    )
                    right = self._resolve(
                        source=source,
                        column=right_expression,
                        aliases=aliases,
                        metadata=metadata,
                    )
                    if left is None or right is None or left.table_key == right.table_key:
                        continue
                    warnings.append(
                        self._warning(
                            source,
                            "where_relation_unsupported",
                            "WHERE 中出现跨表字段等值条件，第一版仅记录诊断、不建立关系",
                            equality.sql(dialect=source.dialect),
                        )
                    )
        return facts, warnings, len(statements)

    @staticmethod
    def _normalize_statement(statement: str) -> tuple[str, bool]:
        normalized, count = re.subn(r"<<.*?>>", " ", statement, flags=re.DOTALL)
        return normalized, count > 0

    def _using_facts(
        self,
        *,
        source: SqlSource,
        statement: exp.Expression,
        join: exp.Join,
        aliases: dict[str, tuple[str | None, str]],
        derived_aliases: set[str],
        outer_aliases: set[str],
        metadata: SqlMetadataProvider,
    ) -> tuple[list[ObservedJoinFact], list[AnalyzerWarning]]:
        using = join.args.get("using")
        if not isinstance(using, list) or not using:
            return [], []
        parent = join.parent
        while parent is not None and not isinstance(parent, exp.Select):
            parent = parent.parent
        if not isinstance(parent, exp.Select):
            return [], [self._warning(source, "join_using_unresolved", "JOIN USING 左侧表无法确认")]
        joins = list(parent.args.get("joins") or [])
        try:
            position = joins.index(join)
        except ValueError:
            return [], [self._warning(source, "join_using_unresolved", "JOIN USING 顺序无法确认")]
        if position > 0:
            return [], [
                self._warning(
                    source,
                    "join_using_unresolved",
                    "多表 JOIN USING 的左侧字段归属不唯一，第一版不建立关系",
                    ", ".join(item.name for item in using if isinstance(item, exp.Identifier)),
                )
            ]
        from_clause = parent.args.get("from_")
        left_expression = from_clause.this if isinstance(from_clause, exp.From) else None
        right_expression = join.this
        if not isinstance(left_expression, exp.Table) or not isinstance(
            right_expression, exp.Table
        ):
            return [], [
                self._warning(
                    source,
                    "join_derived_relation_unsupported",
                    "JOIN USING 涉及子查询或派生表，第一版不建立关系",
                    join.sql(dialect=source.dialect),
                )
            ]
        left_qualifier = left_expression.alias_or_name
        right_qualifier = right_expression.alias_or_name
        facts: list[ObservedJoinFact] = []
        warnings: list[AnalyzerWarning] = []
        for identifier in using:
            column_name = identifier.name if isinstance(identifier, exp.Identifier) else ""
            if not column_name:
                continue
            left_column = exp.column(column_name, table=left_qualifier)
            right_column = exp.column(column_name, table=right_qualifier)
            left, left_failure = self._resolve_detailed(
                source=source,
                column=left_column,
                aliases=aliases,
                derived_aliases=derived_aliases,
                outer_aliases=outer_aliases,
                metadata=metadata,
            )
            right, right_failure = self._resolve_detailed(
                source=source,
                column=right_column,
                aliases=aliases,
                derived_aliases=derived_aliases,
                outer_aliases=outer_aliases,
                metadata=metadata,
            )
            equality = exp.EQ(this=left_column, expression=right_column)
            if left is None or right is None:
                warnings.extend(
                    self._warning(
                        source,
                        warning_code,
                        warning_message,
                        column_name,
                    )
                    for warning_code, warning_message in self._resolution_warnings(
                        source,
                        left_failure,
                        right_failure,
                    )
                )
                continue
            if left.table_key == right.table_key:
                continue
            facts.append(
                ObservedJoinFact(
                    left=left,
                    right=right,
                    source_path=source.source_path,
                    join_expression=equality.sql(dialect=source.dialect),
                    sql_statement=statement.sql(dialect=source.dialect),
                )
            )
        return facts, warnings

    @classmethod
    def _aliases(cls, scope: exp.Expression) -> dict[str, tuple[str | None, str]]:
        aliases: dict[str, tuple[str | None, str]] = {}
        for table in scope.find_all(exp.Table):
            if cls._query_scope(table) is not scope:
                continue
            if isinstance(table.parent, exp.Delete) and table in (
                table.parent.args.get("tables") or []
            ):
                continue
            table_name = table.name
            if not table_name:
                continue
            schema_name = table.db or None
            keys = {table_name.casefold()}
            if table.alias:
                keys.add(table.alias.casefold())
            for key in keys:
                existing = aliases.get(key)
                identity = (schema_name, table_name)
                aliases[key] = identity if existing in {None, identity} else (None, "")
        return aliases

    @classmethod
    def _derived_aliases(cls, scope: exp.Expression) -> set[str]:
        """Return aliases backed by CTEs or subqueries in the current query scope.

        These aliases are intentionally kept outside physical table metadata
        resolution. Treating them as missing database tables makes an expected
        first-version boundary look like a database configuration error.
        """

        cte_names: set[str] = set()
        current: exp.Expression | None = scope
        while current is not None:
            with_clause = current.args.get("with_")
            if isinstance(with_clause, exp.With):
                cte_names.update(
                    cte.alias_or_name.casefold()
                    for cte in with_clause.expressions
                    if isinstance(cte, exp.CTE) and cte.alias_or_name
                )
            current = cls._query_scope(current)

        aliases: set[str] = set()
        for table in scope.find_all(exp.Table):
            if cls._query_scope(table) is not scope or table.name.casefold() not in cte_names:
                continue
            aliases.add(table.name.casefold())
            if table.alias:
                aliases.add(table.alias.casefold())
        for subquery in scope.find_all(exp.Subquery):
            if cls._query_scope(subquery) is scope and subquery.alias:
                aliases.add(subquery.alias.casefold())
        return aliases

    @classmethod
    def _outer_aliases(cls, scope: exp.Expression) -> set[str]:
        aliases: set[str] = set()
        current = cls._query_scope(scope)
        while current is not None:
            aliases.update(cls._aliases(current))
            current = cls._query_scope(current)
        return aliases

    @staticmethod
    def _query_scope(expression: exp.Expression) -> exp.Expression | None:
        current = expression.parent
        while current is not None:
            if isinstance(current, (exp.Select, exp.Update, exp.Delete)):
                return current
            current = current.parent
        return None

    @staticmethod
    def _unsupported_join(join: exp.Join) -> bool:
        kind = str(join.args.get("kind") or "").casefold()
        method = str(join.args.get("method") or "").casefold()
        return kind == "cross" or method == "natural"

    @classmethod
    def _and_groups(cls, expression: exp.Expression) -> list[exp.Expression]:
        if isinstance(expression, exp.Paren):
            return cls._and_groups(expression.this)
        if isinstance(expression, exp.And):
            return [*cls._and_groups(expression.this), *cls._and_groups(expression.expression)]
        return [expression]

    @classmethod
    def _contains_cross_table_predicate(cls, expression: exp.Expression) -> bool:
        if isinstance(expression, exp.Paren):
            return cls._contains_cross_table_predicate(expression.this)
        if isinstance(expression, (exp.And, exp.Or)):
            return cls._contains_cross_table_predicate(
                expression.this
            ) or cls._contains_cross_table_predicate(expression.expression)
        qualifiers = {
            column.table.casefold() for column in expression.find_all(exp.Column) if column.table
        }
        return len(qualifiers) > 1

    @staticmethod
    def _resolve(
        *,
        source: SqlSource,
        column: exp.Column,
        aliases: dict[str, tuple[str | None, str]],
        metadata: SqlMetadataProvider,
    ) -> ResolvedColumn | None:
        resolved, _ = SqlObservedJoinAnalyzer._resolve_detailed(
            source=source,
            column=column,
            aliases=aliases,
            derived_aliases=set(),
            outer_aliases=set(),
            metadata=metadata,
        )
        return resolved

    @staticmethod
    def _resolve_detailed(
        *,
        source: SqlSource,
        column: exp.Column,
        aliases: dict[str, tuple[str | None, str]],
        derived_aliases: set[str],
        outer_aliases: set[str],
        metadata: SqlMetadataProvider,
    ) -> tuple[ResolvedColumn | None, ColumnResolutionFailure | None]:
        qualifier = column.table
        if not qualifier:
            return None, ColumnResolutionFailure(
                kind="unqualified",
                qualifier=None,
                table_name=None,
                column_name=column.name,
            )
        normalized_qualifier = qualifier.casefold()
        if normalized_qualifier in derived_aliases:
            return None, ColumnResolutionFailure(
                kind="derived",
                qualifier=qualifier,
                table_name=None,
                column_name=column.name,
            )
        identity = aliases.get(normalized_qualifier)
        if identity is None:
            if normalized_qualifier in outer_aliases:
                return None, ColumnResolutionFailure(
                    kind="correlated",
                    qualifier=qualifier,
                    table_name=None,
                    column_name=column.name,
                )
            return None, ColumnResolutionFailure(
                kind="unknown_alias",
                qualifier=qualifier,
                table_name=None,
                column_name=column.name,
            )
        if not identity[1]:
            return None, ColumnResolutionFailure(
                kind="ambiguous_alias",
                qualifier=qualifier,
                table_name=None,
                column_name=column.name,
            )
        schema_name, table_name = identity
        detailed_resolver = getattr(metadata, "resolve_column_detailed", None)
        if callable(detailed_resolver):
            metadata_resolution = detailed_resolver(
                database_key=source.database_key,
                schema_name=schema_name,
                table_name=table_name,
                column_name=column.name,
            )
            resolved = metadata_resolution.resolved
            metadata_failure = metadata_resolution.failure or "metadata"
        else:  # pragma: no cover - compatibility for third-party providers
            resolved = metadata.resolve_column(
                database_key=source.database_key,
                schema_name=schema_name,
                table_name=table_name,
                column_name=column.name,
            )
            metadata_failure = "metadata"
        if resolved is None:
            return None, ColumnResolutionFailure(
                kind=metadata_failure,
                qualifier=qualifier,
                table_name=table_name,
                column_name=column.name,
            )
        resolved_schema, resolved_table, resolved_column = resolved
        return (
            ResolvedColumn(
                project_id=source.project_id,
                project_name=source.project_name,
                database_key=source.database_key,
                schema_name=resolved_schema,
                table_name=resolved_table,
                column_name=resolved_column,
            ),
            None,
        )

    @staticmethod
    def _resolution_warnings(
        source: SqlSource,
        *failures: ColumnResolutionFailure | None,
    ) -> list[tuple[str, str]]:
        failure_items = [failure for failure in failures if failure is not None]
        failure_kinds = {failure.kind for failure in failure_items}
        expected_boundaries = (
            (
                "derived",
                "join_derived_relation_unsupported",
                "JOIN 涉及 CTE 或派生表字段，第一版不跨派生边界建立物理表关系",
            ),
            (
                "unqualified",
                "join_unqualified_column_unsupported",
                "JOIN 字段未限定表别名，无法安全确认字段归属",
            ),
            (
                "correlated",
                "join_correlated_reference_unsupported",
                "JOIN 条件引用外层查询字段，第一版不跨相关子查询作用域建立关系",
            ),
        )
        for kind, code, message in expected_boundaries:
            if kind in failure_kinds:
                return [(code, message)]

        warnings: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for failure in failure_items:
            qualifier = failure.qualifier or "<未限定>"
            field = f"{qualifier}.{failure.column_name}"
            if failure.kind == "ambiguous_alias":
                item = (
                    "join_alias_ambiguous",
                    f"JOIN 表别名 {qualifier} 在当前查询作用域内不唯一（字段 {field}）",
                )
            elif failure.kind == "unknown_alias":
                item = (
                    "join_alias_unresolved",
                    f"JOIN 表别名 {qualifier} 无法在当前查询作用域确认（字段 {field}）",
                )
            elif failure.kind == "table_not_found":
                item = (
                    "join_metadata_table_not_found",
                    f"默认数据库 {source.database_key} 中未找到表 "
                    f"{failure.table_name}（字段 {field}）",
                )
            elif failure.kind == "table_ambiguous":
                item = (
                    "join_metadata_table_ambiguous",
                    f"默认数据库 {source.database_key} 中表 {failure.table_name} "
                    f"无法唯一确认（字段 {field}）",
                )
            elif failure.kind == "column_not_found":
                item = (
                    "join_metadata_column_not_found",
                    f"默认数据库 {source.database_key} 的表 {failure.table_name} 中未找到字段 "
                    f"{failure.column_name}",
                )
            elif failure.kind == "column_ambiguous":
                item = (
                    "join_metadata_column_ambiguous",
                    f"默认数据库 {source.database_key} 的表 {failure.table_name} 中字段 "
                    f"{failure.column_name} 无法唯一确认",
                )
            else:
                item = (
                    "join_metadata_unresolved",
                    f"默认数据库 {source.database_key} 无法确认表 {failure.table_name} 的字段 "
                    f"{failure.column_name}",
                )
            if item not in seen:
                warnings.append(item)
                seen.add(item)
        return warnings or [
            (
                "join_metadata_unresolved",
                f"默认数据库 {source.database_key} 无法确认 JOIN 物理表或字段",
            )
        ]

    @staticmethod
    def _warning(
        source: SqlSource,
        code: str,
        message: str,
        expression: str | None = None,
    ) -> AnalyzerWarning:
        clean_message = _ANSI_ESCAPE_RE.sub("", message)
        return AnalyzerWarning(
            source_path=source.source_path,
            code=code,
            message=clean_message[:500],
            expression=expression[:1000] if expression else None,
        )
