import pytest

from context_router.schemas.interface_forwarding import (
    InterfaceForwardingIdentityWrite,
    InterfaceForwardingLogWrite,
)
from context_router.services.interface_forwarding import InterfaceForwardingService


def test_identity_write_keeps_a_concise_role_name() -> None:
    payload = InterfaceForwardingIdentityWrite(
        workspace_id="workspace-1",
        environment_id="address-1",
        login_account="15181319157",
        role_name="货主",
        request_header="{}",
    )

    assert payload.role_name == "货主"


def test_identity_write_defaults_role_name_for_existing_clients() -> None:
    payload = InterfaceForwardingIdentityWrite(
        workspace_id="workspace-1",
        environment_id="address-1",
        login_account="superAdmin",
    )

    assert payload.role_name == ""


def test_external_log_write_bounds_status_and_duration() -> None:
    payload = InterfaceForwardingLogWrite(
        environment_id="address-1",
        identity_id="identity-1",
        request_body='{"pageNumber":1,"pageSize":1}',
        response_body='{"code":200}',
        status_code=200,
        success=True,
        duration_ms=120,
    )

    assert payload.status_code == 200
    assert payload.duration_ms == 120


def test_parse_openapi_endpoints_and_resolve_local_schema_refs() -> None:
    endpoints = InterfaceForwardingService._parse_spec(
        {
            "openapi": "3.0.0",
            "tags": [{"name": "order-controller", "description": "订单接口"}],
            "paths": {
                "/orders": {
                    "post": {
                        "tags": ["order-controller"],
                        "summary": "创建订单",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/OrderWrite"}
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"id": {"type": "string"}},
                                        }
                                    }
                                }
                            }
                        },
                    }
                }
            },
            "components": {
                "schemas": {
                    "OrderWrite": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    }
                }
            },
        }
    )

    assert len(endpoints) == 1
    assert endpoints[0]["name"] == "创建订单"
    assert endpoints[0]["method"] == "POST"
    assert endpoints[0]["path"] == "/orders"
    assert endpoints[0]["controller_name"] == "OrderController"
    assert "controller_description" not in endpoints[0]
    assert endpoints[0]["request_schema"]["properties"]["name"]["type"] == "string"


def test_parse_swagger_body_and_response_schema() -> None:
    endpoints = InterfaceForwardingService._parse_spec(
        {
            "swagger": "2.0",
            "paths": {
                "/health": {
                    "get": {
                        "operationId": "health",
                        "parameters": [{"in": "body", "schema": {"type": "object"}}],
                        "responses": {"200": {"schema": {"type": "string"}}},
                    }
                }
            },
        }
    )

    assert endpoints[0]["name"] == "health"
    assert endpoints[0]["request_schema"] == {"type": "object"}
    assert endpoints[0]["response_schema"] == {"type": "string"}
    assert endpoints[0]["operation_id"] == "health"
    assert "crud_type" not in endpoints[0]


@pytest.mark.skip(reason="legacy CRUD inference was replaced by semantic actions")
def test_crud_type_does_not_treat_every_post_as_create() -> None:
    assert InterfaceForwardingService._crud_type("POST", "分页查询委托需求") == "read"
    assert InterfaceForwardingService._crud_type("POST", "新增门户端委托需求") == "create"
    assert InterfaceForwardingService._crud_type("POST", "更新委托需求状态") == "update"
    assert InterfaceForwardingService._crud_type("POST", "批量删除委托需求") == "delete"
    assert InterfaceForwardingService._crud_type("POST", "按文件 ID 获取附件地址") == "read"
    assert InterfaceForwardingService._crud_type("POST", "根据合同生成作业计划") == "create"
    assert InterfaceForwardingService._crud_type("POST", "审批作业计划") == "update"
    assert InterfaceForwardingService._crud_type("POST", "撤回委托订单") == "update"


def test_parse_controller_metadata_with_chinese_fallback() -> None:
    endpoints = InterfaceForwardingService._parse_spec(
        {
            "openapi": "3.0.0",
            "paths": {
                "/admin/attachment/upload": {
                    "post": {
                        "tags": ["bt-attachment-controller"],
                        "operationId": "upload_11",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
    )

    assert endpoints[0]["controller_name"] == "BtAttachmentController"
    assert "controller_description" not in endpoints[0]


def test_coalesce_interface_name_prefers_chinese_summary() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "getOrderInfo",
            summary="查询订单详情",
            method="GET",
            path="/api/orders/{id}",
        )
        == "查询订单详情"
    )


@pytest.mark.skip(reason="legacy workspace-specific name inference")
def test_coalesce_interface_name_infers_action_and_subject() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "getDriverPage",
            method="GET",
            path="/api/drivers",
        )
        == "查询司机"
    )
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "batchCreateOrders",
            method="POST",
            path="/api/orders/batch",
        )
        == "新增订单"
    )
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "getOrders",
            method="GET",
            path="/api/orders",
        )
        == "查询订单"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_derive_c12_portal_name_preserves_precise_chinese_summary() -> None:
    assert (
        InterfaceForwardingService._derive_c12_portal_name(
            "查询当前可填报入口",
            "/api/government/reporting/currentEntry",
            "门户端政务填报Controller",
        )
        == "查询当前可填报入口"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_derive_c12_portal_name_rewrites_generated_names() -> None:
    assert (
        InterfaceForwardingService._derive_c12_portal_name(
            "新增contract-admin-controller 相关",
            "/member-api/admin/contract/deleteByIds",
            "ContractAdminController",
        )
        == "批量删除合同"
    )
    assert (
        InterfaceForwardingService._derive_c12_portal_name(
            "查询用户",
            "/member-api/portal/userInfo/getLoginUserInfo",
            "UserInfoPortalController",
        )
        == "查询当前登录用户信息"
    )
    assert (
        InterfaceForwardingService._derive_c12_portal_name(
            "处理账户概览",
            "/member-api/portal/mtp/workbench/accountOverview/shipper",
            "AccountOverviewPortalController",
        )
        == "查询货主工作台账户概览"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_derive_c12_data_name_uses_source_reviewed_path_mapping() -> None:
    assert (
        InterfaceForwardingService._derive_c12_data_name(
            "新增订单",
            "/data-api/portal/order/orderStatusStatistics",
        )
        == "统计公路派车单状态"
    )
    assert (
        InterfaceForwardingService._derive_c12_data_name(
            "新增商品",
            "/data-api/mtp/admin/goods/selectable/page",
        )
        == "分页查询可添加的 MTP 商品"
    )


@pytest.mark.skip(reason="legacy workspace-specific controller mapping")
def test_derive_source_controller_name_resolves_localized_tag() -> None:
    assert (
        InterfaceForwardingService._derive_source_controller_name(
            "c12-portal",
            "门户端政务填报Controller",
        )
        == "PortalGovernmentReportController"
    )
    assert (
        InterfaceForwardingService._derive_source_controller_name(
            "c12-data",
            "装箱数据查询Controller",
        )
        == "DataPortalOutboundBoxController"
    )
    assert (
        InterfaceForwardingService._derive_source_controller_name(
            "c12-mtp",
            "司机管理Controller",
        )
        == "司机管理Controller"
    )
    assert (
        InterfaceForwardingService._derive_source_controller_name(
            "c12-mtp",
            "运营端装箱管理Controller",
            "/order-api/admin/outboundBox/page",
        )
        == "OutboundBoxOrderAdminController"
    )
    assert (
        InterfaceForwardingService._derive_source_controller_name(
            "c12-mtp",
            "EntrustedOrderRelateAdminController",
            "/order-api/admin/relate/getList",
        )
        == "entrustedOrderRelateAdminController"
    )


@pytest.mark.skip(reason="legacy workspace-specific controller metadata")
def test_controller_description_prefers_java_tag_description() -> None:
    pytest.fail("legacy controller description test must stay skipped")


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_basic_api_path_before_http_method() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增司机",
            method="POST",
            path="/basic-api/admin/driver/deleteByIds/{ids}",
            controller_description="司机管理",
        )
        == "批量删除司机"
    )
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增address-admin-controller 相关",
            method="POST",
            path="/basic-api/admin/address/getById",
        )
        == "按 ID 查询地址"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_declaration_api_path() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增订单",
            method="POST",
            path="/declaration-api/admin/order/getDeclareDetailById",
        )
        == "查询订单申报详情"
    )
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增commodity-admin-controller 相关",
            method="POST",
            path="/declaration-api/admin/commodity/deleteByIds",
        )
        == "批量删除商品"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_order_api_path() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增订单",
            method="POST",
            path="/order-api/admin/entrustedOrder/deleteByIds/{ids}",
        )
        == "批量删除委托订单"
    )
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增booking-application-admin-controller 相关",
            method="POST",
            path="/order-api/admin/booking/application/confirm/{id}",
        )
        == "确认订舱申请"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_line_api_path() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增线路",
            method="POST",
            path="/line-api/admin/route/product/queryFeeItems",
        )
        == "查询线路产品费用项"
    )
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增station-admin-controller 相关",
            method="POST",
            path="/line-api/admin/station/updateStationStatusByIds",
        )
        == "批量更新站点状态"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_shipping_api_path() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增订单",
            method="POST",
            path="/shipping-api/portal/dispatchOrder/redispatch",
        )
        == "重新调度"
    )
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增shipping-cargo-admin-controller 相关",
            method="POST",
            path="/shipping-api/admin/cargo/getCargoListByCarrierOrderNo",
        )
        == "按承运商订单号查询货物列表"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_settlement_api_path() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增payable-bill-admin-controller 相关",
            method="POST",
            path="/settlement-api/admin/payableBill/batchConfirmReconciliation",
        )
        == "批量确认对账应付账单"
    )
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增payment-confirmation-admin-controller 相关",
            method="POST",
            path="/settlement-api/admin/paymentConfirmation/confirmVerification",
        )
        == "确认付款核销"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_trace_api_path() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增map-track-admin-controller 相关",
            method="POST",
            path="/trace-api/admin/track/carrierMapTrack",
        )
        == "查询承运商地图轨迹"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_railway_api_path() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增订单",
            method="POST",
            path="/railway-api/admin/dispatchOrder/syncRailwayTrace",
        )
        == "同步铁路运输轨迹"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_operation_api_path() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增operation-entrusted-admin-controller 相关",
            method="POST",
            path="/operation-api/admin/entrusted/createOrder",
        )
        == "创建运营委托订单"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_highway_api_path() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "新增highway-cargo-admin-controller 相关",
            method="POST",
            path="/highway-api/admin/cargo/getCargoListByDispatchOrderId",
        )
        == "按调度订单 ID 查询公路运输货物列表"
    )


@pytest.mark.skip(reason="legacy workspace-specific path mapping")
def test_coalesce_interface_name_uses_remaining_small_groups() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "查询custom-sse-emitter-controller 相关",
            method="GET",
            path="/api/sse/connect",
        )
        == "建立 SSE 连接"
    )
