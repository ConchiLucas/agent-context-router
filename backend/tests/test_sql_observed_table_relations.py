import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from context_router.database.manager import ConnectorManagerError
from context_router.repositories.table_relation_repository import (
    InMemoryTableRelationRepository,
    TableJoinEvidenceRecord,
    TableJoinRelationRecord,
    TableRelationBuildRecord,
    TableRelationWarningRecord,
)
from context_router.services.project_registry import ProjectRegistryError
from context_router.services.sql_join_analyzer import (
    MetadataColumnResolution,
    SqlAutomaticWhitelist,
    SqlFileCollector,
    SqlObservedJoinAnalyzer,
    SqlSource,
)
from context_router.services.table_relations import (
    TableRelationService,
    TableRelationServiceError,
)

_GOLDEN_PATH = Path(__file__).parent / "fixtures" / "sql_table_relation_golden.json"
_GOLDEN_SUITE = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))


def _configure_defaults(
    repository: InMemoryTableRelationRepository,
    *projects: str,
) -> None:
    repository.replace_default_databases(
        workspace_id="workspace-1",
        expected_revision=0,
        targets=[(project_id, f"link-{project_id}") for project_id in projects],
    )


class _RelationRegistry:
    def __init__(self, projects: tuple[str, ...]) -> None:
        self._projects = projects
        self._snapshot = SimpleNamespace(
            projects=[
                SimpleNamespace(id=project_id, project_kind="backend") for project_id in projects
            ]
        )

    def get_workspace_snapshot(self, _: str) -> object:
        return self._snapshot

    def get_snapshot(self, project_id: str) -> object:
        if project_id not in self._projects:
            raise ProjectRegistryError("项目不存在")
        return SimpleNamespace(
            id=project_id,
            name=project_id,
            workspace_id="workspace-1",
            project_kind="backend",
        )


class _RelationDataSources:
    def __init__(self, repository: InMemoryTableRelationRepository) -> None:
        config = repository.get_default_database_config("workspace-1")
        builds = {item.project_id: item for item in repository.list_builds("workspace-1")}
        self._databases = [
            SimpleNamespace(
                link_id=link_id,
                project_id=project_id,
                project_name=builds[project_id].project_name,
                mcp_alias=builds[project_id].database_key,
                database_remote_name=(
                    next(
                        relation.table_a_schema
                        for relation in repository.list_relations("workspace-1")
                        if relation.project_id == project_id
                    )
                    if any(
                        relation.project_id == project_id
                        for relation in repository.list_relations("workspace-1")
                    )
                    else "app"
                ),
                database_display_name=builds[project_id].database_key,
                data_source_name="test",
                engine="mysql",
                readonly=True,
                database_available=True,
                database_system=False,
            )
            for project_id, link_id in config.targets
        ]

    def list_workspace_databases_for_mcp(self, _: str) -> list[object]:
        return self._databases


def _relation_service(repository: InMemoryTableRelationRepository) -> TableRelationService:
    config = repository.get_default_database_config("workspace-1")
    projects = tuple(project_id for project_id, _ in config.targets)
    return TableRelationService(
        registry=_RelationRegistry(projects),  # type: ignore[arg-type]
        task_repository=cast("object", None),
        data_source_repository=_RelationDataSources(repository),  # type: ignore[arg-type]
        repository=repository,
        connector_manager=cast("object", None),
    )


class DictionaryMetadata:
    def __init__(self, tables: dict[str, set[str]]) -> None:
        self._tables = tables

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
        assert database_key == "cargo_db"
        tables = [
            (name, columns)
            for name, columns in self._tables.items()
            if name.casefold() == table_name.casefold()
        ]
        if not tables:
            return MetadataColumnResolution(None, "table_not_found")
        if len(tables) > 1:
            return MetadataColumnResolution(None, "table_ambiguous")
        name, columns = tables[0]
        matches = [item for item in columns if item.casefold() == column_name.casefold()]
        if not matches:
            return MetadataColumnResolution(None, "column_not_found")
        if len(matches) > 1:
            return MetadataColumnResolution(None, "column_ambiguous")
        column = next(item for item in columns if item.casefold() == column_name.casefold())
        return MetadataColumnResolution((schema_name or "cargo", name, column))


def source(sql: str) -> SqlSource:
    return SqlSource(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="cargo-service",
        database_key="cargo_db",
        dialect="mysql",
        source_path="src/main/resources/sql/cargo.sql",
        statement=sql,
    )


def test_sql_file_collector_prunes_target_directories(tmp_path: Path) -> None:
    source_file = tmp_path / "src" / "main" / "resources" / "sql" / "cargo.sql"
    target_file = tmp_path / "target" / "classes" / "sql" / "cargo.sql"
    nested_target_file = tmp_path / "module" / "TARGET" / "generated" / "cargo.sql"
    for path in (source_file, target_file, nested_target_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("select 1", encoding="utf-8")

    sources = SqlFileCollector().collect(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="cargo-service",
        project_root=tmp_path,
        database_key="cargo_db",
        dialect="mysql",
    )

    assert [item.source_path for item in sources] == ["src/main/resources/sql/cargo.sql"]


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("CREATE TABLE cargo (id BIGINT)", "automatic_ddl"),
        ("ALTER TABLE cargo ADD COLUMN category_id BIGINT", "automatic_ddl"),
        ("DROP TABLE cargo", "automatic_ddl"),
        ("TRUNCATE TABLE cargo", "automatic_ddl"),
        ("SELECT id, name FROM cargo WHERE deleted = 0", "automatic_single_table_query"),
        ("INSERT INTO cargo (id, name) VALUES (1, 'coal')", "automatic_write_without_query"),
        ("UPDATE cargo SET name = 'coal' WHERE id = 1", "automatic_write_without_query"),
        (
            "CREATE TABLE cargo (id BIGINT); UPDATE cargo SET id = 1",
            "automatic_safe_mixed",
        ),
    ],
)
def test_automatic_whitelist_accepts_only_explicit_safe_statement_shapes(
    sql: str,
    reason: str,
) -> None:
    assert SqlAutomaticWhitelist().classify(source(sql)) == reason


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT c.id FROM cargo c JOIN category k ON k.id = c.category_id",
        "INSERT INTO cargo_archive SELECT * FROM cargo",
        "UPDATE cargo c JOIN category k ON k.id = c.category_id SET c.name = k.name",
        "UPDATE cargo SET name = (SELECT name FROM category WHERE category.id = cargo.category_id)",
        "SELECT * FROM cargo WHERE <<tenant_id = :tenantId>>",
        "SELECT FROM",
    ],
)
def test_automatic_whitelist_fails_closed_for_relational_or_unparseable_sql(sql: str) -> None:
    assert SqlAutomaticWhitelist().classify(source(sql)) is None


@pytest.fixture
def metadata() -> DictionaryMetadata:
    return DictionaryMetadata(
        {
            "cargo": {"id", "category_id", "tenant_id", "status"},
            "category": {"id", "tenant_id", "status"},
            "cargo_tag": {"cargo_id", "tag_id"},
        }
    )


@pytest.mark.parametrize("case", _GOLDEN_SUITE["cases"], ids=lambda item: item["id"])
def test_sql_relation_golden_cases(case: dict[str, object]) -> None:
    suite_metadata = DictionaryMetadata(
        {name: set(columns) for name, columns in _GOLDEN_SUITE["tables"].items()}
    )
    facts, warnings, _ = SqlObservedJoinAnalyzer().analyze(
        source(str(case["sql"])),
        suite_metadata,
    )

    actual_facts = sorted(
        (
            fact.left.table_name.casefold(),
            fact.left.column_name.casefold(),
            fact.right.table_name.casefold(),
            fact.right.column_name.casefold(),
        )
        for fact in facts
    )
    expected_facts = sorted(
        tuple(str(value).casefold() for value in item) for item in case["facts"]
    )
    assert actual_facts == expected_facts
    assert sorted(item.code for item in warnings) == sorted(case["warnings"])
    assert all("\x1b" not in warning.message for warning in warnings)


def test_golden_suite_has_thirty_three_reviewable_cases() -> None:
    assert len(_GOLDEN_SUITE["cases"]) == 33


def test_extracts_only_metadata_validated_equality_join_evidence(
    metadata: DictionaryMetadata,
) -> None:
    facts, warnings, statement_count = SqlObservedJoinAnalyzer().analyze(
        source(
            """
            SELECT c.id
            FROM cargo c
            JOIN category category
              ON c.category_id = category.id
             AND c.tenant_id = category.tenant_id
            WHERE c.status = 1 AND c.id > 10
            """
        ),
        metadata,
    )

    assert statement_count == 1
    assert warnings == []
    assert {
        (fact.left.table_name, fact.left.column_name, fact.right.table_name, fact.right.column_name)
        for fact in facts
    } == {
        ("cargo", "category_id", "category", "id"),
        ("cargo", "tenant_id", "category", "tenant_id"),
    }
    assert all(fact.source_path.endswith("cargo.sql") for fact in facts)
    assert all("JOIN category" in fact.sql_statement for fact in facts)


def test_recursive_cte_join_is_an_expected_derived_boundary(
    metadata: DictionaryMetadata,
) -> None:
    facts, warnings, statement_count = SqlObservedJoinAnalyzer().analyze(
        source(
            """
            WITH RECURSIVE ancestors AS (
                SELECT c.id, c.category_id
                FROM cargo c
                UNION ALL
                SELECT parent.id, parent.category_id
                FROM cargo parent
                JOIN ancestors a ON parent.id = a.category_id
            )
            SELECT k.id
            FROM category k
            JOIN ancestors a ON k.id = a.category_id
            """
        ),
        metadata,
    )

    assert statement_count == 1
    assert facts == []
    assert {warning.code for warning in warnings} == {"join_derived_relation_unsupported"}


def test_correlated_subquery_reference_is_an_expected_scope_boundary(
    metadata: DictionaryMetadata,
) -> None:
    facts, warnings, statement_count = SqlObservedJoinAnalyzer().analyze(
        source(
            """
            SELECT c.id
            FROM cargo c
            WHERE EXISTS (
                SELECT 1
                FROM cargo_tag ct
                JOIN category k ON k.id = c.category_id AND k.id = ct.tag_id
            )
            """
        ),
        metadata,
    )

    assert statement_count == 1
    assert [
        (fact.left.table_name, fact.left.column_name, fact.right.table_name, fact.right.column_name)
        for fact in facts
    ] == [("category", "id", "cargo_tag", "tag_id")]
    assert {warning.code for warning in warnings} == {"join_correlated_reference_unsupported"}


def test_metadata_failures_are_reported_per_join_side(
    metadata: DictionaryMetadata,
) -> None:
    facts, warnings, statement_count = SqlObservedJoinAnalyzer().analyze(
        source("SELECT * FROM cargo c JOIN missing_table m ON c.unknown_id = m.id"),
        metadata,
    )

    assert statement_count == 1
    assert facts == []
    assert {warning.code for warning in warnings} == {
        "join_metadata_column_not_found",
        "join_metadata_table_not_found",
    }
    assert any(
        "cargo" in warning.message and "unknown_id" in warning.message for warning in warnings
    )
    assert any(
        "missing_table" in warning.message and "m.id" in warning.message for warning in warnings
    )


def test_join_using_is_expanded_to_an_explicit_undirected_equality(
    metadata: DictionaryMetadata,
) -> None:
    facts, warnings, _ = SqlObservedJoinAnalyzer().analyze(
        source("SELECT * FROM cargo c JOIN category k USING (tenant_id)"),
        metadata,
    )

    assert warnings == []
    assert len(facts) == 1
    assert facts[0].join_expression == "c.tenant_id = k.tenant_id"


def test_multi_join_using_is_skipped_when_left_column_ownership_is_ambiguous(
    metadata: DictionaryMetadata,
) -> None:
    facts, warnings, _ = SqlObservedJoinAnalyzer().analyze(
        source(
            "SELECT * FROM cargo c "
            "JOIN category k ON c.category_id = k.id "
            "JOIN cargo_tag t USING (tenant_id)"
        ),
        metadata,
    )

    assert len(facts) == 1
    assert any(item.code == "join_using_unresolved" for item in warnings)


def test_static_join_survives_project_template_fragments(
    metadata: DictionaryMetadata,
) -> None:
    facts, warnings, statement_count = SqlObservedJoinAnalyzer().analyze(
        source(
            """
            SELECT c.id
            FROM cargo c
            LEFT JOIN category k ON c.category_id = k.id
            WHERE 1 = 1
            << AND c.status = :status >>
            """
        ),
        metadata,
    )

    assert statement_count == 1
    assert [(item.left.table_name, item.right.table_name) for item in facts] == [
        ("cargo", "category")
    ]
    assert [item.code for item in warnings] == ["sql_template_fragment_ignored"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM cargo c CROSS JOIN category k",
        "SELECT * FROM cargo c JOIN category k ON c.id > k.id",
        "SELECT * FROM cargo c JOIN category k ON c.id = k.id OR c.tenant_id = k.tenant_id",
        "SELECT * FROM cargo c JOIN category k ON missing_id = k.id",
        "SELECT * FROM cargo c JOIN category k ON c.unknown_column = k.id",
    ],
)
def test_ambiguous_or_non_equality_sql_never_becomes_a_relation(
    metadata: DictionaryMetadata,
    sql: str,
) -> None:
    facts, _, _ = SqlObservedJoinAnalyzer().analyze(source(sql), metadata)

    assert facts == []


def test_context_is_one_hop_undirected_and_keeps_bounded_sql_evidence() -> None:
    repository = InMemoryTableRelationRepository()
    _configure_defaults(repository, "project-1")
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="cargo-service",
        database_key="cargo_db",
        generation_id="generation-1",
    )
    repository.publish(
        build=TableRelationBuildRecord(
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="cargo-service",
            database_key="cargo_db",
            generation_id="generation-1",
            status="building",
            sql_file_count=1,
            statement_count=1,
            relation_count=1,
            warnings=(),
            error_message=None,
            started_at=datetime.now(UTC),
            finished_at=None,
        ),
        relations=[
            TableJoinRelationRecord(
                relation_id="relation-1",
                workspace_id="workspace-1",
                project_id="project-1",
                project_name="cargo-service",
                database_key="cargo_db",
                table_a_schema="cargo",
                table_a_name="cargo",
                table_b_schema="cargo",
                table_b_name="category",
                column_pairs=(("category_id", "id"),),
                evidences=(
                    TableJoinEvidenceRecord(
                        source_path="src/main/resources/sql/cargo.sql",
                        join_expression="c.category_id = k.id",
                        sql_statement=(
                            "SELECT * FROM cargo c JOIN category k ON c.category_id = k.id"
                        ),
                    ),
                ),
            )
        ],
    )
    service = _relation_service(repository)

    result = service.context_for_workspace(
        workspace_id="workspace-1",
        table="category",
        database_key="cargo_db",
        schema="cargo",
    )

    assert result.relation_semantics.directed is False
    assert result.root_table.table_name == "category"
    assert [item.table_name for item in result.related_tables] == ["cargo"]
    assert result.joins[0].directed is False
    assert result.joins[0].column_pairs[0].column_a == "category_id"
    assert result.joins[0].evidence[0].source_path.endswith("cargo.sql")
    assert result.total_relation_count == 1
    assert result.returned_relation_count == 1
    assert result.has_more is False
    assert result.next_offset is None
    assert result.joins[0].evidence_total == 1
    assert result.joins[0].evidence_returned == 1
    assert result.joins[0].evidence_truncated is False
    assert result.detail_level == "full"
    assert result.joins[0].evidence[0].sql_statement is not None

    evidence_result = service.context_for_workspace(
        workspace_id="workspace-1",
        table="category",
        database_key="cargo_db",
        schema="cargo",
        detail_level="evidence",
    )
    assert evidence_result.detail_level == "evidence"
    assert evidence_result.joins[0].evidence[0].source_path.endswith("cargo.sql")
    assert evidence_result.joins[0].evidence[0].join_expression == "c.category_id = k.id"
    assert evidence_result.joins[0].evidence[0].sql_statement is None

    compact_result = service.context_for_workspace(
        workspace_id="workspace-1",
        table="category",
        database_key="cargo_db",
        schema="cargo",
        detail_level="compact",
    )
    assert compact_result.detail_level == "compact"
    assert compact_result.joins[0].evidence == []
    assert compact_result.joins[0].evidence_total == 1
    assert compact_result.joins[0].evidence_returned == 0
    assert compact_result.joins[0].evidence_truncated is True


def test_context_paginates_relations_and_discloses_evidence_truncation() -> None:
    repository = InMemoryTableRelationRepository()
    _configure_defaults(repository, "project-1")
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="cargo-service",
        database_key="cargo_db",
        generation_id="generation-pagination",
    )
    repository.publish(
        build=TableRelationBuildRecord(
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="cargo-service",
            database_key="cargo_db",
            generation_id="generation-pagination",
            status="building",
            sql_file_count=9,
            statement_count=9,
            relation_count=3,
            warnings=(),
            error_message=None,
            started_at=datetime.now(UTC),
            finished_at=None,
        ),
        relations=[
            TableJoinRelationRecord(
                relation_id=f"relation-{index}",
                workspace_id="workspace-1",
                project_id="project-1",
                project_name="cargo-service",
                database_key="cargo_db",
                table_a_schema="cargo",
                table_a_name="hub",
                table_b_schema="cargo",
                table_b_name=f"related_{index}",
                column_pairs=(("id", "hub_id"),),
                evidences=tuple(
                    TableJoinEvidenceRecord(
                        source_path=f"sql/relation_{index}_{evidence_index}.sql",
                        join_expression="h.id = r.hub_id",
                        sql_statement="SELECT * FROM hub h JOIN related r ON h.id = r.hub_id",
                    )
                    for evidence_index in range(3)
                ),
            )
            for index in range(3)
        ],
    )
    service = _relation_service(repository)

    middle_page = service.context_for_workspace(
        workspace_id="workspace-1",
        table="hub",
        database_key="cargo_db",
        schema="cargo",
        detail_level="evidence",
        relation_limit=1,
        relation_offset=1,
        evidence_limit_per_join=2,
    )

    assert middle_page.total_relation_count == 3
    assert middle_page.returned_relation_count == 1
    assert middle_page.has_more is True
    assert middle_page.next_offset == 2
    assert [item.table_name for item in middle_page.related_tables] == ["related_1"]
    assert middle_page.joins[0].evidence_total == 3
    assert middle_page.joins[0].evidence_returned == 2
    assert middle_page.joins[0].evidence_truncated is True

    last_page = service.context_for_workspace(
        workspace_id="workspace-1",
        table="hub",
        database_key="cargo_db",
        schema="cargo",
        relation_limit=1,
        relation_offset=2,
    )
    assert [item.table_name for item in last_page.related_tables] == ["related_2"]
    assert last_page.has_more is False
    assert last_page.next_offset is None


def test_table_list_paginates_without_silently_truncating_after_two_hundred() -> None:
    repository = InMemoryTableRelationRepository()
    _configure_defaults(repository, "project-1")
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="cargo-service",
        database_key="cargo_db",
        generation_id="generation-table-list",
    )
    relations = [
        TableJoinRelationRecord(
            relation_id=f"relation-{index:03d}",
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="cargo-service",
            database_key="cargo_db",
            table_a_schema="cargo",
            table_a_name="hub",
            table_b_schema="cargo",
            table_b_name=f"related_{index:03d}",
            column_pairs=(("id", "hub_id"),),
            evidences=(
                TableJoinEvidenceRecord(
                    source_path=f"sql/relation_{index:03d}.sql",
                    join_expression="h.id = r.hub_id",
                    sql_statement="SELECT 1",
                ),
            ),
        )
        for index in range(204)
    ]
    repository.publish(
        build=TableRelationBuildRecord(
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="cargo-service",
            database_key="cargo_db",
            generation_id="generation-table-list",
            status="building",
            sql_file_count=204,
            statement_count=204,
            relation_count=204,
            warnings=(),
            error_message=None,
            started_at=datetime.now(UTC),
            finished_at=None,
        ),
        relations=relations,
    )
    service = _relation_service(repository)

    first_page = service.list_tables("workspace-1", limit=200)
    last_page = service.list_tables("workspace-1", limit=200, offset=200)

    assert first_page.total == 205
    assert len(first_page.tables) == 200
    assert first_page.has_more is True
    assert first_page.next_offset == 200
    assert last_page.total == 205
    assert len(last_page.tables) == 5
    assert last_page.has_more is False
    assert last_page.next_offset is None
    assert {item.table_name for item in first_page.tables}.isdisjoint(
        item.table_name for item in last_page.tables
    )


def test_warning_diagnostics_are_grouped_filterable_and_keep_expressions() -> None:
    repository = InMemoryTableRelationRepository()
    _configure_defaults(repository, "project-1")
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="cargo-service",
        database_key="cargo_db",
        generation_id="generation-warning",
    )
    warning_records = [
        TableRelationWarningRecord(
            project_id="project-1",
            project_name="cargo-service",
            database_key="cargo_db",
            source_path="sql/cargo.sql",
            code="join_column_unresolved",
            message="字段\x1b[4m身份\x1b[0m无法唯一确认",
            expression="c.category_id = k.id",
            occurrence_count=3,
        ),
        TableRelationWarningRecord(
            project_id="project-1",
            project_name="cargo-service",
            database_key="cargo_db",
            source_path="sql/tag.sql",
            code="join_or_unsupported",
            message="包含 OR 的关联条件无法安全拆分",
            expression="c.tag_id = t.id OR c.tenant_id = t.tenant_id",
        ),
    ]
    repository.publish(
        build=TableRelationBuildRecord(
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="cargo-service",
            database_key="cargo_db",
            generation_id="generation-warning",
            status="building",
            sql_file_count=2,
            statement_count=2,
            relation_count=0,
            warnings=("preview",),
            error_message=None,
            started_at=datetime.now(UTC),
            finished_at=None,
            warning_count=4,
        ),
        relations=[],
        warning_records=warning_records,
    )
    service = _relation_service(repository)

    report = service.list_warnings(
        "workspace-1",
        code="join_column_unresolved",
        query="category_id",
    )

    assert report.total == 3
    assert report.attention_total == 3
    assert report.expected_total == 1
    assert [(item.code, item.disposition, item.count) for item in report.categories] == [
        ("join_column_unresolved", "attention", 3),
        ("join_or_unsupported", "expected", 1),
    ]
    assert [item.model_dump() for item in report.projects] == [
        {
            "project_id": "project-1",
            "project_name": "cargo-service",
            "database_key": "cargo_db",
            "count": 4,
        }
    ]
    assert len(report.warnings) == 1
    assert report.warnings[0].category == "表或字段无法唯一确认"
    assert report.warnings[0].disposition == "attention"
    assert report.warnings[0].message == "字段身份无法唯一确认"
    assert report.warnings[0].expression == "c.category_id = k.id"
    status = service.get_status("workspace-1")
    assert status.warning_count == 4
    assert status.attention_warning_count == 3
    assert status.expected_skip_count == 1
    assert len(status.projects) == 1
    assert status.projects[0].model_dump(
        include={
            "project_id",
            "project_name",
            "database_key",
            "status",
            "warning_count",
            "attention_warning_count",
            "expected_skip_count",
        }
    ) == {
        "project_id": "project-1",
        "project_name": "cargo-service",
        "database_key": "cargo_db",
        "status": "ready",
        "warning_count": 4,
        "attention_warning_count": 3,
        "expected_skip_count": 1,
    }

    expected = service.list_warnings("workspace-1", disposition="expected")
    assert expected.total == 1
    assert [(item.code, item.disposition) for item in expected.warnings] == [
        ("join_or_unsupported", "expected")
    ]
    assert [item.code for item in expected.categories] == ["join_or_unsupported"]

    unknown_project = service.list_warnings(
        "workspace-1",
        project_id="unknown-project",
        disposition="attention",
    )
    assert unknown_project.total == 0
    assert unknown_project.warnings == []
    assert unknown_project.projects[0].project_id == "project-1"

    whitelist = service.replace_sql_whitelist(
        workspace_id="workspace-1",
        project_id="project-1",
        paths=["sql\\cargo.sql", "sql/cargo.sql"],
    )
    assert whitelist.paths == ["sql/cargo.sql"]
    assert whitelist.suggested_paths == []
    assert [rule.code for rule in whitelist.automatic_rules] == [
        "automatic_ddl",
        "automatic_single_table_query",
        "automatic_write_without_query",
    ]

    with pytest.raises(TableRelationServiceError) as invalid_path:
        service.replace_sql_whitelist(
            workspace_id="workspace-1",
            project_id="project-1",
            paths=["../outside.sql"],
        )
    assert invalid_path.value.code == "table_relation_sql_whitelist_invalid_path"


@pytest.mark.parametrize(
    ("code", "classification", "disposition"),
    [
        ("join_derived_relation_unsupported", "safe_skip", "expected"),
        ("join_unqualified_column_unsupported", "safe_skip", "expected"),
        ("join_correlated_reference_unsupported", "safe_skip", "expected"),
        ("join_metadata_unresolved", "metadata", "attention"),
        ("join_metadata_table_not_found", "metadata", "attention"),
        ("join_metadata_column_not_found", "metadata", "attention"),
        ("join_metadata_table_ambiguous", "metadata", "attention"),
        ("join_metadata_column_ambiguous", "metadata", "attention"),
        ("join_alias_unresolved", "source_error", "attention"),
        ("join_alias_ambiguous", "source_error", "attention"),
    ],
)
def test_resolution_warning_codes_have_actionable_dispositions(
    code: str,
    classification: str,
    disposition: str,
) -> None:
    assert TableRelationService._warning_classification(code) == classification
    assert TableRelationService._warning_disposition(code) == disposition


def test_build_error_keeps_sanitized_connector_failure_reason() -> None:
    assert (
        TableRelationService._safe_error(  # noqa: SLF001
            ConnectorManagerError(
                "connection_failed", "database connector could not be initialized"
            )
        )
        == "connection_failed: database connector could not be initialized"
    )


def test_failed_generation_is_fail_closed_and_does_not_return_old_relations() -> None:
    repository = InMemoryTableRelationRepository()
    _configure_defaults(repository, "project-1")
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="cargo-service",
        database_key="cargo_db",
        generation_id="generation-2",
    )
    repository.mark_failed(
        workspace_id="workspace-1",
        project_id="project-1",
        project_name="cargo-service",
        database_key="cargo_db",
        generation_id="generation-2",
        error_message="metadata unavailable",
        warnings=[],
    )
    service = _relation_service(repository)

    status = service.get_status("workspace-1")
    assert status.status == "failed"
    assert len(status.projects) == 1
    assert status.projects[0].status == "failed"
    assert status.projects[0].error_message == "metadata unavailable"

    with pytest.raises(TableRelationServiceError, match="尚未构建完成") as caught:
        service.context_for_workspace(workspace_id="workspace-1", table="cargo")

    assert caught.value.code == "table_relation_index_not_ready"


def test_partial_workspace_returns_only_ready_target_relations() -> None:
    repository = InMemoryTableRelationRepository()
    _configure_defaults(repository, "project-ready", "project-failed")
    now = datetime.now(UTC)
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-ready",
        project_name="ready-service",
        database_key="ready_db",
        generation_id="ready-generation",
    )
    repository.publish(
        build=TableRelationBuildRecord(
            workspace_id="workspace-1",
            project_id="project-ready",
            project_name="ready-service",
            database_key="ready_db",
            generation_id="ready-generation",
            status="building",
            sql_file_count=1,
            statement_count=1,
            relation_count=1,
            warnings=(),
            error_message=None,
            started_at=now,
            finished_at=None,
        ),
        relations=[
            TableJoinRelationRecord(
                relation_id="ready-relation",
                workspace_id="workspace-1",
                project_id="project-ready",
                project_name="ready-service",
                database_key="ready_db",
                table_a_schema="app",
                table_a_name="orders",
                table_b_schema="app",
                table_b_name="customers",
                column_pairs=(("customer_id", "id"),),
                evidences=(
                    TableJoinEvidenceRecord(
                        source_path="orders.sql",
                        join_expression="o.customer_id = c.id",
                        sql_statement=(
                            "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id"
                        ),
                    ),
                ),
            )
        ],
    )
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-failed",
        project_name="failed-service",
        database_key="failed_db",
        generation_id="failed-generation",
    )
    repository.mark_failed(
        workspace_id="workspace-1",
        project_id="project-failed",
        project_name="failed-service",
        database_key="failed_db",
        generation_id="failed-generation",
        error_message="metadata unavailable",
        warnings=[],
    )
    service = _relation_service(repository)

    status = service.get_status("workspace-1")
    assert status.status == "partial"
    assert [(item.project_name, item.status) for item in status.projects] == [
        ("failed-service", "failed"),
        ("ready-service", "ready"),
    ]
    assert status.projects[0].error_message == "metadata unavailable"
    assert status.projects[1].error_message is None
    result = service.context_for_workspace(
        workspace_id="workspace-1",
        table="orders",
        database_key="ready_db",
        schema="app",
    )
    assert [item.table_name for item in result.related_tables] == ["customers"]
    with pytest.raises(TableRelationServiceError) as caught:
        service.context_for_workspace(
            workspace_id="workspace-1",
            table="orders",
            database_key="failed_db",
            schema="app",
        )
    assert caught.value.code == "table_relation_table_not_found"
