import pytest

from context_router.database import (
    QueryPolicyError,
    QueryPolicyHardLimits,
    SqlSafetyContext,
    build_effective_policy,
    validate_sql,
)


@pytest.mark.parametrize(
    ("sql", "statement_type"),
    [
        ("SELECT 1", "SELECT"),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "SELECT"),
        ("SELECT * FROM allowed_table LIMIT 10", "SELECT"),
        ("EXPLAIN SELECT * FROM allowed_table", "EXPLAIN"),
        ("DESCRIBE TABLE allowed_table", "DESCRIBE"),
        ("SHOW TABLES", "SHOW"),
    ],
)
def test_sql_policy_allows_single_readonly_statement(sql: str, statement_type: str) -> None:
    context = SqlSafetyContext(engine="clickhouse", database="analytics")

    assert validate_sql(sql, context).statement_type == statement_type


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DROP TABLE x",
        "INSERT INTO x SELECT 1",
        "CREATE TABLE x (id Int32)",
        "SYSTEM FLUSH LOGS",
        "SELECT * FROM other_database.secret",
        "SELECT * FROM url('http://example.invalid')",
        "SELECT * FROM file('/etc/passwd')",
        "SELECT LOAD_FILE('/etc/passwd')",
        "SELECT 1 SETTINGS readonly=0",
        "SELECT 1 INTO OUTFILE '/tmp/x'",
        "SHOW TABLES INTO OUTFILE '/tmp/x'",
        "SHOW TABLES; DROP TABLE x",
        "SELECT 1 FORMAT JSON",
        "EXPLAIN INSERT INTO x SELECT 1",
    ],
)
def test_sql_policy_rejects_writes_external_access_and_overrides(sql: str) -> None:
    context = SqlSafetyContext(engine="clickhouse", database="analytics")

    with pytest.raises(QueryPolicyError) as rejected:
        validate_sql(sql, context)

    assert rejected.value.code == "query_rejected"


def test_sql_policy_handles_comments_strings_ctes_and_trailing_semicolon() -> None:
    context = SqlSafetyContext(engine="postgresql", database="app", allowed_schemas=("public",))
    sql = """-- semicolon ; in a comment
    WITH x AS (SELECT ';' AS value)
    SELECT value FROM x;
    """

    assert validate_sql(sql, context).statement_type == "SELECT"


def test_sql_policy_enforces_schema_allowlist_and_database_scope() -> None:
    context = SqlSafetyContext(engine="postgresql", database="app", allowed_schemas=("public",))

    assert validate_sql('SELECT * FROM "public"."events"', context)
    with pytest.raises(QueryPolicyError, match="allowed schema"):
        validate_sql("SELECT * FROM private.events", context)
    with pytest.raises(QueryPolicyError, match="cross-database"):
        validate_sql("SELECT * FROM other.public.events", context)
    with pytest.raises(QueryPolicyError, match="system catalogs"):
        validate_sql("SELECT * FROM pg_catalog.pg_tables", context)


def test_sql_policy_does_not_treat_cte_name_as_a_physical_table() -> None:
    context = SqlSafetyContext(engine="postgresql", database="app", allowed_schemas=("public",))

    query = validate_sql(
        "WITH private AS (SELECT * FROM public.events) SELECT * FROM private",
        context,
    )

    assert query.statement_type == "SELECT"


def test_show_cannot_target_another_database() -> None:
    context = SqlSafetyContext(engine="clickhouse", database="analytics")

    with pytest.raises(QueryPolicyError, match="cross-database"):
        validate_sql("SHOW TABLES FROM secret", context)


def test_effective_policy_applies_service_hard_caps() -> None:
    policy = build_effective_policy(
        engine="clickhouse",
        current_database="analytics",
        readonly=True,
        allowed_schemas=[],
        max_rows=100_000,
        max_result_bytes=100_000_000,
        query_timeout_ms=300_000,
        hard_limits=QueryPolicyHardLimits(
            max_rows=5_000,
            max_result_bytes=4_000_000,
            max_query_timeout_ms=30_000,
        ),
    )

    assert policy.max_rows == 5_000
    assert policy.max_result_bytes == 4_000_000
    assert policy.query_timeout_ms == 30_000


def test_effective_policy_rejects_non_readonly_link() -> None:
    with pytest.raises(QueryPolicyError) as rejected:
        build_effective_policy(
            engine="mysql",
            current_database="orders",
            readonly=False,
            allowed_schemas=[],
            max_rows=100,
            max_result_bytes=10_000,
            query_timeout_ms=1_000,
        )

    assert rejected.value.code == "query_rejected"
