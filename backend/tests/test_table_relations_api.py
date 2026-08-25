from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.api.table_relations import router
from context_router.repositories.database_environment_repository import (
    InMemoryDatabaseEnvironmentRepository,
)
from context_router.repositories.table_relation_repository import (
    InMemoryTableRelationRepository,
)
from context_router.repositories.task_repository import TaskRepositoryError
from context_router.repositories.workspace_repository import WorkspaceRepositoryError
from context_router.scripts.seed_table_relations import (
    build_seed_projection,
    load_into_memory,
)
from context_router.services.table_relation_context import TableRelationContextService

WORKSPACE = "workspace-1"
MTP = {"database_key": "c12_mtp_db", "schema_name": "uat_mtp"}


class _WorkspaceRepository:
    def get_workspace(self, workspace_id: str) -> object:
        if workspace_id != WORKSPACE:
            raise WorkspaceRepositoryError("工作空间不存在")
        return object()


class _StubRegistry:
    def get_workspace_snapshot(self, workspace_id: str) -> SimpleNamespace:
        if workspace_id != WORKSPACE:
            raise WorkspaceRepositoryError("工作空间不存在")
        return SimpleNamespace(id=workspace_id, root_path="/repo/java-workspace")


class _UnusedTaskStore:
    def get_task(self, task_id: int) -> object:
        raise TaskRepositoryError("unused")


def _client(*, seeded: bool = True) -> TestClient:
    repository = (
        load_into_memory(build_seed_projection(workspace_id=WORKSPACE))
        if seeded
        else InMemoryTableRelationRepository()
    )
    app = FastAPI()
    app.state.table_relation_repository = repository
    app.state.workspace_repository = _WorkspaceRepository()
    environments = InMemoryDatabaseEnvironmentRepository()
    environments.upsert_environment(
        workspace_id=WORKSPACE,
        environment="uat",
        display_name="UAT",
        sort_order=20,
    )
    app.state.database_environment_repository = environments
    app.state.table_relation_context_service = TableRelationContextService(
        registry=_StubRegistry(),  # type: ignore[arg-type]
        task_repository=_UnusedTaskStore(),  # type: ignore[arg-type]
        reader=repository,
    )
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_status_returns_the_published_generation() -> None:
    with _client() as client:
        response = client.get(f"/api/workspaces/{WORKSPACE}/table-relations/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["generation"]["status"] == "published"
    assert payload["database_keys"] == [
        "c12_admin_db",
        "c12_auth_db",
        "c12_mtp_db",
        "c12_park_db",
        "c12_portal_db",
        "c12_rcc_db",
        "c12_wms_db",
    ]
    assert WORKSPACE in payload["rebuild_command"]


def test_table_list_respects_the_only_related_flag() -> None:
    with _client() as client:
        related = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/tables",
            params={"only_related": "true"},
        ).json()
        everything = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/tables",
            params={"only_related": "false"},
        ).json()

    assert related["returned_count"] < everything["returned_count"]
    assert all(table["relation_count"] > 0 for table in related["tables"])


def test_table_detail_returns_a_flat_list_carrying_both_verdicts() -> None:
    with _client() as client:
        response = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table",
            params={**MTP, "table_name": "cs_dsly_highway_cargo"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "groups" not in payload
    assert payload["relation_count"] == len(payload["relations"]) == 5

    by_id = {relation["relation_id"]: relation for relation in payload["relations"]}
    # The disagreement the page exists to surface, all the way through the wire.
    disagreeing = by_id["cs_dsly_highway_cargo.carrier_order_no"]
    assert disagreeing["references"] == "cs_dsly_highway_carrier_order.carrier_order_no"
    assert disagreeing["code_cardinality"] == "many_to_one"
    assert disagreeing["code_evidence"] == "batch_allowed"
    assert disagreeing["db_cardinality"] == "one_to_one"
    assert disagreeing["db_evidence"] == "measured"


def test_a_relation_nobody_could_measure_is_serialised_rather_than_dropped() -> None:
    with _client() as client:
        payload = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table",
            params={**MTP, "table_name": "cs_dsly_shipping_cargo"},
        ).json()

    relation = payload["relations"][0]
    assert relation["db_cardinality"] == "unknown"
    assert relation["db_evidence"] == "no_data"
    assert relation["code_cardinality"] == "one_to_one"


def test_a_dead_column_is_counted_but_not_listed() -> None:
    with _client() as client:
        payload = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table",
            params={**MTP, "table_name": "cs_dsly_order_entrusted_order_relate"},
        ).json()

    assert payload["hidden_count"] == 1
    relation_ids = [relation["relation_id"] for relation in payload["relations"]]
    assert "cs_dsly_order_entrusted_order_relate.entrusted_order_id" not in relation_ids
    assert "cs_dsly_order_entrusted_order_relate.entrusted_order_no" in relation_ids
    assert "cs_dsly_order_entrusted_order_relate.route_no" in relation_ids


def _edge_id(client: TestClient, table_name: str, relation_id: str) -> str:
    payload = client.get(
        f"/api/workspaces/{WORKSPACE}/table-relations/table",
        params={**MTP, "table_name": table_name},
    ).json()
    return next(
        relation["edge_id"]
        for relation in payload["relations"]
        if relation["relation_id"] == relation_id
    )


def test_relation_evidence_carries_the_counts_and_the_queries_behind_them() -> None:
    with _client() as client:
        edge_id = _edge_id(
            client,
            "cs_dsly_highway_cargo",
            "cs_dsly_highway_cargo.cargo_id",
        )
        response = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/relation",
            params={**MTP, "table_name": "cs_dsly_highway_cargo", "edge_id": edge_id},
        )

    assert response.status_code == 200
    payload = response.json()
    # The row's own verdict, unchanged, so opening it cannot appear to contradict it.
    assert payload["relation"]["relation_id"] == "cs_dsly_highway_cargo.cargo_id"
    assert payload["relation"]["db_cardinality"] == "many_to_one"
    assert payload["measurement"]["child_distinct_keys"] == 51
    assert payload["measurement"]["orphan_keys"] == 27

    outcomes = {item["key"]: item["outcome"] for item in payload["checks"]}
    assert outcomes == {
        "cardinality": "confirmed",
        "parent_unique": "confirmed",
        "orphan": "attention",
    }
    assert all(item["sql"] for item in payload["checks"])


def test_relation_evidence_is_stated_from_the_table_it_was_opened_from() -> None:
    with _client() as client:
        edge_id = _edge_id(
            client,
            "cs_dsly_highway_cargo",
            "cs_dsly_highway_cargo.carrier_order_no",
        )
        from_child = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/relation",
            params={**MTP, "table_name": "cs_dsly_highway_cargo", "edge_id": edge_id},
        ).json()
        from_parent = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/relation",
            params={
                **MTP,
                "table_name": "cs_dsly_highway_carrier_order",
                "edge_id": edge_id,
            },
        ).json()

    assert from_child["relation"]["code_cardinality"] == "many_to_one"
    assert from_parent["relation"]["code_cardinality"] == "one_to_many"
    # Only the reading moves. The evidence is a property of the relation itself.
    assert from_child["measurement"] == from_parent["measurement"]
    assert from_child["relation"]["db_evidence"] == from_parent["relation"]["db_evidence"]


def test_relation_evidence_for_an_unrelated_table_is_reported_as_missing() -> None:
    with _client() as client:
        edge_id = _edge_id(
            client,
            "cs_dsly_highway_cargo",
            "cs_dsly_highway_cargo.cargo_id",
        )
        response = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/relation",
            params={**MTP, "table_name": "cs_dsly_basic_port", "edge_id": edge_id},
        )

    assert response.status_code == 404


def test_relation_evidence_serialises_the_places_its_code_verdict_came_from() -> None:
    """The code dimension used to reach the client as a bare label.

    It now arrives with the places it was read off, and with the role and
    implication of each computed server-side, so a client cannot be the thing
    that decides whether a ``groupingBy`` writes rows.
    """
    with _client() as client:
        edge_id = _edge_id(
            client,
            "cs_dsly_highway_cargo",
            "cs_dsly_highway_cargo.dispatch_order_no",
        )
        payload = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/relation",
            params={**MTP, "table_name": "cs_dsly_highway_cargo", "edge_id": edge_id},
        ).json()

    assert payload["relation"]["code_evidence"] == "enforced"
    sites = payload["code_sites"]
    assert [(site["kind"], site["role"]) for site in sites] == [
        ("fresh_key_per_row", "write"),
        ("strict_to_map", "read"),
    ]
    assert all("SequenceClient" in site["snippet"] for site in sites[:1])
    assert all(site["file_path"].startswith("backend/c12-mtp/") for site in sites)


def test_a_relation_with_no_recorded_sites_says_so_by_omission() -> None:
    """Silence has to be distinguishable from "there is nothing to find".

    An empty list beside conclusive evidence means nobody has written the places
    down yet; ``code_evidence`` is where "looked, found no write path" is said.
    """
    with _client() as client:
        edge_id = _edge_id(
            client,
            "cs_dsly_order_entrusted_order_relate",
            "cs_dsly_order_entrusted_order_relate.entrusted_order_no",
        )
        payload = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/relation",
            params={
                **MTP,
                "table_name": "cs_dsly_order_entrusted_order_relate",
                "edge_id": edge_id,
            },
        ).json()

    assert payload["code_sites"] == []
    assert payload["relation"]["code_evidence"] == "batch_allowed"


def test_table_writes_serialise_the_persist_calls_of_the_selected_table() -> None:
    with _client() as client:
        cargo = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table/writes",
            params={**MTP, "table_name": "cs_dsly_highway_cargo"},
        )
        park = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table/writes",
            params={**MTP, "table_name": "cs_dsly_highway_park_appointment"},
        )

    assert cargo.status_code == 200
    payload = cargo.json()
    assert [site["method_name"] for site in payload["writes"]] == [
        "batchCreateCarrierOrder",
        "batchDispatchOrder",
    ]
    assert "constraint" not in payload
    assert "code_sites" not in payload
    assert [site["method_name"] for site in park.json()["writes"]] == [
        "report",
        "reappoint",
    ]


def test_table_updates_serialise_the_persist_calls_of_the_selected_table() -> None:
    with _client() as client:
        cargo = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table/updates",
            params={**MTP, "table_name": "cs_dsly_highway_cargo"},
        )
        park = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table/updates",
            params={**MTP, "table_name": "cs_dsly_highway_park_appointment"},
        )

    assert cargo.status_code == 200
    payload = cargo.json()
    assert [site["method_name"] for site in payload["updates"]] == [
        "batchDispatchOrder",
        "redispatch",
        "setLoadQuantity",
        "setCargoQuantity",
        "modifyCargoQuantity",
    ]
    assert "writes" not in payload
    assert [site["method_name"] for site in park.json()["updates"]] == [
        "edit",
        "updateAuditStatus",
        "updateAccessTime",
    ]


def test_runtime_environment_query_does_not_change_the_workspace_snapshot() -> None:
    with _client() as client:
        response = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/tables",
            params={"environment": "prod"},
        )

    assert response.status_code == 200
    assert response.json()["generation"]["environment"] == "uat"


def test_unknown_workspace_is_reported_as_missing() -> None:
    with _client() as client:
        response = client.get("/api/workspaces/nope/table-relations/status")

    assert response.status_code == 404
    assert response.json()["detail"] == "工作空间不存在"


def test_unknown_table_is_reported_as_missing() -> None:
    with _client() as client:
        response = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table",
            params={**MTP, "table_name": "cs_dsly_missing"},
        )

    assert response.status_code == 404


def test_workspace_without_a_generation_returns_an_empty_projection() -> None:
    with _client(seeded=False) as client:
        status_response = client.get(f"/api/workspaces/{WORKSPACE}/table-relations/status")
        tables_response = client.get(f"/api/workspaces/{WORKSPACE}/table-relations/tables")
        detail_response = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table",
            params={**MTP, "table_name": "cs_dsly_highway_cargo"},
        )

    assert status_response.json()["generation"] is None
    assert tables_response.json()["tables"] == []
    assert detail_response.status_code == 404


def test_mcp_preview_returns_the_agent_projection_for_one_table() -> None:
    with _client() as client:
        response = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table/mcp",
            params={**MTP, "table_name": "cs_bt_departure_plan", "mode": "full"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool"] == "read_table_relations"
    assert payload["arguments"]["tables"] == ["cs_bt_departure_plan"]
    entry = payload["result"]["tables"][0]
    assert entry["table"]["name"] == "cs_bt_departure_plan"
    assert entry["writes"]
    assert entry["updates"]
    assert entry["relations"]
    assert entry["relations"][0]["evidence"]["checks"]


def test_mcp_preview_defaults_to_relations_without_optional_arguments() -> None:
    with _client() as client:
        response = client.get(
            f"/api/workspaces/{WORKSPACE}/table-relations/table/mcp",
            params={**MTP, "table_name": "cs_bt_departure_plan"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["arguments"] == {
        "task_id": "<from prepare_task_context>",
        "tables": ["cs_bt_departure_plan"],
        "database": "c12_mtp_db",
    }
    entry = payload["result"]["tables"][0]
    assert entry["relations"]
    assert "evidence" not in entry["relations"][0]
    assert "writes" not in entry
    assert "updates" not in entry
