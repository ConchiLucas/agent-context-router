from context_router.interface_search.comparison import compare_interfaces
from context_router.interface_search.domain import EndpointRecord


def _address_endpoint(*, path: str, discriminator: str) -> EndpointRecord:
    return EndpointRecord(
        workspace_id="workspace-1",
        project="basic-service",
        service="basic-core",
        method="POST",
        path=path,
        operation_id="AddressController.getById",
        title="按 ID 查询地址",
        purpose="内部服务远程按地址 ID 查询详情",
        audiences=["内部服务", "门户端"],
        domains=["基础资料", "地址簿"],
        scenarios=["远程按 ID 查询地址"],
        actions=["query", "detail"],
        aliases=["远程地址详情"],
        resource="address_book",
        lookup_keys=["id"],
        cardinality="one",
        ownership="by_id",
        discriminators=[discriminator],
    )


def test_comparison_exposes_authentication_route_and_output_differences() -> None:
    no_auth = _address_endpoint(
        path="/basic-api/portal/address/noAuth/remote/getById",
        discriminator="免鉴权远程入口，返回地址详情",
    )
    authenticated = _address_endpoint(
        path="/basic-api/portal/address/remote/getById",
        discriminator="标准远程入口，返回地址详情",
    )

    response = compare_interfaces([no_auth, authenticated])

    assert "authentication" in response.differing_dimensions
    assert "output_and_other_discriminators" in response.differing_dimensions
    assert response.items[0].differences["authentication"] == ["no_auth"]
    assert response.items[1].differences["authentication"] == ["standard_or_unspecified"]
    assert "role:remote" in response.common["route_roles"]


def test_comparison_exposes_remote_and_direct_route_roles() -> None:
    remote = _address_endpoint(
        path="/basic-api/portal/address/remote/getById",
        discriminator="供内部服务远程调用",
    )
    direct = _address_endpoint(
        path="/basic-api/portal/address/getById",
        discriminator="门户直接入口",
    )

    response = compare_interfaces([remote, direct])

    assert "route_roles" in response.differing_dimensions
    assert "role:remote" in response.items[0].differences["route_roles"]
    assert "role:remote" not in response.items[1].differences["route_roles"]


def test_comparison_exposes_single_mode_constraint_against_neutral_candidate() -> None:
    neutral = _address_endpoint(
        path="/order-api/admin/order/findContainerList",
        discriminator="查询订单全部运输段的集装箱",
    ).model_copy(
        update={
            "domains": ["订单"],
            "resource": "order_container",
            "purpose": "查询订单各运输段集装箱列表",
        }
    )
    highway = _address_endpoint(
        path="/highway-api/admin/order/getContainerList",
        discriminator="仅查询公路运输段集装箱",
    ).model_copy(
        update={
            "domains": ["公路运输"],
            "resource": "order_container",
            "purpose": "查询公路运输订单集装箱列表",
        }
    )

    response = compare_interfaces([neutral, highway])

    assert "transport_mode_constraint" in response.differing_dimensions
    assert response.items[0].differences["transport_mode_constraint"] == [
        "not_transport_mode_limited"
    ]
    assert response.items[1].differences["transport_mode_constraint"] == ["transport:highway"]


def test_comparison_exposes_url_and_stream_output_forms() -> None:
    url = _address_endpoint(
        path="/file/preview/url",
        discriminator="返回文件预览地址 URL",
    )
    content = _address_endpoint(
        path="/file/preview/{uuid}",
        discriminator="流式响应文件内容",
    ).model_copy(update={"purpose": "直接预览并流式响应文件内容"})

    response = compare_interfaces([url, content])

    assert "output_form" in response.differing_dimensions
    assert response.items[0].differences["output_form"] == ["output:url"]
    assert response.items[1].differences["output_form"] == ["output:content"]


def test_comparison_exposes_specialized_operation_against_generic_crud() -> None:
    specialized = _address_endpoint(
        path="/settlement-api/admin/account/transportOrderPage",
        discriminator="分页查询运输订单费用",
    ).model_copy(
        update={
            "operation_id": "AccountController.transportOrderPage",
            "resource": "transport_order_expense",
        }
    )
    generic = _address_endpoint(
        path="/settlement-api/admin/account/page",
        discriminator="分页查询普通费用账户",
    ).model_copy(
        update={
            "operation_id": "AccountController.page",
            "resource": "expense_account",
        }
    )

    response = compare_interfaces([specialized, generic])

    assert "endpoint_operation" in response.differing_dimensions
    assert "operation_specificity" in response.differing_dimensions
    assert response.items[0].differences["endpoint_operation"] == ["transportOrderPage"]
    assert response.items[0].differences["operation_specificity"] == ["specialized"]
    assert response.items[1].differences["operation_specificity"] == ["generic_crud"]


def test_comparison_recomputes_path_resource_scope_for_existing_records() -> None:
    business_expense = _address_endpoint(
        path="/settlement-api/admin/btExpense/getById",
        discriminator="按 ID 查询业务费用",
    ).model_copy(
        update={
            "operation_id": "BtExpenseController.getById",
            "resource": "business_expense",
            "distinguishing_features": {"primary_action": "detail"},
        }
    )
    account = _address_endpoint(
        path="/settlement-api/admin/account/getById",
        discriminator="按 ID 查询普通费用账户",
    ).model_copy(
        update={
            "operation_id": "AccountController.getById",
            "resource": "expense_account",
            "distinguishing_features": {"primary_action": "detail"},
        }
    )

    response = compare_interfaces([business_expense, account])

    assert "path_resource_scope" in response.differing_dimensions
    assert response.items[0].differences["path_resource_scope"] == ["btExpense"]
    assert response.items[1].differences["path_resource_scope"] == ["account"]
    assert response.items[0].distinguishing_features["api_namespace"] == "settlement-api"
    assert "复合资源或专用动作" in response.decision_rule
