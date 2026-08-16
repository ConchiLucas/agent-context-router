from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from context_router.repositories.table_relation_repository import (
    InMemoryTableRelationRepository,
    TableRelationBuildRecord,
    TableRelationWarningRecord,
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
    assert build.automatic_file_count == 1


def test_automatic_whitelist_list_uses_rebuild_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryTableRelationRepository()
    service = _service(repository, monkeypatch)
    service._collector = _Collector()  # noqa: SLF001
    service._analyzer = _Analyzer()  # noqa: SLF001
    service.rebuild("workspace-1", project_id="project-1")

    class _BoomCollector:
        def collect(self, **_: object) -> list[SqlSource]:
            raise AssertionError("snapshot list must not rescan SQL files")

    service._collector = _BoomCollector()  # noqa: SLF001
    monkeypatch.setattr(
        service,
        "_project_for_workspace",
        lambda _workspace_id, project_id: SimpleNamespace(
            id=project_id,
            name=project_id,
            resolved_project_root=Path("/tmp"),
        ),
    )
    listed = service.list_automatic_whitelist_files(
        workspace_id="workspace-1",
        project_id="project-1",
        rule_code="automatic_ddl",
    )
    assert [item.source_path for item in listed.files] == ["sql/automatic.sql"]


def test_project_rebuild_skips_files_with_missing_table_or_column_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryTableRelationRepository()
    analyzer = _Analyzer()
    service = _service(repository, monkeypatch)
    service._collector = _Collector()  # noqa: SLF001
    service._analyzer = analyzer  # noqa: SLF001
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="project-1",
        database_key="database-1",
        generation_id="generation-old",
        config_revision=1,
    )
    repository.publish(
        build=TableRelationBuildRecord(
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="project-1",
            database_key="database-1",
            generation_id="generation-old",
            status="building",
            sql_file_count=1,
            statement_count=1,
            relation_count=0,
            warnings=(),
            error_message=None,
            started_at=None,
            finished_at=None,
        ),
        relations=[],
        warning_records=[
            TableRelationWarningRecord(
                project_id="project-1",
                project_name="project-1",
                database_key="database-1",
                source_path="sql/kept.sql",
                code="join_metadata_column_not_found",
                message="missing column",
            )
        ],
    )

    service.rebuild("workspace-1", project_id="project-1")

    assert analyzer.paths == ["sql/custom.sql"]
    assert {item.code for item in repository.list_warnings("workspace-1")} == {
        "automatic_missing_table_or_column",
    }
    monkeypatch.setattr(
        service,
        "_project_for_workspace",
        lambda _workspace_id, project_id: SimpleNamespace(
            id=project_id,
            name=project_id,
            resolved_project_root=Path("/tmp"),
        ),
    )
    listed = service.list_automatic_whitelist_files(
        workspace_id="workspace-1",
        project_id="project-1",
        rule_code="automatic_missing_table_or_column",
    )
    assert [item.source_path for item in listed.files] == ["sql/kept.sql"]


def test_project_rebuild_skips_files_with_invalid_sql_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryTableRelationRepository()
    analyzer = _Analyzer()
    service = _service(repository, monkeypatch)
    service._collector = _Collector()  # noqa: SLF001
    service._analyzer = analyzer  # noqa: SLF001
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="project-1",
        database_key="database-1",
        generation_id="generation-old",
        config_revision=1,
    )
    repository.publish(
        build=TableRelationBuildRecord(
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="project-1",
            database_key="database-1",
            generation_id="generation-old",
            status="building",
            sql_file_count=1,
            statement_count=1,
            relation_count=0,
            warnings=(),
            error_message=None,
            started_at=None,
            finished_at=None,
        ),
        relations=[],
        warning_records=[
            TableRelationWarningRecord(
                project_id="project-1",
                project_name="project-1",
                database_key="database-1",
                source_path="sql/kept.sql",
                code="join_unqualified_column_unsupported",
                message="unqualified",
            )
        ],
    )

    service.rebuild("workspace-1", project_id="project-1")

    assert analyzer.paths == ["sql/custom.sql"]
    assert {item.code for item in repository.list_warnings("workspace-1")} == {
        "automatic_invalid_sql",
    }
    monkeypatch.setattr(
        service,
        "_project_for_workspace",
        lambda _workspace_id, project_id: SimpleNamespace(
            id=project_id,
            name=project_id,
            resolved_project_root=Path("/tmp"),
        ),
    )
    listed = service.list_automatic_whitelist_files(
        workspace_id="workspace-1",
        project_id="project-1",
        rule_code="automatic_invalid_sql",
    )
    assert [item.source_path for item in listed.files] == ["sql/kept.sql"]
    assert listed.rule.group == "no_value"


def test_project_rebuild_still_scans_complex_sql_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryTableRelationRepository()
    analyzer = _Analyzer()
    service = _service(repository, monkeypatch)

    class _ComplexCollector:
        def collect(self, **kwargs: object) -> list[SqlSource]:
            return [
                SqlSource(
                    workspace_id=str(kwargs["workspace_id"]),
                    project_id=str(kwargs["project_id"]),
                    project_name=str(kwargs["project_name"]),
                    database_key=str(kwargs["database_key"]),
                    dialect=str(kwargs["dialect"]),
                    source_path="sql/complex.sql",
                    statement="SELECT FROM",
                )
            ]

    service._collector = _ComplexCollector()  # noqa: SLF001
    service._analyzer = analyzer  # noqa: SLF001

    service.rebuild("workspace-1", project_id="project-1")

    assert analyzer.paths == ["sql/complex.sql"]
    monkeypatch.setattr(
        service,
        "_project_for_workspace",
        lambda _workspace_id, project_id: SimpleNamespace(
            id=project_id,
            name=project_id,
            resolved_project_root=Path("/tmp"),
        ),
    )
    listed = service.list_automatic_whitelist_files(
        workspace_id="workspace-1",
        project_id="project-1",
        rule_code="automatic_complex_sql",
    )
    assert [item.source_path for item in listed.files] == ["sql/complex.sql"]
    assert listed.rule.group == "parser_gap"


def test_parser_gap_whitelist_lists_warning_files_without_skipping_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryTableRelationRepository()
    analyzer = _Analyzer()
    service = _service(repository, monkeypatch)
    service._collector = _Collector()  # noqa: SLF001
    service._analyzer = analyzer  # noqa: SLF001
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="project-1",
        database_key="database-1",
        generation_id="generation-old",
        config_revision=1,
    )
    repository.publish(
        build=TableRelationBuildRecord(
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="project-1",
            database_key="database-1",
            generation_id="generation-old",
            status="building",
            sql_file_count=1,
            statement_count=1,
            relation_count=0,
            warnings=(),
            error_message=None,
            started_at=None,
            finished_at=None,
        ),
        relations=[],
        warning_records=[
            TableRelationWarningRecord(
                project_id="project-1",
                project_name="project-1",
                database_key="database-1",
                source_path="sql/kept.sql",
                code="join_derived_relation_unsupported",
                message="derived",
            )
        ],
    )
    monkeypatch.setattr(
        service,
        "_project_for_workspace",
        lambda _workspace_id, project_id: SimpleNamespace(
            id=project_id,
            name=project_id,
            resolved_project_root=Path("/tmp"),
        ),
    )
    listed = service.list_automatic_whitelist_files(
        workspace_id="workspace-1",
        project_id="project-1",
        rule_code="automatic_derived_relation",
    )
    assert [item.source_path for item in listed.files] == ["sql/kept.sql"]

    service.rebuild("workspace-1", project_id="project-1")

    assert "sql/kept.sql" in analyzer.paths
    assert "sql/custom.sql" in analyzer.paths


def test_automatic_whitelist_assigns_each_file_to_one_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryTableRelationRepository()
    service = _service(repository, monkeypatch)

    class _MixedCollector:
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
                    ("sql/create.sql", "CREATE TABLE cargo (id BIGINT)"),
                    (
                        "sql/join-mixed.sql",
                        "SELECT c.id FROM cargo c JOIN category k ON k.id = c.category_id",
                    ),
                    (
                        "sql/or-only.sql",
                        "SELECT c.id FROM cargo c JOIN category k "
                        "ON c.category_id = k.id OR c.id = k.id",
                    ),
                    (
                        "sql/invalid.sql",
                        "SELECT c.id FROM cargo c JOIN category k ON k.id = c.category_id",
                    ),
                    (
                        "sql/missing.sql",
                        "SELECT c.id FROM cargo c JOIN category k ON k.id = c.category_id",
                    ),
                    ("sql/complex.sql", "SELECT FROM"),
                )
            ]

    service._collector = _MixedCollector()  # noqa: SLF001
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="project-1",
        database_key="database-1",
        generation_id="generation-old",
        config_revision=1,
    )
    repository.publish(
        build=TableRelationBuildRecord(
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="project-1",
            database_key="database-1",
            generation_id="generation-old",
            status="building",
            sql_file_count=6,
            statement_count=6,
            relation_count=0,
            warnings=(),
            error_message=None,
            started_at=None,
            finished_at=None,
        ),
        relations=[],
        warning_records=[
            TableRelationWarningRecord(
                project_id="project-1",
                project_name="project-1",
                database_key="database-1",
                source_path="sql/join-mixed.sql",
                code="join_derived_relation_unsupported",
                message="derived",
            ),
            TableRelationWarningRecord(
                project_id="project-1",
                project_name="project-1",
                database_key="database-1",
                source_path="sql/join-mixed.sql",
                code="join_or_unsupported",
                message="or",
            ),
            TableRelationWarningRecord(
                project_id="project-1",
                project_name="project-1",
                database_key="database-1",
                source_path="sql/or-only.sql",
                code="join_or_unsupported",
                message="or",
            ),
            TableRelationWarningRecord(
                project_id="project-1",
                project_name="project-1",
                database_key="database-1",
                source_path="sql/invalid.sql",
                code="join_unqualified_column_unsupported",
                message="unqualified",
            ),
            TableRelationWarningRecord(
                project_id="project-1",
                project_name="project-1",
                database_key="database-1",
                source_path="sql/invalid.sql",
                code="join_derived_relation_unsupported",
                message="derived",
            ),
            TableRelationWarningRecord(
                project_id="project-1",
                project_name="project-1",
                database_key="database-1",
                source_path="sql/missing.sql",
                code="join_metadata_column_not_found",
                message="missing",
            ),
            TableRelationWarningRecord(
                project_id="project-1",
                project_name="project-1",
                database_key="database-1",
                source_path="sql/missing.sql",
                code="join_derived_relation_unsupported",
                message="derived",
            ),
        ],
    )
    monkeypatch.setattr(
        service,
        "_project_for_workspace",
        lambda _workspace_id, project_id: SimpleNamespace(
            id=project_id,
            name=project_id,
            resolved_project_root=Path("/tmp"),
        ),
    )

    assigned: dict[str, list[str]] = {}
    for rule_code in (
        "automatic_ddl",
        "automatic_missing_table_or_column",
        "automatic_invalid_sql",
        "automatic_derived_relation",
        "automatic_or_unsupported",
        "automatic_complex_sql",
    ):
        listed = service.list_automatic_whitelist_files(
            workspace_id="workspace-1",
            project_id="project-1",
            rule_code=rule_code,
        )
        assigned[rule_code] = [item.source_path for item in listed.files]

    assert assigned == {
        "automatic_ddl": ["sql/create.sql"],
        "automatic_missing_table_or_column": ["sql/missing.sql"],
        "automatic_invalid_sql": ["sql/invalid.sql"],
        "automatic_derived_relation": ["sql/join-mixed.sql"],
        "automatic_or_unsupported": ["sql/or-only.sql"],
        "automatic_complex_sql": ["sql/complex.sql"],
    }
    paths = [path for files in assigned.values() for path in files]
    assert len(paths) == len(set(paths))
