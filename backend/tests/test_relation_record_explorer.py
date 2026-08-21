from types import SimpleNamespace

from context_router.database.models import QueryResult
from context_router.schemas.relation_records import RelationRecordTable
from context_router.schemas.table_relations import TableRelationEndpoint, TableRelationView
from context_router.services.relation_record_explorer import (
    RelationRecordExplorerService,
    _endpoints_for_table,
)


def _endpoint(table: str, column: str) -> TableRelationEndpoint:
    return TableRelationEndpoint(
        database_key="db",
        schema_name="app",
        table_name=table,
        column_name=column,
    )


def test_selected_table_side_is_the_only_source_endpoint() -> None:
    child = _endpoint("orders", "route_id")
    parent = _endpoint("routes", "id")
    relation = TableRelationView(
        edge_id="edge-1",
        relation_id="orders.route_id",
        references="routes.id",
        child=child,
        parent=parent,
        direction="outbound",
        code_cardinality="many_to_one",
        code_evidence="single_write",
        db_cardinality="many_to_one",
        db_evidence="measured",
        cross_database=False,
    )

    source, target = _endpoints_for_table(
        relation,
        RelationRecordTable(
            database_key="db",
            schema_name="app",
            table_name="orders",
        ),
    )

    assert source == child
    assert target == parent


def test_relation_field_scan_uses_one_query_and_ignores_non_matching_cells() -> None:
    service = object.__new__(RelationRecordExplorerService)
    statements: list[str] = []

    def execute(_: object, statement: str) -> QueryResult:
        statements.append(statement)
        return QueryResult(
            columns=(),
            rows=[(123, "code-1"), (999, "none")],
        )

    service._execute = execute  # type: ignore[method-assign]
    access = SimpleNamespace(policy=SimpleNamespace(engine="mysql"))
    grouped, truncated = service._matching_keys_by_column(
        access,
        [_endpoint("orders", "route_id"), _endpoint("orders", "order_no")],
        "1",
    )

    assert len(statements) == 1
    assert "`route_id`" in statements[0]
    assert "`order_no`" in statements[0]
    assert "name" not in statements[0]
    assert grouped == {"route_id": [123], "order_no": ["code-1"]}
    assert truncated is False
