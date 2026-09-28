from __future__ import annotations

from context_router.interface_search.domain import EndpointCreate
from context_router.interface_search.query_understanding import understand_query
from context_router.interface_search.search import _distinctive_query_terms, _slot_match_details
from context_router.interface_search.workspaces import WorkspaceProfile, WorkspaceTerm


def _profile() -> WorkspaceProfile:
    return WorkspaceProfile(
        workspace_id="workspace",
        name="workspace",
        terms=[
            WorkspaceTerm(
                dimension="resource",
                canonical_value="rail_dispatch_order",
                aliases=["运输订单"],
                metadata={"domains": ["rail_transport"]},
            ),
            WorkspaceTerm(
                dimension="resource",
                canonical_value="road_dispatch_order",
                aliases=["运输订单"],
                metadata={"domains": ["road_transport"]},
            ),
            WorkspaceTerm(
                dimension="resource",
                canonical_value="sea_dispatch_order",
                aliases=["运输订单"],
                metadata={"domains": ["sea_transport"]},
            ),
            # Reproduce a profile where an overly broad domain alias belongs to
            # one mode. It must not silently decide the shared resource alias.
            WorkspaceTerm(
                dimension="domain",
                canonical_value="rail_transport",
                aliases=["铁路", "运输订单"],
            ),
            WorkspaceTerm(
                dimension="domain",
                canonical_value="road_transport",
                aliases=["公路"],
            ),
            WorkspaceTerm(
                dimension="domain",
                canonical_value="sea_transport",
                aliases=["水路"],
            ),
            WorkspaceTerm(
                dimension="audience",
                canonical_value="admin",
                aliases=["运营端"],
            ),
        ],
    )


def test_shared_resource_alias_does_not_choose_an_arbitrary_mode() -> None:
    intent = understand_query("运营端生成运输订单", _profile())

    assert intent.resource == ""
    assert intent.domains == []
    assert {item.value for item in intent.resource_candidates} == {
        "rail_dispatch_order",
        "road_dispatch_order",
        "sea_dispatch_order",
    }
    assert all(item.confidence == 0.55 for item in intent.resource_candidates)
    assert intent.uncertain_slots == ["resource", "domain"]


def test_explicit_domain_outside_shared_alias_resolves_the_resource() -> None:
    intent = understand_query("运营端生成铁路运输订单", _profile())

    assert intent.resource == "rail_dispatch_order"
    assert intent.domains == ["rail_transport"]
    assert intent.uncertain_slots == []


def test_distinctive_terms_remove_actor_and_read_grammar() -> None:
    assert _distinctive_query_terms("运营端按ID查询文章详情") == ["文章"]
    assert _distinctive_query_terms("运营端按ID反馈详情") == ["反馈"]


def test_resource_after_query_verb_wins_over_actor_resource() -> None:
    profile = WorkspaceProfile(
        workspace_id="workspace",
        name="workspace",
        terms=[
            WorkspaceTerm(
                dimension="resource",
                canonical_value="carrier",
                aliases=["承运商"],
                metadata={"domains": ["member"]},
            ),
            WorkspaceTerm(
                dimension="resource",
                canonical_value="station",
                aliases=["站点"],
                metadata={"domains": ["line"]},
            ),
            WorkspaceTerm(
                dimension="domain",
                canonical_value="member",
                aliases=["承运商"],
            ),
            WorkspaceTerm(
                dimension="domain",
                canonical_value="line",
                aliases=["站点"],
            ),
        ],
    )

    intent = understand_query("门户端承运商分页查询站点", profile)

    assert intent.resource == "station"
    assert intent.context_resources == ["carrier"]
    assert intent.domains == ["line"]


def test_context_resource_matches_endpoint_identity_without_replacing_target_resource() -> None:
    profile = WorkspaceProfile(
        workspace_id="workspace",
        name="workspace",
        terms=[
            WorkspaceTerm(
                dimension="resource",
                canonical_value="request",
                aliases=["业务需求"],
            ),
            WorkspaceTerm(
                dimension="resource",
                canonical_value="request_order",
                aliases=["业务订单"],
            ),
            WorkspaceTerm(
                dimension="resource",
                canonical_value="shipper",
                aliases=["托运人"],
            ),
        ],
    )
    intent = understand_query("在业务需求中分页查询托运人", profile)
    endpoint = EndpointCreate(
        workspace_id="workspace",
        project="demo",
        service="demo-core",
        method="POST",
        path="/api/admin/request/shipper/page",
        operation_id="RequestController.shipperPage",
        title="业务需求下托运人分页",
        purpose="分页查询业务需求的托运人",
        resource="shipper",
        actions=["page"],
        cardinality="many",
    )

    matched, conflicting = _slot_match_details(endpoint, intent, profile)

    assert intent.resource == "shipper"
    assert intent.context_resources == ["request"]
    assert {"resource", "context_resource"} <= set(matched)
    assert "context_resource" not in conflicting

    adjacent_endpoint = EndpointCreate(
        workspace_id="workspace",
        project="demo",
        service="demo-core",
        method="POST",
        path="/api/admin/requestOrder/shipper/page",
        operation_id="RequestOrderController.shipperPage",
        title="业务订单下托运人分页",
        purpose="分页查询业务订单的托运人",
        resource="shipper",
        actions=["page"],
        cardinality="many",
    )

    adjacent_matched, adjacent_conflicting = _slot_match_details(
        adjacent_endpoint,
        intent,
        profile,
    )

    assert "resource" in adjacent_matched
    assert "context_resource" not in adjacent_matched
    assert "context_resource" in adjacent_conflicting
