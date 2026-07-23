from datetime import UTC, datetime

import pytest

from context_router.repositories.data_source_repository import (
    DataSourceDatabaseRecord,
    DataSourceRecord,
    DataSourceRepositoryError,
    InMemoryDataSourceRepository,
    ProjectDatabaseLinkRecord,
)


def _source(source_id: str, name: str) -> DataSourceRecord:
    now = datetime.now(UTC)
    return DataSourceRecord(
        id=source_id,
        name=name,
        category="本机电脑",
        engine="postgresql",
        description="",
        connection_config={"host": "localhost", "username": "reader"},
        enabled=True,
        config_version=3,
        database_count=0,
        project_count=0,
        created_at=now,
        updated_at=now,
    )


def _database(database_id: str, source_id: str, remote_name: str) -> DataSourceDatabaseRecord:
    now = datetime.now(UTC)
    return DataSourceDatabaseRecord(
        id=database_id,
        data_source_id=source_id,
        remote_name=remote_name,
        display_name="订单库",
        namespace_type="database",
        available=True,
        system_database=False,
        metadata={"owner": "application"},
        project_count=0,
        created_at=now,
        updated_at=now,
    )


def _link(
    link_id: str,
    project_id: str,
    database: DataSourceDatabaseRecord,
    source: DataSourceRecord,
    *,
    mcp_alias: str | None = None,
) -> ProjectDatabaseLinkRecord:
    now = datetime.now(UTC)
    return ProjectDatabaseLinkRecord(
        id=link_id,
        project_id=project_id,
        project_name="订单项目",
        database_id=database.id,
        database_name=database.remote_name,
        data_source_id=source.id,
        data_source_name=source.name,
        engine=source.engine,
        alias="订单主库",
        mcp_alias=mcp_alias,
        purpose="查询订单",
        enabled=True,
        readonly=True,
        allowed_schemas=["public"],
        max_rows=500,
        max_result_bytes=1_000_000,
        query_timeout_ms=8_000,
        created_at=now,
        updated_at=now,
    )


def test_generates_stable_project_aliases_and_resolves_current_state() -> None:
    repository = InMemoryDataSourceRepository()
    source_a = _source("source-a", "主库")
    source_b = _source("source-b", "归档库")
    database_a = _database("database-a", source_a.id, "orders")
    database_b = _database("database-b", source_b.id, "orders")
    repository.create_data_source(source_a)
    repository.create_data_source(source_b)
    repository.create_database(database_a)
    repository.create_database(database_b)

    first = repository.create_link(_link("a" * 32, "project-a", database_a, source_a))
    second = repository.create_link(_link("b" * 32, "project-a", database_b, source_b))
    other_project = repository.create_link(
        _link("c" * 32, "project-b", database_b, source_b, mcp_alias="orders")
    )

    assert first.mcp_alias == "orders"
    assert second.mcp_alias is not None
    assert second.mcp_alias.startswith("orders_")
    assert other_project.mcp_alias == "orders"

    resolved = repository.get_project_database_by_alias(
        project_id="project-a",
        mcp_alias="ORDERS",
    )
    assert resolved.link_id == first.id
    assert resolved.database_remote_name == "orders"
    assert resolved.database_metadata == {"owner": "application"}
    assert resolved.data_source_id == source_a.id
    assert resolved.connection_config == {"host": "localhost", "username": "reader"}
    assert resolved.source_enabled is True
    assert resolved.database_available is True
    assert resolved.link_enabled is True
    assert resolved.readonly is True
    assert resolved.allowed_schemas == ["public"]
    assert resolved.config_version == 3

    listed = repository.list_project_databases_for_mcp("project-a")
    assert [item.mcp_alias for item in listed] == sorted(
        [first.mcp_alias, second.mcp_alias],
        key=str.casefold,
    )


def test_rejects_manual_alias_conflicts_and_invalid_repository_input() -> None:
    repository = InMemoryDataSourceRepository()
    source_a = _source("source-a", "主库")
    source_b = _source("source-b", "归档库")
    database_a = _database("database-a", source_a.id, "orders")
    database_b = _database("database-b", source_b.id, "archive")
    repository.create_data_source(source_a)
    repository.create_data_source(source_b)
    repository.create_database(database_a)
    repository.create_database(database_b)
    repository.create_link(
        _link("a" * 32, "project-a", database_a, source_a, mcp_alias="analytics")
    )

    with pytest.raises(DataSourceRepositoryError, match="项目内 MCP 数据库别名已存在"):
        repository.create_link(
            _link("b" * 32, "project-a", database_b, source_b, mcp_alias="analytics")
        )

    with pytest.raises(DataSourceRepositoryError, match="MCP 数据库别名格式不正确"):
        repository.create_link(
            _link("c" * 32, "project-b", database_b, source_b, mcp_alias="Bad Alias")
        )


def test_replace_project_links_returns_and_preserves_generated_aliases() -> None:
    repository = InMemoryDataSourceRepository()
    source = _source("source-a", "主库")
    database = _database("database-a", source.id, "orders")
    repository.create_data_source(source)
    repository.create_database(database)
    link = _link("a" * 32, "project-a", database, source)

    saved = repository.replace_project_links("project-a", [link])
    repeated = repository.replace_project_links("project-a", saved)

    assert saved[0].mcp_alias == "orders"
    assert repeated[0].mcp_alias == "orders"
