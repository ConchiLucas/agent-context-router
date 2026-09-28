from context_router.interface_search.config import Settings
from context_router.interface_search.domain import EndpointCreate, QueryIntent, SearchRequest
from context_router.interface_search.embedding import LocalFeatureEmbedding
from context_router.interface_search.query_understanding import understand_query
from context_router.interface_search.repository import InMemoryEndpointRepository
from context_router.interface_search.route_identity import (
    infer_endpoint_call_layer,
    infer_endpoint_route_signals,
    infer_query_call_layer,
    infer_query_route_signals,
    route_identity_score,
)
from context_router.interface_search.search import SearchService, _semantic_conflict_penalty


def _endpoint(*, service: str, path: str, title: str) -> EndpointCreate:
    return EndpointCreate(
        project="demo-project",
        service=service,
        method="POST",
        path=path,
        operation_id=f"DemoController.{path.rsplit('/', 1)[-1]}",
        title=title,
        purpose=title,
        audiences=["门户端"],
        actions=["query", "page"],
        resource="bill",
    )


def test_query_keeps_architectural_roles_out_of_explicit_service_hints() -> None:
    intent = understand_query("门户端调用 customer-portal 的分页接口")

    assert "customer-portal" in intent.service_hints
    assert "portal" not in intent.service_hints


def test_route_signals_are_derived_without_workspace_business_mapping() -> None:
    query_signals = infer_query_route_signals("通过网关入口预览铁路文件")
    endpoint_signals = infer_endpoint_route_signals(
        project="transport-web",
        service="public-gateway",
        path="/railway-api/portal/file/preview/{uuid}",
        operation_id="FileController.preview",
        title="预览铁路文件",
        actions=["query"],
    )

    assert {"layer:gateway", "transport:railway", "operation:preview"} <= set(query_signals)
    assert {"layer:gateway", "transport:railway", "operation:preview"} <= set(
        endpoint_signals
    )


def test_waterway_is_a_generic_shipping_route_signal() -> None:
    assert "transport:shipping" in infer_query_route_signals("查询水路运输订单轨迹")
    track_score = route_identity_score(
        query="查询水路运输订单轨迹",
        project="transport-service",
        service="transport-core",
        path="/basic-api/portal/track/carrierMapTrack",
        operation_id="TrackController.carrierMapTrack",
        title="查询承运商运输轨迹",
        semantic_terms=("水路运输", "海运地图轨迹"),
    )
    detail_score = route_identity_score(
        query="查询水路运输订单轨迹",
        project="transport-service",
        service="transport-core",
        path="/shipping-api/portal/order/getDetail",
        operation_id="OrderController.getDetail",
        title="查询水路运单详情",
        semantic_terms=("水路运输", "运单详情"),
    )

    assert track_score >= 0.86
    assert track_score > detail_score


def test_specialized_track_query_conflicts_with_unrelated_detail_operation() -> None:
    query_signals = set(infer_query_route_signals("查询水路运输轨迹"))
    track_signals = set(
        infer_endpoint_route_signals(
            project="transport-service",
            service="transport-core",
            path="/api/admin/track/carrierMapTrack",
            operation_id="TrackController.carrierMapTrack",
            title="查询运输轨迹",
            actions=["detail"],
        )
    )
    detail_signals = set(
        infer_endpoint_route_signals(
            project="transport-service",
            service="transport-core",
            path="/api/admin/dispatch/getInfo",
            operation_id="DispatchController.getInfo",
            title="查询调度详情",
            actions=["detail"],
        )
    )

    assert "operation:track" in query_signals & track_signals
    assert "operation:track" not in detail_signals
    assert "operation:detail" in detail_signals


def test_high_confidence_semantic_conflicts_receive_a_bounded_soft_penalty() -> None:
    intent = QueryIntent(
        normalized_query="查询铁路账单",
        slot_confidences={"domain": 0.95, "resource": 0.82, "action": 0.95},
    )

    assert _semantic_conflict_penalty(
        ["domain", "resource", "action"], intent, exact=0.0
    ) == 0.12
    assert _semantic_conflict_penalty(["domain"], intent, exact=0.95) == 0.0


def test_portal_actor_implies_gateway_only_without_explicit_route_or_service() -> None:
    assert infer_query_call_layer("门户端分页查询应收账单") == "unknown"
    assert infer_query_call_layer("门户端调用下游直连接口分页查询应收账单") == "service_direct"
    assert infer_query_call_layer("门户端调用 settlement-api 分页查询应收账单") == "unknown"
    assert infer_query_call_layer("门户端内部远程供内部服务免登录按ID查询地址") == "unknown"


def test_multiple_route_conditions_outweigh_a_partial_route_match() -> None:
    no_auth = route_identity_score(
        query="门户端内部远程供内部服务免登录按ID查询地址",
        project="basic-service",
        service="basic-core",
        path="/basic-api/portal/address/noAuth/remote/getById",
        operation_id="AddressController.getById",
        title="按ID查询地址",
    )
    authenticated = route_identity_score(
        query="门户端内部远程供内部服务免登录按ID查询地址",
        project="basic-service",
        service="basic-core",
        path="/basic-api/portal/address/remote/getById",
        operation_id="AddressController.getById",
        title="按ID查询地址",
    )

    assert no_auth > authenticated


def test_explicit_service_combines_with_operation_and_output_identity() -> None:
    preview_url = route_identity_score(
        query="门户端调用 customer-portal 获取附件预览地址",
        project="frontend",
        service="customer-portal",
        path="/member-api/portal/attachment/preview/url",
        operation_id="AttachmentController.getPreviewUrl",
        title="获取附件预览 URL",
    )
    file_url = route_identity_score(
        query="门户端调用 customer-portal 获取附件预览地址",
        project="frontend",
        service="customer-portal",
        path="/member-api/portal/attachment/{uuid}",
        operation_id="AttachmentController.getFileUrl",
        title="获取附件访问 URL",
    )

    assert preview_url > file_url
    assert preview_url == 0.99


def test_endpoint_call_layer_is_derived_from_architectural_service_role() -> None:
    assert (
        infer_endpoint_call_layer(
            project="frontend",
            service="customer-portal",
            path="/billing/portal/bill/page",
            operation_id="BillController.page",
            title="门户账单分页",
        )
        == "frontend_gateway"
    )
    assert (
        infer_endpoint_call_layer(
            project="billing",
            service="billing-core",
            path="/billing-api/portal/bill/page",
            operation_id="BillController.page",
            title="账单分页",
        )
        == "service_direct"
    )


def test_portal_route_identity_is_recalled_without_coercing_a_service_name() -> None:
    repository = InMemoryEndpointRepository()
    service = SearchService(
        repository,
        LocalFeatureEmbedding(),
        Settings(search_candidate_limit=10),
    )
    noise = [
        _endpoint(
            service="billing-core",
            path=f"/billing-api/portal/invoice/noise{index}",
            title=f"门户端处理账单{index}",
        )
        for index in range(20)
    ]
    expected = _endpoint(
        service="customer-portal",
        path="/gateway/billing/portal/receivableBill/page",
        title="门户端分页查询应收账单",
    )
    saved = service.add_many([*noise, expected])
    expected_id = saved[-1].id

    response = service.search(
        SearchRequest(
            query="门户端分页查询应收账单",
            top_k=10,
            debug=True,
            persist_session=False,
        )
    )

    assert response.hits[0].interface_id == expected_id
    assert response.hits[0].score.service_match == 0
    assert response.hits[0].score.route_identity_match >= 0.56
    assert response.trace is not None
    assert response.trace.ranking_strategy_version == "support-aware-rrf-v8"


def test_portal_actor_prefers_gateway_over_same_action_direct_service() -> None:
    repository = InMemoryEndpointRepository()
    service = SearchService(
        repository,
        LocalFeatureEmbedding(),
        Settings(search_candidate_limit=20),
    )
    direct = _endpoint(
        service="billing-core",
        path="/billing-api/portal/receivableBill/batchConfirm",
        title="门户端批量确认应收对账",
    )
    gateway = _endpoint(
        service="customer-portal",
        path="/gateway/billing/portal/receivableBill/batchConfirm",
        title="门户端批量确认应收对账",
    )
    saved = service.add_many([direct, gateway])

    response = service.search(
        SearchRequest(
            query="门户端批量确认应收对账",
            top_k=2,
            debug=True,
            persist_session=False,
        )
    )

    assert response.hits[0].interface_id == saved[1].id
    assert response.hits[0].score.route_identity_match >= 0.6
    assert response.hits[1].score.conflict_penalty == 0
    assert "call_layer" not in response.hits[1].conflicting_slots


def test_explicit_service_name_is_stronger_than_similar_business_wording() -> None:
    direct = route_identity_score(
        query="调用 customer-portal 的 getByIdItem",
        project="member-service",
        service="member-core",
        path="/member-api/admin/contract/getByIdItem",
        operation_id="ContractController.getByIdItem",
        title="按ID查询合同",
        actions=["query", "detail"],
    )
    selected = route_identity_score(
        query="调用 customer-portal 的 getByIdItem",
        project="frontend",
        service="customer-portal",
        path="/member-api/admin/contract/getByIdItem",
        operation_id="ContractController.getByIdItem",
        title="按ID查询合同",
        actions=["query", "detail"],
    )

    assert selected == 1.0
    assert selected > direct


def test_explicit_service_and_operation_are_promoted_together() -> None:
    repository = InMemoryEndpointRepository()
    service = SearchService(
        repository,
        LocalFeatureEmbedding(),
        Settings(search_candidate_limit=20),
    )
    service.add_many(
        [
            _endpoint(
                service="customer-portal",
                path="/member-api/portal/article/detail",
                title="门户文章详情",
            ),
            _endpoint(
                service="customer-portal",
                path="/member-api/admin/invoice/getByUserId",
                title="按用户查询发票资料",
            ),
        ]
    )

    response = service.search(
        SearchRequest(
            query="运营端调用 customer-portal 的getByUserId",
            top_k=2,
            persist_session=False,
        )
    )

    assert response.hits[0].path.endswith("/getByUserId")
    assert response.hits[0].score.service_match == 1.0
    assert response.hits[0].score.route_identity_match == 1.0
    assert response.hits[0].score.total >= 0.95
