"""Tests for the task-scoped MCP projection of table relations.

The service fixtures reuse the real seed declaration, so the rows an agent
receives are asserted against the same data the page renders. The MCP layer is
tested separately with a recording fake, the same way the other tools are.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from context_router.mcp_server import create_context_router_mcp
from context_router.repositories.table_relation_repository import (
    InMemoryTableRelationRepository,
    TableRelationGenerationRecord,
    TableRelationTableRecord,
)
from context_router.repositories.task_repository import TaskRecord, TaskRepositoryError
from context_router.scripts.seed_table_relations import (
    build_seed_projection,
    load_into_memory,
)
from context_router.services.project_registry import ProjectRegistryError
from context_router.services.table_relation_context import (
    TableRelationContextError,
    TableRelationContextService,
)

WORKSPACE = "workspace-under-test"
JAVA_ROOT = Path("/repo/java-workspace")
COCKPIT_DATA_SERVICE = (
    "backend/c12-portal/c12-portal-biz/src/main/java/com/chinaservices/dsly"
    "/member/module/cockpit/service/CockpitDataService.java"
)


def task_record(
    *,
    scope: str = "workspace",
    workspace_id: str | None = WORKSPACE,
    database_environment: str | None = "uat",
) -> TaskRecord:
    return TaskRecord(
        id=7,
        project_id=None,
        project_key="workspace-key",
        project_name="工作空间",
        task="表关联上下文测试",
        cwd="/tmp/anywhere",
        agent_name="tester",
        created_at=datetime.now(UTC),
        scope=scope,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        workspace_key="workspace-key",
        database_environment=database_environment,
    )


class StubTaskStore:
    def __init__(self, record: TaskRecord | None) -> None:
        self._record = record

    def get_task(self, task_id: int) -> TaskRecord:
        if self._record is None:
            raise TaskRepositoryError("任务不存在")
        assert task_id == self._record.id
        return self._record


class StubRegistry:
    def __init__(self, *, available: bool = True) -> None:
        self._available = available

    def get_workspace_snapshot(self, workspace_id: str) -> SimpleNamespace:
        if not self._available or workspace_id != WORKSPACE:
            raise ProjectRegistryError("任务绑定的工作空间不存在")
        return SimpleNamespace(
            id=WORKSPACE,
            root_path=str(JAVA_ROOT),
            resolved_root_path=Path("/container-mount/java-workspace"),
        )

    def get_workspace_snapshot_for_task(
        self,
        *,
        workspace_id: str | None,
        workspace_key: str | None,
    ) -> SimpleNamespace:
        if not self._available:
            raise ProjectRegistryError("任务绑定的工作空间不存在")
        assert workspace_id == WORKSPACE
        return self.get_workspace_snapshot(WORKSPACE)


@pytest.fixture
def service() -> TableRelationContextService:
    projection = build_seed_projection(workspace_id=WORKSPACE, generation_id="generation-1")
    return TableRelationContextService(
        registry=StubRegistry(),  # type: ignore[arg-type]
        task_repository=StubTaskStore(task_record()),  # type: ignore[arg-type]
        reader=load_into_memory(projection),
    )


def single_entry(result: dict[str, object]) -> dict[str, object]:
    entries = result["tables"]
    assert isinstance(entries, list) and len(entries) == 1
    return entries[0]


def test_read_inherits_the_task_environment_after_tool_defaults_are_removed() -> None:
    projection = build_seed_projection(workspace_id=WORKSPACE, generation_id="generation-default")
    configured = TableRelationContextService(
        registry=StubRegistry(),  # type: ignore[arg-type]
        task_repository=StubTaskStore(task_record(database_environment="uat")),  # type: ignore[arg-type]
        reader=load_into_memory(projection),
    )

    result = configured.read(task_id=7, tables=["cs_portal_cockpit_city_flow"])

    assert result["environment"] == "uat"


def test_read_for_workspace_wraps_the_mcp_projection(service: TableRelationContextService) -> None:
    preview = service.read_for_workspace(
        workspace_id=WORKSPACE,
        database_key="c12_portal_db",
        schema_name="uat_portal",
        table_name="cs_portal_cockpit_city_flow",
        mode="full",
    )

    assert preview["tool"] == "read_table_relations"
    assert preview["arguments"]["tables"] == ["cs_portal_cockpit_city_flow"]
    assert preview["arguments"]["sections"] == ["relations", "writes", "updates"]
    assert preview["arguments"]["evidence"] == "all"
    result = preview["result"]
    assert isinstance(result, dict)
    assert result["environment"] == "uat"
    entry = result["tables"][0]
    assert entry["table"]["name"] == "cs_portal_cockpit_city_flow"
    assert entry["relations"][0]["evidence"]["checks"]


def test_read_for_workspace_defaults_to_the_real_compact_call(
    service: TableRelationContextService,
) -> None:
    preview = service.read_for_workspace(
        workspace_id=WORKSPACE,
        database_key="c12_portal_db",
        schema_name="uat_portal",
        table_name="cs_portal_cockpit_city_flow",
    )

    assert preview["arguments"] == {
        "task_id": "<from prepare_task_context>",
        "tables": ["cs_portal_cockpit_city_flow"],
        "database": "c12_portal_db",
    }
    entry = preview["result"]["tables"][0]
    assert entry["relations"]
    assert "evidence" not in entry["relations"][0]
    assert "writes" not in entry
    assert "updates" not in entry


def test_default_read_returns_only_structured_relations_by_bare_table_name(
    service: TableRelationContextService,
) -> None:
    result = service.read(task_id=7, tables=["cs_portal_cockpit_city_flow"])

    assert result["environment"] == "uat"
    entry = single_entry(result)
    assert entry["table"] == {
        "database": "c12_portal_db",
        "schema": "uat_portal",
        "name": "cs_portal_cockpit_city_flow",
    }

    relations = entry["relations"]
    assert isinstance(relations, list)
    assert relations[0]["child"].endswith("cs_portal_cockpit_city_flow_cargo.flow_id")
    assert relations[0]["parent"].endswith("cs_portal_cockpit_city_flow.id")
    assert relations[0]["role"] == "parent"
    assert "relation_count" not in entry
    assert "writes" not in entry
    assert "updates" not in entry
    assert result["generation"]["revision"] > 0


def test_entry_points_are_grouped_by_file_under_one_workspace_root(
    service: TableRelationContextService,
) -> None:
    result = service.read(
        task_id=7,
        tables=["cs_portal_cockpit_city_flow"],
        sections=["writes"],
    )

    # The root is stated once for the whole response, and each group carries the
    # workspace-relative file, so an agent joins the two rather than reading the
    # same absolute prefix once per method.
    assert result["workspace_root"] == str(JAVA_ROOT)
    groups = {group["file"]: group for group in single_entry(result)["writes"]}
    assert COCKPIT_DATA_SERVICE in groups
    assert str(JAVA_ROOT / groups[COCKPIT_DATA_SERVICE]["file"]) == str(
        JAVA_ROOT / COCKPIT_DATA_SERVICE
    )
    assert "class" not in groups[COCKPIT_DATA_SERVICE]


def test_several_methods_of_one_file_share_a_single_group() -> None:
    projection = build_seed_projection(workspace_id=WORKSPACE, generation_id="generation-1")
    service = TableRelationContextService(
        registry=StubRegistry(),  # type: ignore[arg-type]
        task_repository=StubTaskStore(task_record()),  # type: ignore[arg-type]
        reader=load_into_memory(projection),
    )

    result = service.read(
        task_id=7,
        tables=["cs_bt_departure_plan"],
        sections=["updates"],
        database="c12_mtp_db",
    )

    groups = single_entry(result)["updates"]
    files = [group["file"] for group in groups]
    # One group per file even though this table is updated from many methods of
    # the same service, which is the whole point of grouping.
    assert len(files) == len(set(files))
    service_group = next(
        group for group in groups if group["file"].endswith("/BtDeparturePlanService.java")
    )
    assert len(service_group["methods"]) > 1
    assert {"publish", "cancel"} <= {method["name"] for method in service_group["methods"]}


def test_one_settled_cardinality_reaches_the_row_with_a_flag_when_readings_differ(
    service: TableRelationContextService,
) -> None:
    result = service.read(
        task_id=7,
        tables=["cs_portal_cockpit_city_flow"],
        sections=["relations"],
    )

    row = single_entry(result)["relations"][0]
    # Cockpit tables are empty on UAT, so the data reading cannot confirm the code
    # reading. The row states the code verdict and admits it is soft, without
    # spending four keys on explaining a data-quality finding nobody can act on.
    assert row["cardinality"] == "1:N"
    assert row["uncertain"] is True
    assert "code_cardinality" not in row
    assert "db_evidence" not in row
    assert "verdict_conflict" not in row
    assert "evidence" not in row


def test_agreeing_readings_leave_no_uncertain_flag() -> None:
    projection = build_seed_projection(workspace_id=WORKSPACE, generation_id="generation-1")
    service = TableRelationContextService(
        registry=StubRegistry(),  # type: ignore[arg-type]
        task_repository=StubTaskStore(task_record()),  # type: ignore[arg-type]
        reader=load_into_memory(projection),
    )

    result = service.read(
        task_id=7,
        tables=["cs_bt_departure_plan"],
        sections=["relations"],
        database="c12_mtp_db",
    )

    rows = single_entry(result)["relations"]
    settled = [row for row in rows if "uncertain" not in row]
    assert settled, "这张表应当有两个维度一致的关系"
    for row in settled:
        assert row["cardinality"] in {"1:1", "1:N", "N:1"}


def test_evidence_all_adds_measurement_checks_and_code_sites(
    service: TableRelationContextService,
) -> None:
    result = service.read(
        task_id=7,
        tables=["cs_portal_cockpit_city_flow"],
        sections=["relations"],
        evidence="all",
    )

    row = single_entry(result)["relations"][0]
    evidence = row["evidence"]
    # The per-dimension breakdown the row no longer carries lives here, so asking
    # for evidence recovers everything the collapsed verdict left out.
    assert evidence["code_cardinality"] == "1:N"
    assert evidence["code_evidence"] == "batch_allowed"
    assert evidence["db_cardinality"] == "unknown"
    assert evidence["db_evidence"] == "no_data"
    measurement = evidence["measurement"]
    assert set(measurement) == {
        "child_table_rows",
        "child_rows_with_value",
        "child_distinct_keys",
        "parent_rows_with_value",
        "parent_distinct_keys",
        "orphan_keys",
    }
    checks = evidence["checks"]
    assert isinstance(checks, list) and checks
    for check in checks:
        assert check["key"] in {"cardinality", "parent_unique", "orphan", "key_kind"}
        assert check["outcome"] in {"confirmed", "attention", "inconclusive"}
        assert isinstance(check["sql"], str) and "SELECT" in check["sql"].upper()
    for site in evidence["code_sites"]:
        assert site["method"]
        assert "class" not in site
        assert not site["file"].startswith("/")
        assert site["implies"] in {"1:1", "1:N", "N:1", "unknown"}
        assert "snippet" not in site


def test_evidence_uncertain_expands_only_soft_verdicts(
    service: TableRelationContextService,
) -> None:
    result = service.read(
        task_id=7,
        tables=["cs_bt_departure_plan"],
        database="c12_mtp_db",
        evidence="uncertain",
    )

    rows = single_entry(result)["relations"]
    expanded = [row for row in rows if "evidence" in row]
    compact = [row for row in rows if "evidence" not in row]
    assert expanded, "至少一条软结论应展开证据"
    assert compact, "已确认的关系应保持精简"
    assert all(row.get("uncertain") is True for row in expanded)
    assert all("uncertain" not in row for row in compact)


def test_unresolved_relations_are_reported_as_a_nonzero_warning(
    service: TableRelationContextService,
) -> None:
    result = service.read(
        task_id=7,
        tables=["cs_dsly_order_entrusted_order_relate"],
        database="c12_mtp_db",
    )

    entry = single_entry(result)
    assert entry["warnings"] == [{"code": "unresolved_relations", "count": 1}]
    assert "hidden_count" not in entry


def test_batch_read_isolates_per_table_failures(
    service: TableRelationContextService,
) -> None:
    result = service.read(
        task_id=7,
        tables=[
            "cs_portal_cockpit_city_flow",
            "cs_no_such_table_anywhere",
            "cs_portal_cockpit_cargo_summary",
        ],
        sections=["relations"],
    )

    entries = result["tables"]
    assert isinstance(entries, list) and len(entries) == 3
    assert entries[0]["table"]["name"] == "cs_portal_cockpit_city_flow"
    assert entries[1]["table_request"] == "cs_no_such_table_anywhere"
    assert entries[1]["error"]["code"] == "table_relation_table_not_found"
    assert entries[2]["table"]["name"] == "cs_portal_cockpit_cargo_summary"


def test_sections_limit_what_is_fetched(service: TableRelationContextService) -> None:
    result = service.read(
        task_id=7,
        tables=["cs_portal_cockpit_city_flow"],
        sections=["writes"],
    )

    entry = single_entry(result)
    assert "writes" in entry
    assert "relations" not in entry
    assert "updates" not in entry


def test_invalid_section_and_empty_tables_are_rejected(
    service: TableRelationContextService,
) -> None:
    with pytest.raises(TableRelationContextError) as excinfo:
        service.read(
            task_id=7,
            tables=["cs_portal_cockpit_city_flow"],
            sections=["snippets"],
        )
    assert excinfo.value.code == "invalid_relation_section"

    with pytest.raises(TableRelationContextError) as excinfo:
        service.read(
            task_id=7,
            tables=["cs_portal_cockpit_city_flow"],
            evidence="verbose",  # type: ignore[arg-type]
        )
    assert excinfo.value.code == "invalid_relation_evidence"

    with pytest.raises(TableRelationContextError) as excinfo:
        service.read(task_id=7, tables=["  ", ""])
    assert excinfo.value.code == "invalid_relation_tables"


def test_missing_table_reports_close_names(service: TableRelationContextService) -> None:
    result = service.read(task_id=7, tables=["cs_portal_cockpit_city"])
    entry = single_entry(result)
    assert entry["error"]["code"] == "table_relation_table_not_found"
    assert "cs_portal_cockpit_city_flow" in entry["error"]["message"]


def test_same_table_name_in_two_databases_requires_database() -> None:
    reader = InMemoryTableRelationRepository()
    reader.add_generation(
        TableRelationGenerationRecord(
            id="generation-1",
            workspace_id=WORKSPACE,
            environment="uat",
            status="published",
            revision=1,
        ),
        tables=[
            TableRelationTableRecord("generation-1", "db_a", "schema_a", "cs_shared"),
            TableRelationTableRecord("generation-1", "db_b", "schema_b", "cs_shared"),
        ],
    )
    service = TableRelationContextService(
        registry=StubRegistry(),  # type: ignore[arg-type]
        task_repository=StubTaskStore(task_record()),  # type: ignore[arg-type]
        reader=reader,
    )

    ambiguous = single_entry(service.read(task_id=7, tables=["cs_shared"]))
    assert ambiguous["error"]["code"] == "table_relation_table_ambiguous"

    entry = single_entry(service.read(task_id=7, tables=["cs_shared"], database="db_a"))
    assert entry["table"] == {"database": "db_a", "schema": "schema_a", "name": "cs_shared"}
    assert entry["relations"] == []
    assert "writes" not in entry
    assert "updates" not in entry


def test_search_matches_substring_and_sorts_by_relation_count(
    service: TableRelationContextService,
) -> None:
    result = service.search(task_id=7, query="cockpit")

    assert result["environment"] == "uat"
    tables = result["tables"]
    assert isinstance(tables, list) and tables
    names = [item["name"] for item in tables]
    assert all("cockpit" in name for name in names)
    # only_related defaults to true: every hit draws at least one relation, and
    # the KPI snapshot tables without edges stay out.
    counts = [item["relation_count"] for item in tables]
    assert all(count > 0 for count in counts)
    assert counts == sorted(counts, reverse=True)
    assert "cs_portal_cockpit_kpi" not in names

    everything = service.search(task_id=7, query="cockpit", only_related=False)
    assert "cs_portal_cockpit_kpi" in [item["name"] for item in everything["tables"]]
    assert everything["truncated"] is False


def test_search_scopes_to_database_and_respects_limit(
    service: TableRelationContextService,
) -> None:
    result = service.search(task_id=7, database="c12_portal_db", only_related=False, limit=3)

    assert len(result["tables"]) == 3
    assert result["truncated"] is True
    assert all(item["database"] == "c12_portal_db" for item in result["tables"])


def test_project_scoped_task_is_rejected() -> None:
    service = TableRelationContextService(
        registry=StubRegistry(),  # type: ignore[arg-type]
        task_repository=StubTaskStore(  # type: ignore[arg-type]
            task_record(scope="project", workspace_id=None)
        ),
        reader=InMemoryTableRelationRepository(),
    )
    with pytest.raises(TableRelationContextError) as excinfo:
        service.read(task_id=7, tables=["cs_anything"])
    assert excinfo.value.code == "workspace_task_required"
    with pytest.raises(TableRelationContextError) as excinfo:
        service.search(task_id=7, query="cs")
    assert excinfo.value.code == "workspace_task_required"


def test_unknown_task_and_missing_generation_have_distinct_codes() -> None:
    unknown_task = TableRelationContextService(
        registry=StubRegistry(),  # type: ignore[arg-type]
        task_repository=StubTaskStore(None),  # type: ignore[arg-type]
        reader=InMemoryTableRelationRepository(),
    )
    with pytest.raises(TableRelationContextError) as excinfo:
        unknown_task.read(task_id=7, tables=["cs_anything"])
    assert excinfo.value.code == "task_not_found"

    no_generation = TableRelationContextService(
        registry=StubRegistry(),  # type: ignore[arg-type]
        task_repository=StubTaskStore(task_record()),  # type: ignore[arg-type]
        reader=InMemoryTableRelationRepository(),
    )
    with pytest.raises(TableRelationContextError) as excinfo:
        no_generation.read(task_id=7, tables=["cs_anything"])
    assert excinfo.value.code == "table_relation_generation_missing"
    with pytest.raises(TableRelationContextError) as excinfo:
        no_generation.search(task_id=7)
    assert excinfo.value.code == "table_relation_generation_missing"


class RecordingTableRelationContextService:
    def __init__(self) -> None:
        self.read_arguments: dict[str, object] = {}
        self.search_arguments: dict[str, object] = {}

    def read(self, **arguments: object) -> dict[str, object]:
        self.read_arguments = arguments
        return {"environment": "local", "tables": []}

    def search(self, **arguments: object) -> dict[str, object]:
        self.search_arguments = arguments
        return {
            "environment": "local",
            "truncated": False,
            "tables": [],
        }


class UnusedService:
    def prepare(self, **_: object) -> None:
        raise AssertionError("table relation tools must not call prepare")

    def read(self, **_: object) -> None:
        raise AssertionError("table relation tools must not call document read")


def test_mcp_tools_forward_only_task_scoped_arguments() -> None:
    document_service = UnusedService()
    relations = RecordingTableRelationContextService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        table_relation_context_service=relations,  # type: ignore[arg-type]
    )

    asyncio.run(
        server.call_tool(
            "read_table_relations",
            {
                "task_id": 7,
                "tables": ["cs_portal_cockpit_city_flow"],
                "sections": ["writes"],
                "evidence": "all",
            },
        )
    )
    assert relations.read_arguments == {
        "task_id": 7,
        "environment": None,
        "tables": ["cs_portal_cockpit_city_flow"],
        "sections": ["writes"],
        "database": None,
        "evidence": "all",
    }

    asyncio.run(
        server.call_tool(
            "search_relation_tables",
            {"task_id": 7, "query": "cockpit", "limit": 20},
        )
    )
    assert relations.search_arguments == {
        "task_id": 7,
        "environment": None,
        "query": "cockpit",
        "database": None,
        "only_related": True,
        "limit": 20,
    }


def test_mcp_tools_report_disabled_without_service() -> None:
    document_service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
    )

    with pytest.raises(ToolError, match="table_relations_disabled"):
        asyncio.run(
            server.call_tool(
                "read_table_relations",
                {"task_id": 7, "tables": ["cs_portal_cockpit_city_flow"]},
            )
        )
    with pytest.raises(ToolError, match="table_relations_disabled"):
        asyncio.run(server.call_tool("search_relation_tables", {"task_id": 7}))
