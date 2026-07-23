from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import expressions as exp
from sqlglot.errors import ParseError, TokenError
from sqlglot.tokens import Tokenizer

from .models import EffectiveQueryPolicy

_DIALECTS = {
    "clickhouse": "clickhouse",
    "mariadb": "mysql",
    "mysql": "mysql",
    "oracle": "oracle",
    "postgresql": "postgres",
    "sqlite": "sqlite",
    "sqlserver": "tsql",
}

_ALLOWED_ROOT_TYPES = {
    "Describe",
    "Exists",
    "Explain",
    "Show",
}

_FORBIDDEN_EXPRESSION_TYPES = {
    "Alter",
    "Analyze",
    "Attach",
    "Backup",
    "Call",
    "Command",
    "Commit",
    "Copy",
    "Create",
    "Delete",
    "Detach",
    "Drop",
    "Execute",
    "Export",
    "Format",
    "Grant",
    "Insert",
    "Into",
    "Kill",
    "LoadData",
    "Lock",
    "Merge",
    "Optimize",
    "Pragma",
    "Rename",
    "Restore",
    "Revoke",
    "Rollback",
    "Set",
    "Settings",
    "System",
    "Transaction",
    "TruncateTable",
    "Unlock",
    "Update",
    "Use",
}

_SYSTEM_NAMESPACES = {
    "information_schema",
    "mysql",
    "performance_schema",
    "pg_catalog",
    "sys",
    "system",
}

_EXTERNAL_FUNCTIONS = {
    "azureblobstorage",
    "file",
    "hdfs",
    "jdbc",
    "load_file",
    "lo_export",
    "lo_import",
    "mongodb",
    "mysql",
    "odbc",
    "opendatasource",
    "openrowset",
    "pg_ls_dir",
    "pg_read_binary_file",
    "pg_read_file",
    "postgresql",
    "readfile",
    "remote",
    "remotesecure",
    "s3",
    "s3cluster",
    "sqlite",
    "url",
    "writefile",
}


class QueryPolicyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class QueryPolicyHardLimits:
    max_rows: int = 5_000
    max_result_bytes: int = 4_000_000
    max_query_timeout_ms: int = 30_000

    def __post_init__(self) -> None:
        if min(self.max_rows, self.max_result_bytes, self.max_query_timeout_ms) < 1:
            raise ValueError("query hard limits must be positive")


@dataclass(frozen=True, slots=True)
class SqlSafetyContext:
    engine: str
    database: str
    allowed_schemas: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_engine = self.engine.strip().lower()
        if normalized_engine not in _DIALECTS:
            raise QueryPolicyError(
                "engine_not_supported",
                f"SQL validation is not supported for engine: {normalized_engine}",
            )
        if not self.database.strip():
            raise ValueError("database must not be empty")
        object.__setattr__(self, "engine", normalized_engine)
        object.__setattr__(
            self,
            "allowed_schemas",
            tuple(schema.strip() for schema in self.allowed_schemas if schema.strip()),
        )


@dataclass(frozen=True, slots=True)
class ValidatedQuery:
    sql: str
    statement_type: str


def build_effective_policy(
    *,
    engine: str,
    current_database: str,
    readonly: bool,
    allowed_schemas: list[str] | tuple[str, ...],
    max_rows: int,
    max_result_bytes: int,
    query_timeout_ms: int,
    hard_limits: QueryPolicyHardLimits | None = None,
) -> EffectiveQueryPolicy:
    limits = hard_limits or QueryPolicyHardLimits()
    if not readonly:
        raise QueryPolicyError(
            "query_rejected",
            "database MCP access requires a read-only project policy",
        )
    if min(max_rows, max_result_bytes, query_timeout_ms) < 1:
        raise QueryPolicyError("query_rejected", "database query limits must be positive")
    return EffectiveQueryPolicy(
        engine=engine,
        current_database=current_database,
        readonly=True,
        allowed_schemas=tuple(allowed_schemas),
        max_rows=min(max_rows, limits.max_rows),
        max_result_bytes=min(max_result_bytes, limits.max_result_bytes),
        query_timeout_ms=min(query_timeout_ms, limits.max_query_timeout_ms),
    )


class SqlSafetyPolicy:
    def validate(self, sql: str, context: SqlSafetyContext) -> ValidatedQuery:
        statement = sql.strip()
        if not statement:
            raise QueryPolicyError("query_rejected", "SQL must not be empty")

        try:
            tokens = Tokenizer(dialect=_DIALECTS[context.engine]).tokenize(statement)
        except (TokenError, ValueError):
            raise QueryPolicyError(
                "query_rejected",
                "SQL could not be tokenized safely; simplify the read-only query",
            ) from None
        if tokens:
            first_token = tokens[0]
            first_keyword = first_token.text.strip().upper()
            if first_keyword in {"EXPLAIN", "SHOW"}:
                payload = tokens[1].text.strip() if len(tokens) == 2 else ""
                return self._validate_supported_command(
                    statement,
                    command=first_keyword,
                    payload=payload,
                    context=context,
                )
            if first_token.token_type.name == "COMMAND":
                raise QueryPolicyError(
                    "query_rejected",
                    "unsupported SQL commands are not allowed",
                )

        try:
            parsed = sqlglot.parse(statement, read=_DIALECTS[context.engine])
        except (ParseError, ValueError):
            raise QueryPolicyError(
                "query_rejected",
                "SQL could not be parsed safely; simplify the read-only query",
            ) from None

        expressions = [expression for expression in parsed if expression is not None]
        if len(expressions) != 1:
            raise QueryPolicyError(
                "query_rejected",
                "exactly one read-only SQL statement is required",
            )
        expression = expressions[0]
        if expression.__class__.__name__ == "Command":
            command = str(expression.args.get("this") or "").strip().upper()
            payload_expression = expression.args.get("expression")
            payload = (
                str(payload_expression.this).strip()
                if isinstance(payload_expression, exp.Literal)
                else ""
            )
            return self._validate_supported_command(
                statement,
                command=command,
                payload=payload,
                context=context,
            )
        self._validate_root(expression)
        self._reject_forbidden_nodes(expression)
        self._reject_table_functions(expression)
        self._validate_table_scope(expression, context)
        return ValidatedQuery(
            sql=statement,
            statement_type=self._statement_type(expression),
        )

    def _validate_supported_command(
        self,
        statement: str,
        *,
        command: str,
        payload: str,
        context: SqlSafetyContext,
    ) -> ValidatedQuery:
        if command == "EXPLAIN" and payload:
            try:
                inner_statements = sqlglot.parse(payload, read=_DIALECTS[context.engine])
            except (ParseError, ValueError):
                raise QueryPolicyError(
                    "query_rejected",
                    "EXPLAIN must contain one safely parseable SELECT query",
                ) from None
            inner = [item for item in inner_statements if item is not None]
            if len(inner) != 1 or not isinstance(inner[0], exp.Query):
                raise QueryPolicyError(
                    "query_rejected",
                    "EXPLAIN must contain one SELECT query",
                )
            self._reject_forbidden_nodes(inner[0])
            self._reject_table_functions(inner[0])
            self._validate_table_scope(inner[0], context)
            return ValidatedQuery(sql=statement, statement_type="EXPLAIN")

        if command == "SHOW":
            try:
                show_statements = sqlglot.parse(statement, read="mysql")
            except (ParseError, ValueError):
                raise QueryPolicyError(
                    "query_rejected",
                    "SHOW statement could not be parsed safely",
                ) from None
            parsed_show = [item for item in show_statements if item is not None]
            if len(parsed_show) != 1 or parsed_show[0].__class__.__name__ != "Show":
                raise QueryPolicyError(
                    "query_rejected",
                    "SHOW statement is not supported",
                )
            show = parsed_show[0]
            show_kind = str(show.args.get("this") or "").strip().upper()
            if show_kind not in {"COLUMNS", "CREATE TABLE", "TABLES"}:
                raise QueryPolicyError(
                    "query_rejected",
                    "only SHOW TABLES, SHOW COLUMNS, and SHOW CREATE TABLE are allowed",
                )
            self._reject_forbidden_nodes(show)
            show_database = show.args.get("db")
            if (
                show_database is not None
                and show_database.name.casefold() != context.database.casefold()
            ):
                raise QueryPolicyError(
                    "query_rejected",
                    "cross-database SHOW statements are not allowed",
                )
            return ValidatedQuery(sql=statement, statement_type="SHOW")

        raise QueryPolicyError(
            "query_rejected",
            "only safely parsed read-only SQL statements are allowed",
        )

    @staticmethod
    def _validate_root(expression: exp.Expression) -> None:
        if isinstance(expression, exp.Query):
            return
        if expression.__class__.__name__ in _ALLOWED_ROOT_TYPES:
            return
        raise QueryPolicyError(
            "query_rejected",
            "only a single read-only SELECT, SHOW, DESCRIBE, EXPLAIN, or EXISTS is allowed",
        )

    @staticmethod
    def _reject_forbidden_nodes(expression: exp.Expression) -> None:
        for node in expression.walk():
            node_type = node.__class__.__name__
            if node_type in _FORBIDDEN_EXPRESSION_TYPES:
                raise QueryPolicyError(
                    "query_rejected",
                    f"SQL contains a forbidden operation: {node_type.upper()}",
                )

            # SQLGlot represents some dialect-specific FORMAT/SETTINGS clauses as
            # query arguments rather than standalone expression classes.
            if any(
                value is not None
                for key, value in node.args.items()
                if key.lower()
                in {
                    "format",
                    "into",
                    "into_outfile",
                    "outfile",
                    "settings",
                }
            ):
                raise QueryPolicyError(
                    "query_rejected",
                    "SQL FORMAT, INTO, and SETTINGS clauses are not allowed",
                )

    def _reject_table_functions(self, expression: exp.Expression) -> None:
        for table in expression.find_all(exp.Table):
            target = table.this
            if isinstance(target, exp.Func):
                raise QueryPolicyError(
                    "query_rejected",
                    "table functions are not allowed",
                )

        # Explicitly reject external-access functions wherever the dialect parser
        # places them. This covers engines that model a table function without a
        # surrounding Table node.
        for function in expression.find_all(exp.Func):
            name = self._function_name(function)
            if name.casefold() in _EXTERNAL_FUNCTIONS:
                raise QueryPolicyError(
                    "query_rejected",
                    "external database, file, and network functions are not allowed",
                )

    @staticmethod
    def _validate_table_scope(expression: exp.Expression, context: SqlSafetyContext) -> None:
        cte_names = {
            cte.alias_or_name.casefold()
            for cte in expression.find_all(exp.CTE)
            if cte.alias_or_name
        }
        allowed_schemas = {schema.casefold() for schema in context.allowed_schemas}
        current_database = context.database.casefold()

        for table in expression.find_all(exp.Table):
            table_name = table.name
            database_name = table.catalog
            namespace = table.db
            if not database_name and not namespace and table_name.casefold() in cte_names:
                continue

            if database_name and database_name.casefold() != current_database:
                raise QueryPolicyError(
                    "query_rejected",
                    "cross-database table references are not allowed",
                )

            if context.engine in {"mysql", "mariadb", "clickhouse"}:
                if namespace and namespace.casefold() != current_database:
                    raise QueryPolicyError(
                        "query_rejected",
                        "cross-database table references are not allowed",
                    )
                if namespace and namespace.casefold() in _SYSTEM_NAMESPACES:
                    raise QueryPolicyError(
                        "query_rejected",
                        "system catalogs are only available through object search",
                    )
                continue

            if namespace and namespace.casefold() in _SYSTEM_NAMESPACES:
                raise QueryPolicyError(
                    "query_rejected",
                    "system catalogs are only available through object search",
                )
            if namespace and allowed_schemas and namespace.casefold() not in allowed_schemas:
                raise QueryPolicyError(
                    "query_rejected",
                    "table schema is outside the project's allowed schema list",
                )

    @staticmethod
    def _function_name(function: exp.Func) -> str:
        if isinstance(function, exp.Anonymous):
            return function.name
        sql_name = getattr(function, "sql_name", None)
        if callable(sql_name):
            return str(sql_name())
        return function.__class__.__name__

    @staticmethod
    def _statement_type(expression: exp.Expression) -> str:
        name = expression.__class__.__name__
        if name == "Describe" and isinstance(expression.args.get("this"), exp.Query):
            return "EXPLAIN"
        if name in _ALLOWED_ROOT_TYPES:
            return name.upper()
        return "SELECT"


def validate_sql(sql: str, context: SqlSafetyContext) -> ValidatedQuery:
    return SqlSafetyPolicy().validate(sql, context)


def policy_as_safety_context(policy: EffectiveQueryPolicy) -> SqlSafetyContext:
    return SqlSafetyContext(
        engine=policy.engine,
        database=policy.current_database,
        allowed_schemas=policy.allowed_schemas,
    )
