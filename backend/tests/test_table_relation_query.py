"""Query-layer tests for the table relation projection.

The fixtures reuse the seed declaration the page is demonstrated with, so these
tests assert against the very data a user clicks through — and because that seed
is a set of real UAT measurements, the fixtures also pin the states the two
dimensions can actually be found in rather than states someone imagined.
"""

from __future__ import annotations

import re

import pytest

from context_router.repositories.table_relation_repository import (
    InMemoryTableRelationRepository,
)
from context_router.schemas.table_relations import (
    TableRelationCheck,
    TableRelationDetail,
    TableRelationEndpoint,
    TableRelationMeasurement,
    TableRelationTableDetail,
    TableRelationView,
)
from context_router.scripts.seed_table_relations import (
    SEED_EDGES,
    SEED_TABLES,
    SeedProjection,
    build_seed_projection,
    load_into_memory,
)
from context_router.services.table_relation_probe_sql import (
    TableRelationProbeError,
    cardinality_sql,
)
from context_router.services.table_relation_query import (
    TableRelationNotFoundError,
    TableRelationQueryService,
)
from context_router.services.table_relation_rules import (
    LOW_SAMPLE_ROW_THRESHOLD,
    check_counts,
    check_sites,
    check_update_site,
    check_verdict,
    check_write_site,
    db_verdict_from_counts,
    flip_cardinality,
    is_common_column,
    is_dead_column,
)

WORKSPACE = "workspace-under-test"
MTP = ("c12_mtp_db", "uat_mtp")


@pytest.fixture
def projection() -> SeedProjection:
    return build_seed_projection(workspace_id=WORKSPACE, generation_id="generation-1")


@pytest.fixture
def service(projection: SeedProjection) -> TableRelationQueryService:
    return TableRelationQueryService(reader=load_into_memory(projection))


def detail(
    service: TableRelationQueryService,
    table_name: str,
    *,
    database_key: str = MTP[0],
    schema_name: str = MTP[1],
) -> TableRelationTableDetail:
    return service.get_table_detail(
        WORKSPACE,
        database_key=database_key,
        schema_name=schema_name,
        table_name=table_name,
    )


def row(view: TableRelationTableDetail, relation_id: str) -> TableRelationView:
    match = [item for item in view.relations if item.relation_id == relation_id]
    assert len(match) == 1, f"{relation_id} 应当只出现一次，实际 {len(match)} 次"
    return match[0]


def evidence(
    service: TableRelationQueryService,
    table_name: str,
    edge_id: str,
    *,
    database_key: str = MTP[0],
    schema_name: str = MTP[1],
) -> TableRelationDetail:
    return service.get_relation_detail(
        WORKSPACE,
        database_key=database_key,
        schema_name=schema_name,
        table_name=table_name,
        edge_id=edge_id,
    )


def opened(
    service: TableRelationQueryService,
    table_name: str,
    relation_id: str,
) -> TableRelationDetail:
    """The detail as a user reaches it: by clicking a row of a table's list."""
    return evidence(service, table_name, row(detail(service, table_name), relation_id).edge_id)


def check(view: TableRelationDetail, key: str) -> TableRelationCheck:
    match = [item for item in view.checks if item.key == key]
    assert len(match) == 1, f"体检项 {key} 应当只出现一次，实际 {len(match)} 次"
    return match[0]


def test_the_list_is_flat_and_ordered_by_the_relation_identity(
    service: TableRelationQueryService,
) -> None:
    view = detail(service, "cs_dsly_highway_cargo")

    # Five foreign keys on one table, ordered by the identity each row shows, so
    # the order cannot shift when a verdict is re-measured.
    assert [item.relation_id for item in view.relations] == [
        "cs_dsly_highway_cargo.cargo_code",
        "cs_dsly_highway_cargo.cargo_id",
        "cs_dsly_highway_cargo.carrier_order_no",
        "cs_dsly_highway_cargo.category_id",
        "cs_dsly_highway_cargo.dispatch_order_no",
    ]
    assert view.relation_count == 5


def test_a_relation_keeps_one_identity_from_both_of_its_ends(
    service: TableRelationQueryService,
) -> None:
    """The property that makes the identity worth calling an id.

    The foreign key side is the one thing about a relation that does not depend
    on where you arrived from, so the same row is named the same way whether the
    user opened the parent or the child.
    """
    from_child = row(
        detail(service, "cs_dsly_highway_cargo"),
        "cs_dsly_highway_cargo.carrier_order_no",
    )
    from_parent = row(
        detail(service, "cs_dsly_highway_carrier_order"),
        "cs_dsly_highway_cargo.carrier_order_no",
    )

    assert from_child.edge_id == from_parent.edge_id
    assert from_child.references == from_parent.references
    assert from_parent.references == "cs_dsly_highway_carrier_order.carrier_order_no"
    assert (from_child.direction, from_parent.direction) == ("outbound", "inbound")


def test_only_the_cardinalities_move_with_the_perspective(
    service: TableRelationQueryService,
) -> None:
    identity = "cs_dsly_highway_dispatch_record.dispatch_order_no"
    from_child = row(detail(service, "cs_dsly_highway_dispatch_record"), identity)
    from_parent = row(detail(service, "cs_dsly_highway_dispatch_order"), identity)

    # 281 records over 93 dispatch orders: many records per order seen from the
    # order, one order per record seen from the record.
    assert (from_parent.code_cardinality, from_parent.db_cardinality) == (
        "one_to_many",
        "one_to_many",
    )
    assert (from_child.code_cardinality, from_child.db_cardinality) == (
        "many_to_one",
        "many_to_one",
    )


def test_each_dimension_is_flipped_on_its_own_so_a_disagreement_survives(
    service: TableRelationQueryService,
) -> None:
    """A disagreement has to read the same from both ends, or it is an artefact.

    ``cs_dsly_highway_cargo.carrier_order_no`` is the case the whole two-verdict
    design exists for: ``batchInsert`` lets one order carry many cargo rows, and
    all 99 orders in UAT carry exactly one.
    """
    identity = "cs_dsly_highway_cargo.carrier_order_no"
    from_parent = row(detail(service, "cs_dsly_highway_carrier_order"), identity)
    from_child = row(detail(service, "cs_dsly_highway_cargo"), identity)

    assert (from_parent.code_cardinality, from_parent.db_cardinality) == (
        "one_to_many",
        "one_to_one",
    )
    assert (from_child.code_cardinality, from_child.db_cardinality) == (
        "many_to_one",
        "one_to_one",
    )
    assert from_parent.dimensions_agree is False
    assert from_child.dimensions_agree is False


def test_evidence_never_flips_because_it_is_not_a_statement_about_a_direction(
    service: TableRelationQueryService,
) -> None:
    identity = "cs_dsly_highway_cargo.carrier_order_no"
    from_parent = row(detail(service, "cs_dsly_highway_carrier_order"), identity)
    from_child = row(detail(service, "cs_dsly_highway_cargo"), identity)

    for view in (from_parent, from_child):
        assert view.code_evidence == "batch_allowed"
        assert view.db_evidence == "measured"


def test_an_unmeasurable_dimension_still_reaches_the_page(
    service: TableRelationQueryService,
) -> None:
    """An empty domain is not a reason to hide a relation.

    The water-freight module has never been switched on, so the data dimension
    has nothing to say — but the code dimension does, and dropping the row would
    throw away the only answer available.

    Read from the cargo end, so a code verdict of one-to-one reads back
    unchanged: it is the one cardinality that says the same thing from both ends.
    """
    view = row(
        detail(service, "cs_dsly_shipping_cargo"),
        "cs_dsly_shipping_cargo.carrier_order_no",
    )

    assert (view.code_cardinality, view.code_evidence) == ("one_to_one", "enforced")
    assert (view.db_cardinality, view.db_evidence) == ("unknown", "no_data")
    assert view.dimensions_agree is False


def test_unknown_reads_the_same_from_both_ends(service: TableRelationQueryService) -> None:
    identity = "cs_dsly_shipping_cargo.carrier_order_no"
    from_parent = row(detail(service, "cs_dsly_shipping_carrier_order"), identity)
    from_child = row(detail(service, "cs_dsly_shipping_cargo"), identity)

    assert from_parent.db_cardinality == "unknown"
    assert from_child.db_cardinality == "unknown"


def test_a_low_sample_verdict_still_states_a_cardinality(
    service: TableRelationQueryService,
) -> None:
    # 7 rows over 7 keys: one child per parent, on far too little evidence to
    # call it a rule. The cardinality is stated and the caveat travels with it.
    view = row(
        detail(service, "cs_dsly_highway_inbound_order"),
        "cs_dsly_highway_inbound_order_cargo.inbound_order_no",
    )

    assert (view.db_cardinality, view.db_evidence) == ("one_to_one", "low_sample")


def test_dead_columns_are_kept_off_the_list_but_stay_counted(
    service: TableRelationQueryService,
    projection: SeedProjection,
) -> None:
    dead = [edge for edge in projection.edges if is_dead_column(edge.db_evidence)]
    assert len(dead) == 7, "种子里保留了死列，用来证明死列确实被挡在列表外"
    entrusted_dead = next(
        edge
        for edge in dead
        if edge.left_column == "entrusted_order_id" or edge.right_column == "entrusted_order_id"
    )

    relate = detail(service, "cs_dsly_order_entrusted_order_relate")
    parent = detail(service, "cs_dsly_order_entrusted_order")

    # The dead id stays hidden while the fields that are really written stay visible.
    relation_ids = [item.relation_id for item in relate.relations]
    assert "cs_dsly_order_entrusted_order_relate.entrusted_order_id" not in relation_ids
    assert "cs_dsly_order_entrusted_order_relate.entrusted_order_no" in relation_ids
    assert "cs_dsly_order_entrusted_order_relate.route_no" in relation_ids
    assert relate.hidden_count == 1
    assert parent.hidden_count == 1
    for view in (relate, parent):
        assert entrusted_dead.id not in {item.edge_id for item in view.relations}


def test_every_table_counter_equals_the_rows_the_list_draws(
    service: TableRelationQueryService,
) -> None:
    """The invariant the stored counters exist to guarantee.

    A card that advertises three relations next to a list that draws two is the
    bug this walks every table to rule out.
    """
    for summary in service.list_tables(WORKSPACE, only_related=False).tables:
        view = detail(
            service,
            summary.table_name,
            database_key=summary.database_key,
            schema_name=summary.schema_name,
        )
        assert summary.relation_count == len(view.relations), summary.table_name
        assert summary.hidden_count == view.hidden_count, summary.table_name


def test_a_table_reachable_only_through_a_dead_column_reads_as_unrelated(
    service: TableRelationQueryService,
) -> None:
    related = service.list_tables(WORKSPACE)
    everything = service.list_tables(WORKSPACE, only_related=False)

    hidden = {table.table_name for table in everything.tables} - {
        table.table_name for table in related.tables
    }
    assert hidden == {
        "cs_dsly_operation_attachment",
        "cs_dsly_order_attachment",
        "cs_dsly_railway_carrier_order_container",
        "cs_dsly_shipping_attachment",
        "cs_dsly_shipping_container",
        "cs_dsly_settlement_advance_payment",
        "cs_dsly_settlement_attachment",
        "cs_dsly_settlement_collection",
        "cs_dsly_settlement_operation_cargo_detail",
        "cs_dsly_settlement_operation_fee",
        "cs_dsly_declaration_attachment",
        "cs_dsly_declaration_interface_file_transfer_record",
        "cs_dsly_declaration_origin",
        "cs_portal_cockpit_kpi",
        "cs_portal_cockpit_ontime_summary",
    }
    assert related.total_count == everything.total_count
    assert related.related_count == len(related.tables)
    # Busiest table first, so the interesting one is reachable without scrolling.
    assert related.tables[0].table_name == "sys_user"


def test_railway_first_priority_relations_are_published(
    service: TableRelationQueryService,
) -> None:
    cargo = detail(service, "cs_dsly_railway_cargo")
    manifest = detail(service, "cs_dsly_railway_dispatch_manifest")
    attachment = detail(service, "cs_dsly_railway_attachment")
    carrier = detail(service, "cs_dsly_railway_carrier_order")
    dispatch = detail(service, "cs_dsly_railway_dispatch_order")
    record = detail(service, "cs_dsly_railway_dispatch_record")
    dispatch_line = detail(service, "cs_dsly_railway_dispatch_order_line")

    assert "cs_dsly_railway_cargo.cargo_code" in {
        item.relation_id for item in cargo.relations
    }
    assert "cs_dsly_railway_dispatch_manifest.cargo_id" in {
        item.relation_id for item in manifest.relations
    }
    assert "cs_dsly_railway_attachment.source_id" in {
        item.relation_id for item in attachment.relations
    }
    assert {
        "cs_dsly_railway_dispatch_order.id",
        "cs_dsly_railway_carrier_order.id",
    }.issubset({item.references for item in attachment.relations})
    carrier_ids = {item.relation_id for item in carrier.relations}
    assert any(
        identity.endswith("cs_dsly_railway_carrier_order.shipper_id")
        for identity in carrier_ids
    )
    assert any(
        identity.endswith("cs_dsly_railway_carrier_order.carrier_id")
        for identity in carrier_ids
    )
    assert "cs_dsly_railway_carrier_order.contract_no" in carrier_ids

    dispatch_ids = {item.relation_id for item in dispatch.relations}
    for suffix in (
        "cs_dsly_railway_dispatch_order.carrier_id",
        "cs_logistics_waybill_execution.waybill_no",
        "cs_logistics_cargo_safety.waybill_no",
    ):
        assert any(identity.endswith(suffix) for identity in dispatch_ids)

    assert any(
        identity.endswith("cs_dsly_railway_dispatch_record.operator_id")
        for identity in {item.relation_id for item in record.relations}
    )
    assert "cs_dsly_railway_dispatch_order_line.station_id" in {
        item.relation_id for item in dispatch_line.relations
    }


def test_table_list_search_and_database_filter_narrow_the_result(
    service: TableRelationQueryService,
) -> None:
    searched = service.list_tables(WORKSPACE, search="shipping", only_related=False)
    scoped = service.list_tables(WORKSPACE, database_key="c12_mtp_db", only_related=False)
    missing = service.list_tables(WORKSPACE, database_key="nope", only_related=False)

    assert {table.table_name for table in searched.tables} == {
        "cs_dsly_shipping_attachment",
        "cs_dsly_shipping_cargo",
        "cs_dsly_shipping_carrier_order",
        "cs_dsly_shipping_carrier_settlement",
        "cs_dsly_shipping_container",
        "cs_dsly_shipping_dispatch_manifest",
        "cs_dsly_shipping_dispatch_order",
        "cs_dsly_shipping_dispatch_record",
    }
    assert scoped.total_count == sum(
        1 for key in SEED_TABLES if key.startswith("c12_mtp_db.")
    )
    assert missing.tables == []
    assert {table.database_key for table in scoped.tables} == {"c12_mtp_db"}


def test_generation_summary_splits_every_edge_into_shown_and_held_back(
    service: TableRelationQueryService,
) -> None:
    generation = service.get_status(WORKSPACE).generation

    assert generation is not None
    assert generation.edge_count == len(SEED_EDGES)
    assert generation.hidden_count == 7
    assert generation.edge_count == generation.relation_count + generation.hidden_count


def test_status_reports_the_published_generation_and_the_seed_command(
    service: TableRelationQueryService,
) -> None:
    status = service.get_status(WORKSPACE)

    assert status.generation is not None
    assert status.generation.status == "published"
    assert status.building is None
    assert status.database_keys == [
        "c12_admin_db",
        "c12_auth_db",
        "c12_mtp_db",
        "c12_park_db",
        "c12_portal_db",
        "c12_rcc_db",
        "c12_wms_db",
    ]
    assert WORKSPACE in status.rebuild_command


def test_both_dimensions_carry_their_own_timestamp(projection: SeedProjection) -> None:
    # Two sides refreshed on one clock could not tell a real disagreement from a
    # side that simply had not been re-read yet.
    for edge in projection.edges:
        assert edge.code_checked_at is not None
        assert edge.db_measured_at is not None
        assert edge.code_checked_at < edge.db_measured_at


def test_workspace_without_a_generation_reports_an_empty_projection() -> None:
    service = TableRelationQueryService(reader=InMemoryTableRelationRepository())

    status = service.get_status(WORKSPACE)
    tables = service.list_tables(WORKSPACE)

    assert status.generation is None
    assert status.rebuild_command.endswith(WORKSPACE)
    assert tables.tables == []
    assert tables.total_count == 0
    with pytest.raises(TableRelationNotFoundError) as excinfo:
        detail(service, "cs_dsly_highway_cargo")
    assert excinfo.value.code == "table_relation_generation_missing"


def test_unknown_table_is_reported_as_missing(service: TableRelationQueryService) -> None:
    with pytest.raises(TableRelationNotFoundError):
        detail(service, "cs_dsly_does_not_exist")


def test_flip_is_total_over_every_storable_cardinality() -> None:
    assert flip_cardinality("one_to_one") == "one_to_one"
    assert flip_cardinality("one_to_many") == "many_to_one"
    assert flip_cardinality("many_to_one") == "one_to_many"
    # Nobody could measure it from either end, and the page says so rather than
    # dropping the row.
    assert flip_cardinality("unknown") == "unknown"
    with pytest.raises(ValueError):
        flip_cardinality("many_to_many")


def test_a_verdict_cannot_claim_a_cardinality_it_admits_it_never_found() -> None:
    conclusive = {
        "code_cardinality": "one_to_many",
        "code_evidence": "batch_allowed",
        "db_cardinality": "one_to_many",
        "db_evidence": "measured",
    }
    check_verdict(**conclusive)

    with pytest.raises(ValueError):
        check_verdict(**{**conclusive, "code_evidence": "no_write_path"})
    with pytest.raises(ValueError):
        check_verdict(**{**conclusive, "db_evidence": "never_written"})
    # And the other way round: evidence that did establish something cannot be
    # paired with a cardinality that states nothing.
    with pytest.raises(ValueError):
        check_verdict(**{**conclusive, "db_cardinality": "unknown"})
    with pytest.raises(ValueError):
        check_verdict(**{**conclusive, "code_cardinality": "many_to_many"})


def test_opening_a_row_shows_the_verdict_that_row_showed(
    service: TableRelationQueryService,
) -> None:
    """The continuity the detail is worthless without.

    A panel that restated the relation from the canonical stored direction would
    show ``1 — N`` for a row that read ``N — 1``, and the reader would have no way
    to tell a perspective change from a contradiction.
    """
    identity = "cs_dsly_highway_cargo.carrier_order_no"
    for table_name in ("cs_dsly_highway_cargo", "cs_dsly_highway_carrier_order"):
        listed = row(detail(service, table_name), identity)
        opened_here = opened(service, table_name, identity).relation

        assert opened_here == listed


def test_the_data_verdict_publishes_the_counts_it_was_read_off(
    service: TableRelationQueryService,
) -> None:
    """Every number behind the headline verdict, so it can be recomputed."""
    view = opened(
        service,
        "cs_dsly_highway_dispatch_record",
        "cs_dsly_highway_dispatch_record.dispatch_order_no",
    )

    assert view.relation.db_cardinality == "many_to_one"
    # 281 records carrying 93 distinct dispatch orders is the whole argument for
    # the verdict, and reading it back off the panel is how you check it.
    assert view.measurement.child_rows_with_value == 281
    assert view.measurement.child_distinct_keys == 93
    assert view.measurement.parent_distinct_keys == 93
    assert check(view, "cardinality").outcome == "confirmed"


def test_a_check_the_data_could_not_answer_says_so_instead_of_vanishing(
    service: TableRelationQueryService,
) -> None:
    """Absent and inconclusive are different, so both are stated.

    A check that disappeared when it had nothing to report would be
    indistinguishable from one that was never run.
    """
    empty = opened(
        service,
        "cs_dsly_shipping_cargo",
        "cs_dsly_shipping_cargo.carrier_order_no",
    )
    thin = opened(
        service,
        "cs_dsly_highway_inbound_order",
        "cs_dsly_highway_inbound_order_cargo.inbound_order_no",
    )

    for key in ("cardinality", "parent_unique", "orphan"):
        assert check(empty, key).outcome == "inconclusive", key
        assert check(empty, key).sql
    # Seven rows is a reading, not a rule: the cardinality is unconfirmed while
    # the checks that do not depend on volume still answer.
    assert check(thin, "cardinality").outcome == "inconclusive"
    assert check(thin, "parent_unique").outcome == "confirmed"
    assert check(thin, "orphan").outcome == "confirmed"


def test_dangling_keys_are_found_by_the_one_check_that_looks_for_them(
    service: TableRelationQueryService,
) -> None:
    """The finding neither dimension can reach.

    ``cargo_id`` measures a clean one-to-many and its write path is ordinary, yet
    27 of its 51 values point at cargo rows that are not there. Both verdicts are
    correct and both are silent about it.
    """
    view = opened(service, "cs_dsly_highway_cargo", "cs_dsly_highway_cargo.cargo_id")

    assert view.relation.db_cardinality == "many_to_one"
    assert view.relation.db_evidence == "measured"
    assert view.measurement.orphan_keys == 27
    assert check(view, "orphan").outcome == "attention"
    # The relation itself is not in doubt, only the rows it resolves to.
    assert check(view, "cardinality").outcome == "confirmed"
    assert check(view, "parent_unique").outcome == "confirmed"


def test_every_seeded_relation_rests_on_a_unique_parent_key(
    service: TableRelationQueryService,
) -> None:
    """The precondition the child counts mean nothing without.

    N children per key is only N : 1 if the key occurs once up there; otherwise it
    could be one child per key, several times over.
    """
    for summary in service.list_tables(WORKSPACE, only_related=False).tables:
        for listed in detail(
            service,
            summary.table_name,
            database_key=summary.database_key,
            schema_name=summary.schema_name,
        ).relations:
            view = evidence(
                service,
                summary.table_name,
                listed.edge_id,
                database_key=summary.database_key,
                schema_name=summary.schema_name,
            )
            measurable = view.measurement.parent_rows_with_value > 0
            expected = "confirmed" if measurable else "inconclusive"
            assert check(view, "parent_unique").outcome == expected, listed.relation_id


def test_a_matching_pair_of_key_kinds_is_not_reported_as_a_finding(
    service: TableRelationQueryService,
) -> None:
    # Stated only when it is a problem: every relation in these databases matches,
    # and a row repeating that on all of them would be noise rather than evidence.
    view = opened(service, "cs_dsly_highway_cargo", "cs_dsly_highway_cargo.cargo_id")

    assert [item.key for item in view.checks] == ["cardinality", "parent_unique", "orphan"]

    mismatched = TableRelationMeasurement(child_key_kind="numeric", parent_key_kind="text")
    assert mismatched.keys_comparable is False


def test_a_dead_column_is_hidden_from_the_list_and_explained_in_the_detail(
    service: TableRelationQueryService,
    projection: SeedProjection,
) -> None:
    """Hiding it from the list and refusing to explain it are different things.

    It is kept off the list because a row that answers nothing does not earn a
    place there. The detail is the one place where "the table has 129 rows and
    this column has none of them" is the answer.
    """
    dead = next(
        edge
        for edge in projection.edges
        if is_dead_column(edge.db_evidence)
        and (
            edge.left_column == "entrusted_order_id"
            or edge.right_column == "entrusted_order_id"
        )
    )
    view = evidence(service, "cs_dsly_order_entrusted_order_relate", dead.id)

    assert view.relation.db_evidence == "never_written"
    assert view.measurement.child_table_rows == 129
    assert view.measurement.child_rows_with_value == 0
    assert check(view, "cardinality").outcome == "inconclusive"


def test_a_relation_is_only_served_from_a_table_it_touches(
    service: TableRelationQueryService,
) -> None:
    # The table decides which end the cardinalities are stated from, so a table
    # the relation does not touch has no reading to serve.
    edge_id = row(
        detail(service, "cs_dsly_highway_cargo"),
        "cs_dsly_highway_cargo.cargo_id",
    ).edge_id

    with pytest.raises(TableRelationNotFoundError):
        evidence(service, "cs_dsly_basic_port", edge_id)
    with pytest.raises(TableRelationNotFoundError):
        evidence(service, "cs_dsly_highway_cargo", "no-such-edge")


def test_the_probe_spells_an_unset_key_the_way_that_column_stores_it(
    service: TableRelationQueryService,
) -> None:
    """A sentinel mismatch would silently return other numbers.

    An unset key is ``0`` in a bigint column and ``''`` in a varchar one, so a
    probe that guessed wrong would print a query that contradicts the counts
    beside it while looking perfectly reasonable.
    """
    numeric = opened(service, "cs_dsly_highway_cargo", "cs_dsly_highway_cargo.cargo_id")
    text = opened(
        service,
        "cs_dsly_highway_cargo",
        "cs_dsly_highway_cargo.carrier_order_no",
    )

    assert "NULLIF(cargo_id, 0)" in check(numeric, "cardinality").sql
    assert "NULLIF(carrier_order_no, '')" in check(text, "cardinality").sql
    # Schema-qualified but never alias-qualified: the alias is this application's
    # name for a connection and means nothing wherever the reader pastes the query.
    assert "FROM uat_mtp.cs_dsly_highway_cargo" in check(numeric, "cardinality").sql
    assert "c12_mtp_db" not in check(numeric, "cardinality").sql
    # Soft-deleted rows were excluded when the counts were taken, so the query has
    # to exclude them too or it will not reproduce them.
    assert "deleted = 0" in check(numeric, "cardinality").sql


def test_an_identifier_that_would_need_quoting_is_refused_not_quoted() -> None:
    # These strings leave as text a reader is invited to run, so anything that
    # could change the query's meaning fails loudly instead of being escaped.
    with pytest.raises(TableRelationProbeError):
        cardinality_sql(
            TableRelationEndpoint(
                database_key="c12_mtp_db",
                schema_name="uat_mtp",
                table_name="cargo; DROP TABLE users",
                column_name="id",
            ),
            key_kind="numeric",
        )


def test_the_data_verdict_is_the_counts_restated_and_nothing_else() -> None:
    def verdict(rows: int, keys: int, *, table_rows: int | None = None) -> tuple[str, str]:
        return db_verdict_from_counts(
            TableRelationMeasurement(
                child_key_kind="numeric",
                parent_key_kind="numeric",
                child_table_rows=table_rows if table_rows is not None else rows,
                child_rows_with_value=rows,
                child_distinct_keys=keys,
            )
        )

    threshold = LOW_SAMPLE_ROW_THRESHOLD
    assert verdict(threshold, threshold) == ("one_to_one", "measured")
    # One row short of the threshold, the same shape is only a reading.
    assert verdict(threshold - 1, threshold - 1) == ("one_to_one", "low_sample")
    # A repeated key needs no such allowance in the other direction: once a key
    # has been seen twice, no number of further rows can unsee it.
    assert verdict(3, 2) == ("one_to_many", "measured")
    # The two ways of measuring nothing, told apart by where the emptiness is.
    assert verdict(0, 0, table_rows=129) == ("unknown", "never_written")
    assert verdict(0, 0, table_rows=0) == ("unknown", "no_data")


def test_counts_that_cannot_all_be_true_of_the_same_tables_are_rejected() -> None:
    def measurement(**overrides: int) -> TableRelationMeasurement:
        return TableRelationMeasurement(
            child_key_kind="text",
            parent_key_kind="text",
            **{
                "child_table_rows": 10,
                "child_rows_with_value": 8,
                "child_distinct_keys": 5,
                "parent_rows_with_value": 5,
                "parent_distinct_keys": 5,
                "orphan_keys": 1,
                **overrides,
            },
        )

    check_counts(measurement())

    with pytest.raises(ValueError):
        check_counts(measurement(child_distinct_keys=9))
    with pytest.raises(ValueError):
        check_counts(measurement(child_rows_with_value=11))
    with pytest.raises(ValueError):
        check_counts(measurement(parent_distinct_keys=6))
    with pytest.raises(ValueError):
        check_counts(measurement(orphan_keys=6))


def test_a_code_verdict_none_of_its_own_sites_argues_for_is_rejected() -> None:
    """The invariant that took four wrong verdicts out of the seed.

    All four had read a ``batchInsert`` as many children per parent while the
    loop around it minted a fresh parent key each pass. Their sites therefore
    implied one-to-one and their verdict said one-to-many, with nothing in
    between to notice — which is precisely what this now refuses.
    """
    with pytest.raises(ValueError, match="没有任何点位支持"):
        check_sites(
            code_cardinality="one_to_many",
            code_evidence="batch_allowed",
            site_kinds=("fresh_key_per_row", "strict_to_map"),
        )

    # A verdict is also held to the grade of evidence it claims: 强制 needs
    # something that would actually break, not merely a path that writes once.
    with pytest.raises(ValueError, match="需要"):
        check_sites(
            code_cardinality="one_to_one",
            code_evidence="enforced",
            site_kinds=("fresh_key_per_row",),
        )
    with pytest.raises(ValueError, match="无写入路径"):
        check_sites(
            code_cardinality="unknown",
            code_evidence="no_write_path",
            site_kinds=("single_write",),
        )

    # Sites pointing both ways are not a contradiction. A path that can write
    # several children settles it; another that writes one does not undo that.
    check_sites(
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        site_kinds=("caller_key_reuse", "fresh_key_per_row"),
    )
    # And a relation nobody has written the places down for is not thereby wrong.
    check_sites(
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        site_kinds=(),
    )


def test_every_seeded_code_verdict_is_supported_by_its_own_sites(
    projection: SeedProjection,
) -> None:
    by_edge: dict[str, list[str]] = {}
    for site in projection.code_sites:
        by_edge.setdefault(site.edge_id, []).append(site.kind)

    recorded = 0
    for edge in projection.edges:
        kinds = tuple(by_edge.get(edge.id, ()))
        check_sites(
            code_cardinality=edge.code_cardinality,
            code_evidence=edge.code_evidence,
            site_kinds=kinds,
        )
        recorded += 1 if kinds else 0

    # The relations whose two dimensions once disagreed are the ones read
    # closely enough to write down; the rest still carry a verdict and no sites,
    # which the detail view states rather than papers over.
    assert recorded == len([edge for edge in projection.edges if by_edge.get(edge.id)])


def test_a_site_argues_from_the_same_end_the_verdict_is_stated_from(
    service: TableRelationQueryService,
) -> None:
    """A site's implication is flipped along with the verdict it supports.

    Left unflipped it would read as one-to-many under a verdict reading
    many-to-one and look like a contradiction, when the two are the same claim
    seen from opposite ends.
    """
    identity = "cs_dsly_highway_cargo.carrier_order_no"
    from_child = opened(service, "cs_dsly_highway_cargo", identity)
    from_parent = opened(service, "cs_dsly_highway_carrier_order", identity)

    assert from_child.relation.code_cardinality == "many_to_one"
    assert [site.implies for site in from_child.code_sites] == ["many_to_one", "many_to_one"]
    assert from_parent.relation.code_cardinality == "one_to_many"
    assert [site.implies for site in from_parent.code_sites] == ["one_to_many", "one_to_many"]


def test_a_site_carries_where_to_look_and_no_coordinate_that_can_rot(
    service: TableRelationQueryService,
) -> None:
    detail_view = opened(
        service,
        "cs_dsly_highway_cargo",
        "cs_dsly_highway_cargo.dispatch_order_no",
    )

    kinds = [(site.kind, site.role) for site in detail_view.code_sites]
    assert kinds == [("fresh_key_per_row", "write"), ("strict_to_map", "read")]
    for site in detail_view.code_sites:
        # Relative to the workspace root: an absolute path would be one machine's
        # answer to a question about the repository.
        assert not site.file_path.startswith("/")
        assert site.method_name and site.snippet
        # No line number anywhere. The method name and the snippet are what a
        # reader searches for, and both survive an edit that shifts the file.
        assert not re.search(r":\d+", site.file_path)


def test_table_writes_are_persist_calls_against_the_selected_table(
    service: TableRelationQueryService,
) -> None:
    cargo = service.get_table_writes(
        WORKSPACE,
        database_key=MTP[0],
        schema_name=MTP[1],
        table_name="cs_dsly_highway_cargo",
    )
    methods = [(site.kind, site.method_name) for site in cargo.writes]
    assert methods == [
        ("batch_insert", "batchCreateCarrierOrder"),
        ("batch_insert", "batchDispatchOrder"),
    ]
    assert all("cargoDao.batchInsert" in site.snippet for site in cargo.writes)
    assert cargo.table.table_name == "cs_dsly_highway_cargo"


def test_the_same_method_is_listed_once_per_table_it_writes(
    service: TableRelationQueryService,
) -> None:
    cargo = service.get_table_writes(
        WORKSPACE,
        database_key=MTP[0],
        schema_name=MTP[1],
        table_name="cs_dsly_highway_cargo",
    )
    settlement = service.get_table_writes(
        WORKSPACE,
        database_key=MTP[0],
        schema_name=MTP[1],
        table_name="cs_dsly_highway_carrier_settlement",
    )
    cargo_admin = [site for site in cargo.writes if site.method_name == "batchCreateCarrierOrder"]
    assert len(cargo_admin) == 1
    assert "cargoDao.batchInsert" in cargo_admin[0].snippet
    assert len(settlement.writes) == 1
    assert settlement.writes[0].method_name == "batchCreateCarrierOrder"
    assert "settlementAdminService.batchInsert" in settlement.writes[0].snippet


def test_a_parent_table_does_not_inherit_its_child_s_persist_calls(
    service: TableRelationQueryService,
) -> None:
    park = service.get_table_writes(
        WORKSPACE,
        database_key=MTP[0],
        schema_name=MTP[1],
        table_name="cs_dsly_highway_park_appointment",
    )
    assert park.writes
    methods = [site.method_name for site in park.writes]
    assert methods == ["report", "reappoint"]
    assert all("saveOrUpdate(appointment)" in site.snippet for site in park.writes)
    assert all("dispatchOrderDao" not in site.snippet for site in park.writes)


def test_table_updates_are_persist_calls_against_the_selected_table(
    service: TableRelationQueryService,
) -> None:
    cargo = service.get_table_updates(
        WORKSPACE,
        database_key=MTP[0],
        schema_name=MTP[1],
        table_name="cs_dsly_highway_cargo",
    )
    methods = [(site.kind, site.method_name) for site in cargo.updates]
    assert methods == [
        ("batch_update", "batchDispatchOrder"),
        ("update", "redispatch"),
        ("update", "setLoadQuantity"),
        ("update", "setCargoQuantity"),
        ("update", "modifyCargoQuantity"),
    ]
    assert "cargoDao.batchUpdate" in cargo.updates[0].snippet
    assert "cargoDao.update" in cargo.updates[1].snippet


def test_the_same_method_can_be_an_insert_and_an_update(
    service: TableRelationQueryService,
) -> None:
    inbound_inserts = service.get_table_writes(
        WORKSPACE,
        database_key=MTP[0],
        schema_name=MTP[1],
        table_name="cs_dsly_highway_inbound_order",
    )
    inbound_updates = service.get_table_updates(
        WORKSPACE,
        database_key=MTP[0],
        schema_name=MTP[1],
        table_name="cs_dsly_highway_inbound_order",
    )
    assert [site.method_name for site in inbound_inserts.writes] == ["createAndPublish"]
    assert [site.method_name for site in inbound_updates.updates] == [
        "createAndPublish",
        "retry",
        "processReceipt",
        "processOrderStatus",
        "processAcceptResult",
    ]
    assert "saveOrUpdate" in inbound_inserts.writes[0].snippet
    assert "inboundOrderDao.update" in inbound_updates.updates[0].snippet


def test_a_parent_table_does_not_inherit_its_child_s_update_calls(
    service: TableRelationQueryService,
) -> None:
    park = service.get_table_updates(
        WORKSPACE,
        database_key=MTP[0],
        schema_name=MTP[1],
        table_name="cs_dsly_highway_park_appointment",
    )
    assert [site.method_name for site in park.updates] == [
        "edit",
        "updateAuditStatus",
        "updateAccessTime",
    ]
    assert all("update(" in site.snippet for site in park.updates)
    assert all("cargoDao" not in site.snippet for site in park.updates)


def test_an_update_site_must_be_findable_without_a_line_number() -> None:
    with pytest.raises(ValueError, match="相对路径"):
        check_update_site(
            kind="update",
            file_path="/abs/HighwayCargoDao.java",
            method_name="update",
            snippet="cargoDao.update(carrierCargo);",
        )
    with pytest.raises(ValueError, match="不是可存储"):
        check_update_site(
            kind="batch_insert",
            file_path="backend/c12-mtp/HighwayCargoDao.java",
            method_name="update",
            snippet="cargoDao.update(carrierCargo);",
        )


def test_a_write_site_must_be_findable_without_a_line_number() -> None:
    with pytest.raises(ValueError, match="相对路径"):
        check_write_site(
            kind="batch_insert",
            file_path="/abs/HighwayCargoDao.java",
            method_name="batchInsert",
            snippet="cargoDao.batchInsert(insertCargoList);",
        )
    with pytest.raises(ValueError, match="不是可存储"):
        check_write_site(
            kind="caller_key_reuse",
            file_path="backend/c12-mtp/HighwayCargoDao.java",
            method_name="batchInsert",
            snippet="cargoDao.batchInsert(insertCargoList);",
        )


def test_common_columns_are_matched_by_exact_name() -> None:
    assert is_common_column("company_id") is True
    assert is_common_column("CREATE_TIME") is True
    # A prefix or substring match would have swallowed this genuine foreign key.
    assert is_common_column("affiliation_company_id") is False
    assert is_common_column("deleted_at") is False

    for seed_edge in SEED_EDGES:
        for endpoint in (seed_edge.parent, seed_edge.child):
            assert not is_common_column(endpoint.rsplit(".", 1)[1])
