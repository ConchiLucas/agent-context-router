from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from context_router.repositories.data_source_repository import (
    DataSourceDatabaseRecord,
    DataSourceRecord,
    DataSourceRepositoryError,
    InMemoryDataSourceRepository,
    PostgresDataSourceRepository,
    ProjectDatabaseLinkRecord,
)
from context_router.schemas.data_sources import WorkspaceDataSourceSummary


def _source(source_id: str, name: str) -> DataSourceRecord:
    now = datetime.now(UTC)
    return DataSourceRecord(
        id=source_id,
        name=name,
        category="本机电脑",
        engine="postgresql",
        description="",
        connection_config={},
        config_version=1,
        database_count=0,
        project_count=0,
        created_at=now,
        updated_at=now,
    )


def _database(
    database_id: str,
    source_id: str,
    remote_name: str,
    *,
    available: bool = True,
) -> DataSourceDatabaseRecord:
    now = datetime.now(UTC)
    return DataSourceDatabaseRecord(
        id=database_id,
        data_source_id=source_id,
        remote_name=remote_name,
        display_name=f"{remote_name} 展示名",
        namespace_type="database",
        available=available,
        system_database=False,
        metadata={},
        project_count=0,
        created_at=now,
        updated_at=now,
    )


def _link(
    link_id: str,
    project_id: str,
    project_name: str,
    database: DataSourceDatabaseRecord,
    source: DataSourceRecord,
    *,
    workspace_id: str,
    project_kind: str = "backend",
) -> ProjectDatabaseLinkRecord:
    now = datetime.now(UTC)
    return ProjectDatabaseLinkRecord(
        id=link_id,
        project_id=project_id,
        project_name=project_name,
        database_id=database.id,
        database_name=database.remote_name,
        data_source_id=source.id,
        data_source_name=source.name,
        engine=source.engine,
        alias=database.display_name,
        mcp_alias=f"db_{link_id}",
        purpose="工作空间汇总测试",
        readonly=True,
        allowed_schemas=[],
        max_rows=100,
        max_result_bytes=100_000,
        query_timeout_ms=1_000,
        created_at=now,
        updated_at=now,
        workspace_id=workspace_id,
        project_kind=project_kind,
    )


def test_in_memory_workspace_summary_aggregates_distinct_usage_and_statuses() -> None:
    repository = InMemoryDataSourceRepository()
    primary = _source("source-primary", "Primary")
    archive = _source("source-archive", "Archive")
    orders = _database("database-orders", primary.id, "orders")
    events = _database("database-events", primary.id, "events", available=False)
    history = _database("database-history", archive.id, "history")
    for source in (primary, archive):
        repository.create_data_source(source)
    for database in (orders, events, history):
        repository.create_database(database)

    links = [
        _link(
            "orders-a",
            "project-a",
            "订单服务",
            orders,
            primary,
            workspace_id="workspace-a",
            project_kind="backend",
        ),
        _link(
            "orders-b",
            "project-b",
            "管理后台",
            orders,
            primary,
            workspace_id="workspace-a",
            project_kind="frontend",
        ),
        _link(
            "events-a",
            "project-a",
            "订单服务",
            events,
            primary,
            workspace_id="workspace-a",
        ),
        _link(
            "history-a",
            "project-a",
            "订单服务",
            history,
            archive,
            workspace_id="workspace-a",
        ),
        _link("outside", "project-c", "其他项目", orders, primary, workspace_id="workspace-b"),
    ]
    for link in links:
        repository.create_link(link)

    summary = repository.get_workspace_data_source_summary(
        "workspace-a",
    )

    assert summary.workspace_id == "workspace-a"
    assert summary.source_count == 2
    assert summary.database_count == 3
    assert summary.assignment_count == 4
    assert summary.project_count == 2

    sources = {source.id: source for source in summary.sources}
    assert sources[primary.id].database_count == 2
    assert sources[primary.id].assignment_count == 3
    assert sources[primary.id].project_count == 2
    assert sources[archive.id].database_count == 1
    assert sources[archive.id].assignment_count == 1
    assert sources[archive.id].project_count == 1

    statuses = {
        assignment.link_id: assignment.status
        for source in summary.sources
        for assignment in source.assignments
    }
    assert statuses == {
        "orders-a": "active",
        "orders-b": "active",
        "events-a": "database_unavailable",
        "history-a": "active",
    }
    assignments = {
        assignment.link_id: assignment
        for source in summary.sources
        for assignment in source.assignments
    }
    assert assignments["orders-a"].project_kind == "backend"
    assert assignments["orders-b"].project_kind == "frontend"

    response = WorkspaceDataSourceSummary.model_validate(summary)
    assert response.model_dump()["sources"][0]["assignments"]


def test_in_memory_workspace_summary_accepts_empty_project_membership() -> None:
    repository = InMemoryDataSourceRepository()

    summary = repository.get_workspace_data_source_summary(
        "workspace-empty",
    )

    assert summary.source_count == 0
    assert summary.database_count == 0
    assert summary.assignment_count == 0
    assert summary.project_count == 0
    assert summary.sources == []


class _FakeResult:
    def __init__(
        self,
        *,
        one: tuple[object, ...] | None = None,
        rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        self._one = one
        self._rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return self._one

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _FakeConnection:
    def __init__(
        self,
        *,
        workspace_row: tuple[object, ...] | None,
        assignment_rows: list[tuple[object, ...]],
    ) -> None:
        self.workspace_row = workspace_row
        self.assignment_rows = assignment_rows
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(
        self,
        query: str,
        params: tuple[object, ...] | None = None,
    ) -> _FakeResult:
        self.calls.append((query, params))
        if "FROM workspaces" in query:
            return _FakeResult(one=self.workspace_row)
        return _FakeResult(rows=self.assignment_rows)


def test_postgres_workspace_summary_reads_current_workspace_and_project_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection(
        workspace_row=(1,),
        assignment_rows=[
            (
                "source-a",
                "主库",
                "公司数据源",
                "postgresql",
                "link-a",
                "project-a",
                "订单项目",
                "backend",
                "database-a",
                "orders",
                "订单库",
                True,
                False,
                "orders",
                "订单主库",
                "查询订单",
                True,
            )
        ],
    )
    repository = PostgresDataSourceRepository("postgresql://unused")
    monkeypatch.setattr(repository, "_connect", lambda _message: connection)

    summary = repository.get_workspace_data_source_summary(
        "workspace-a",
    )

    assert summary.source_count == 1
    assert summary.database_count == 1
    assert summary.assignment_count == 1
    assert summary.project_count == 1
    assert summary.sources[0].assignments[0].status == "active"
    assert connection.calls[0][1] == ("workspace-a",)
    assert "project.workspace_id=%s" in connection.calls[1][0]
    assert connection.calls[1][1] == ("workspace-a",)


def test_postgres_workspace_summary_rejects_missing_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection(workspace_row=None, assignment_rows=[])
    repository = PostgresDataSourceRepository("postgresql://unused")
    monkeypatch.setattr(repository, "_connect", lambda _message: connection)

    with pytest.raises(DataSourceRepositoryError, match="工作空间不存在"):
        repository.get_workspace_data_source_summary("missing")

    assert len(connection.calls) == 1


def test_database_status_has_precedence_over_readonly_and_alias_issues() -> None:
    repository = InMemoryDataSourceRepository()
    source = _source("source-a", "主库")
    database = _database("database-a", source.id, "orders", available=False)
    repository.create_data_source(source)
    repository.create_database(database)
    repository.create_link(
        replace(
            _link(
                "link-a",
                "project-a",
                "订单项目",
                database,
                source,
                workspace_id="workspace-a",
            ),
            readonly=False,
            mcp_alias=None,
        )
    )

    summary = repository.get_workspace_data_source_summary(
        "workspace-a",
    )

    assert summary.sources[0].assignments[0].status == "database_unavailable"
