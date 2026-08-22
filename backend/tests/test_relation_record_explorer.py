from types import SimpleNamespace

from context_router.database.models import QueryResult
from context_router.schemas.relation_records import (
    RelationRecordCard,
    RelationRecordPage,
    RelationRecordSearchInput,
    RelationRecordTable,
)
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


def test_selected_table_is_the_first_result_card() -> None:
    service = object.__new__(RelationRecordExplorerService)
    relation = TableRelationView(
        edge_id="edge-1",
        relation_id="orders.route_id",
        references="routes.id",
        child=_endpoint("orders", "route_id"),
        parent=_endpoint("routes", "id"),
        direction="outbound",
        code_cardinality="many_to_one",
        code_evidence="single_write",
        db_cardinality="many_to_one",
        db_evidence="measured",
        cross_database=False,
    )
    selected = RelationRecordTable(
        database_key="db",
        schema_name="app",
        table_name="orders",
    )
    source_card = RelationRecordCard(
        kind="source",
        edge_id="source",
        relation_id="source",
        cardinality="unknown",
        source_column="",
        target=selected,
        target_column="",
        matched_columns=["route_id"],
        page=RelationRecordPage(total_rows=1, total_pages=1),
    )
    related_card = RelationRecordCard(
        edge_id="edge-1",
        relation_id="orders.route_id",
        cardinality="many_to_one",
        source_column="route_id",
        target=RelationRecordTable(
            database_key="db",
            schema_name="app",
            table_name="routes",
        ),
        target_column="id",
        page=RelationRecordPage(total_rows=1, total_pages=1),
    )
    service._relations = SimpleNamespace(  # type: ignore[attr-defined]
        get_table_detail=lambda *args, **kwargs: SimpleNamespace(relations=[relation])
    )
    service._resolve = lambda *args, **kwargs: SimpleNamespace()  # type: ignore[method-assign]
    service._source_card_and_keys = (  # type: ignore[method-assign]
        lambda **kwargs: (source_card, {"route_id": [1]})
    )
    service._card = lambda **kwargs: related_card  # type: ignore[method-assign]

    result = service.search(
        workspace_id="workspace",
        request=RelationRecordSearchInput(
            environment="local",
            table=selected,
            keyword="1",
        ),
    )

    assert [card.kind for card in result.cards] == ["source", "related"]
    assert result.cards[0].target.table_name == "orders"
    assert result.cards[1].target.table_name == "routes"
    assert result.source_keys == {"route_id": 1}


def test_source_card_queries_only_registered_relation_columns() -> None:
    service = object.__new__(RelationRecordExplorerService)
    statements: list[str] = []

    def execute(_: object, statement: str) -> QueryResult:
        statements.append(statement)
        return QueryResult(columns=(), rows=[(1, "route-a", "order-9")])

    service._execute = execute  # type: ignore[method-assign]
    service._columns = lambda *args, **kwargs: []  # type: ignore[method-assign]
    service._result_formatter = SimpleNamespace(  # type: ignore[attr-defined]
        format_query=lambda *args, **kwargs: SimpleNamespace(
            as_dict=lambda: {
                "columns": [{"name": "id"}, {"name": "route_id"}, {"name": "order_no"}],
                "rows": [[1, "route-a", "order-9"]],
            }
        )
    )
    access = SimpleNamespace(policy=SimpleNamespace(engine="mysql"))
    identity = RelationRecordTable(
        database_key="db",
        schema_name="app",
        table_name="orders",
    )

    card, keys = service._source_card_and_keys(
        access=access,
        identity=identity,
        endpoints=[_endpoint("orders", "route_id"), _endpoint("orders", "order_no")],
        keyword="route-a",
    )

    assert card.kind == "source"
    assert card.target == identity
    assert card.matched_columns == ["route_id"]
    assert card.page.total_rows == 1
    assert card.page.total_pages == 1
    assert keys == {"route_id": ["route-a"], "order_no": ["order-9"]}
    assert len(statements) == 1
    assert all("`route_id`" in statement and "`order_no`" in statement for statement in statements)
    assert "LIKE" not in statements[0]
    assert "= 'route-a'" in statements[0]
    assert "ORDER BY RAND() LIMIT 1" in statements[0]
    assert all("customer_name" not in statement for statement in statements)


def test_no_exact_source_match_returns_no_cards_or_relation_keys() -> None:
    service = object.__new__(RelationRecordExplorerService)
    service._execute = lambda *args, **kwargs: QueryResult(columns=(), rows=[])  # type: ignore[method-assign]
    service._result_formatter = SimpleNamespace(  # type: ignore[attr-defined]
        format_query=lambda *args, **kwargs: SimpleNamespace(
            as_dict=lambda: {"columns": [{"name": "route_id"}], "rows": []}
        )
    )
    identity = RelationRecordTable(
        database_key="db",
        schema_name="app",
        table_name="orders",
    )

    card, keys = service._source_card_and_keys(
        access=SimpleNamespace(policy=SimpleNamespace(engine="mysql")),
        identity=identity,
        endpoints=[_endpoint("orders", "route_id")],
        keyword="1",
    )

    assert card.page.total_rows == 0
    assert card.rows == []
    assert keys == {}
