from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from context_router.repositories.table_relation_repository import (
    InMemoryTableRelationRepository,
)
from context_router.schemas.table_relations import TableRelationBuildStatus
from context_router.services.sql_join_analyzer import SqlSource
from context_router.services.table_relations import (
    TableRelationService,
    TableRelationServiceError,
)


class _EmptyCollector:
    def collect(self, **_: object) -> list[object]:
        return []


class _ProfileLoader:
    def load(self, _: Path) -> object:
        return SimpleNamespace(
            excluded_by=lambda **_: None,
            match=lambda **_: None,
        )


class _Collector:
    def collect(self, **kwargs: object) -> list[SqlSource]:
        return [
            SqlSource(
                workspace_id=str(kwargs["workspace_id"]),
                project_id=str(kwargs["project_id"]),
                project_name=str(kwargs["project_name"]),
                database_key=str(kwargs["database_key"]),
                dialect=str(kwargs["dialect"]),
                source_path=path,
                statement=statement,
            )
            for path, statement in (
                ("sql/custom.sql", "SELECT a.id FROM a JOIN b ON b.id = a.b_id"),
                ("sql/automatic.sql", "CREATE TABLE ignored (id BIGINT)"),
                ("sql/kept.sql", "SELECT a.id FROM a JOIN b ON b.id = a.b_id"),
            )
        ]


class _Analyzer:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def analyze(self, source: SqlSource, *_: object) -> tuple[list[object], list[object], int]:
        self.paths.append(source.source_path)
        return [], [], 1


def _status() -> TableRelationBuildStatus:
    return TableRelationBuildStatus(
        workspace_id="workspace-1",
        status="partial",
        project_count=2,
        ready_project_count=1,
        sql_file_count=0,
        statement_count=0,
        relation_count=0,
        warning_count=0,
        config_revision=1,
        eligible_project_count=2,
        configured_project_count=2,
    )


def _service(
    repository: InMemoryTableRelationRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> TableRelationService:
    repository.replace_default_databases(
        workspace_id="workspace-1",
        expected_revision=0,
        targets=[("project-1", "link-1"), ("project-2", "link-2")],
    )
    service = TableRelationService(
        registry=cast("object", None),
        task_repository=cast("object", None),
        data_source_repository=cast("object", None),
        repository=repository,
        connector_manager=cast("object", None),
        collector=_EmptyCollector(),  # type: ignore[arg-type]
        profile_loader=_ProfileLoader(),  # type: ignore[arg-type]
    )
    config = repository.get_default_database_config("workspace-1")
    targets = [
        SimpleNamespace(
            database=SimpleNamespace(
                project_id=f"project-{index}",
                project_name=f"project-{index}",
                mcp_alias=f"database-{index}",
            ),
            project_root=Path(f"/workspace/project-{index}"),
            workspace_root=Path("/workspace"),
        )
        for index in (1, 2)
    ]
    monkeypatch.setattr(service, "_require_complete_default_config", lambda _: config)
    monkeypatch.setattr(service, "_targets", lambda *_: targets)
    monkeypatch.setattr(service, "get_status", lambda _: _status())
    monkeypatch.setattr(
        "context_router.services.table_relations.ConnectorTableMetadataProvider",
        lambda **_: object(),
    )
    return service


def test_project_rebuild_publishes_only_the_selected_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryTableRelationRepository()
    service = _service(repository, monkeypatch)

    result = service.rebuild("workspace-1", project_id="project-2")

    assert result.status == "partial"
    builds = repository.list_builds("workspace-1")
    assert [(item.project_id, item.status) for item in builds] == [("project-2", "ready")]


def test_project_rebuild_rejects_projects_without_a_configured_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryTableRelationRepository()
    service = _service(repository, monkeypatch)

    with pytest.raises(TableRelationServiceError) as caught:
        service.rebuild("workspace-1", project_id="project-unknown")

    assert caught.value.code == "table_relation_project_not_found"
    assert repository.list_builds("workspace-1") == []


def test_project_rebuild_skips_custom_and_automatic_whitelist_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryTableRelationRepository()
    analyzer = _Analyzer()
    service = _service(repository, monkeypatch)
    service._collector = _Collector()  # noqa: SLF001
    service._analyzer = analyzer  # noqa: SLF001
    repository.replace_sql_whitelist(
        workspace_id="workspace-1",
        project_id="project-1",
        source_paths=["sql/custom.sql"],
    )

    service.rebuild("workspace-1", project_id="project-1")

    assert analyzer.paths == ["sql/kept.sql"]
    build = repository.list_builds("workspace-1")[0]
    assert build.sql_file_count == 1
    assert build.statement_count == 1
