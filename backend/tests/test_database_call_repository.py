import hashlib

import pytest

from context_router.repositories.database_call_repository import (
    DatabaseCallRepositoryError,
    DatabaseCallWrite,
    InMemoryDatabaseCallRepository,
    PostgresDatabaseCallRepository,
)


def test_records_database_call_metadata_without_sql_or_results() -> None:
    repository = InMemoryDatabaseCallRepository()
    sql_digest = hashlib.sha256(b"SELECT count(*) FROM events").hexdigest()

    call_id = repository.create_call(
        DatabaseCallWrite(
            task_id=42,
            operation="execute_query",
            database_alias="analytics",
            engine="clickhouse",
            status="ok",
            statement_type="select",
            sql_sha256=sql_digest,
            duration_ms=17,
            returned_count=1,
            result_bytes=72,
            truncated=False,
        )
    )
    repository.create_call(
        DatabaseCallWrite(
            task_id=42,
            operation="search_objects",
            database_alias="analytics",
            engine="clickhouse",
            status="error",
            object_type="table",
            duration_ms=4,
            error_code="catalog_query_failed",
        )
    )
    repository.create_call(
        DatabaseCallWrite(
            task_id=99,
            operation="search_objects",
            database_alias="other",
            engine="postgresql",
            status="ok",
            returned_count=0,
        )
    )

    calls = repository.list_calls(42)

    assert call_id == 1
    assert [call.id for call in calls] == [1, 2]
    assert calls[0].sql_sha256 == sql_digest
    assert calls[0].returned_count == 1
    assert calls[1].error_code == "catalog_query_failed"
    assert "sql" not in DatabaseCallWrite.__dataclass_fields__
    assert "rows" not in DatabaseCallWrite.__dataclass_fields__


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"task_id": 0}, "任务号必须大于 0"),
        ({"operation": "write_query"}, "数据库调用类型不受支持"),
        ({"status": "pending"}, "数据库调用状态不受支持"),
        ({"sql_sha256": "SELECT 1"}, "SQL 摘要格式不正确"),
        ({"duration_ms": -1}, "调用耗时不能小于 0"),
    ],
)
def test_rejects_invalid_database_call_metadata(
    overrides: dict[str, object],
    message: str,
) -> None:
    repository = InMemoryDatabaseCallRepository()
    values: dict[str, object] = {
        "task_id": 42,
        "operation": "execute_query",
        "database_alias": "analytics",
        "engine": "clickhouse",
        "status": "ok",
    }
    values.update(overrides)

    with pytest.raises(DatabaseCallRepositoryError, match=message):
        repository.create_call(DatabaseCallWrite(**values))  # type: ignore[arg-type]


def test_postgres_repository_requires_configured_task_database() -> None:
    repository = PostgresDatabaseCallRepository(None)
    call = DatabaseCallWrite(
        task_id=42,
        operation="search_objects",
        database_alias="analytics",
        engine="clickhouse",
        status="ok",
    )

    with pytest.raises(DatabaseCallRepositoryError, match="任务数据库尚未配置"):
        repository.create_call(call)
    with pytest.raises(DatabaseCallRepositoryError, match="任务数据库尚未配置"):
        repository.list_calls(42)
