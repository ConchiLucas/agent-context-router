from __future__ import annotations

from context_router.interface_search.domain import (
    EndpointRecord,
    InterfaceCompareResponse,
    InterfaceComparisonItem,
)
from context_router.interface_search.families import build_distinguishing_features
from context_router.interface_search.route_identity import (
    infer_endpoint_call_layer,
    infer_endpoint_route_signals,
)


def compare_interfaces(endpoints: list[EndpointRecord]) -> InterfaceCompareResponse:
    if len(endpoints) < 2:
        raise ValueError("at_least_two_interfaces_required")
    workspace_ids = {item.workspace_id for item in endpoints}
    if len(workspace_ids) != 1:
        raise ValueError("interfaces_must_share_workspace")

    route_signals = [_route_signals(item) for item in endpoints]
    distinguishing_features = [_distinguishing_features(item) for item in endpoints]
    dimensions = {
        "audiences": [item.audiences for item in endpoints],
        "domains": [item.domains for item in endpoints],
        "resource": [[item.resource] if item.resource else [] for item in endpoints],
        "actions": [item.actions for item in endpoints],
        "lookup_keys": [item.lookup_keys for item in endpoints],
        "cardinality": [[item.cardinality] for item in endpoints],
        "ownership": [[item.ownership] for item in endpoints],
        "required_inputs": [_required_input_labels(item) for item in endpoints],
        "business_identifiers": [_business_identifier_labels(item) for item in endpoints],
        "service_identity": [
            _feature_labels(item, "service_identity") for item in distinguishing_features
        ],
        "api_namespace": [
            _feature_labels(item, "api_namespace") for item in distinguishing_features
        ],
        "path_resource_scope": [
            _feature_labels(item, "path_resource_scope") for item in distinguishing_features
        ],
        "endpoint_operation": [
            _feature_labels(item, "endpoint_operation") for item in distinguishing_features
        ],
        "operation_specificity": [
            _feature_labels(item, "operation_specificity") for item in distinguishing_features
        ],
        "authentication": [_authentication_labels(item) for item in route_signals],
        "call_layer": [_call_layer_labels(item) for item in endpoints],
        "route_roles": [_route_role_labels(item) for item in route_signals],
        "transport_mode_constraint": [_transport_mode_labels(item) for item in route_signals],
        "operation_identity": [_operation_labels(item) for item in route_signals],
        "output_form": [_output_form_labels(item) for item in route_signals],
        "output_and_other_discriminators": [item.discriminators for item in endpoints],
    }
    common: dict[str, list[str]] = {}
    differing: list[str] = []
    for name, values in dimensions.items():
        shared = set(values[0]).intersection(*(set(item) for item in values[1:]))
        if shared:
            common[name] = sorted(shared)
        if len({tuple(sorted(item)) for item in values}) > 1:
            differing.append(name)

    return InterfaceCompareResponse(
        workspace_id=endpoints[0].workspace_id,
        common=common,
        differing_dimensions=differing,
        decision_rule=(
            "只能依据本次比较中真实存在的候选和用户明确条件做决定：若一个候选独占用户明确要求的"
            "业务资源、限定词、专用动作、输入、输出、鉴权、服务身份、调用层级或场景，选择它。"
            "用户明确表达复合资源或专用动作时，必须优先匹配 path_resource_scope、endpoint_operation"
            "和 api_namespace；不得用仅匹配通用 page/getById/deleteByIds 等 CRUD 动作的相邻资源接口"
            "覆盖它。若候选满足相同明确意图、仅在用户未说明的"
            "端侧、数据范围或调用入口等关键维度上不同，提出最小澄清问题。用户明确要求全部或多个"
            "运输方式时，不得选择带单一运输方式约束的候选；用户明确要求 URL/地址或文件内容时，"
            "不得用另一个输出形态替代。不得臆造未出现在 items 中的替代接口。"
        ),
        items=[
            InterfaceComparisonItem(
                interface_id=endpoint.id,
                method=endpoint.method,
                path=endpoint.path,
                operation_id=endpoint.operation_id,
                title=endpoint.title,
                purpose=endpoint.purpose,
                audiences=endpoint.audiences,
                domains=endpoint.domains,
                scenarios=endpoint.scenarios,
                resource=endpoint.resource,
                actions=endpoint.actions,
                lookup_keys=endpoint.lookup_keys,
                cardinality=endpoint.cardinality,
                ownership=endpoint.ownership,
                discriminators=endpoint.discriminators,
                required_inputs=_required_input_labels(endpoint),
                business_identifiers=_business_identifier_labels(endpoint),
                distinguishing_features=distinguishing_features[index],
                differences={
                    name: values[index] for name, values in dimensions.items() if name in differing
                },
            )
            for index, endpoint in enumerate(endpoints)
        ],
    )


def _required_input_labels(endpoint: EndpointRecord) -> list[str]:
    return [
        f"{item.name} ({item.location}, {'必填' if item.required else '可选'})"
        for item in endpoint.required_inputs
        if item.name
    ]


def _business_identifier_labels(endpoint: EndpointRecord) -> list[str]:
    return [
        " / ".join(
            dict.fromkeys(
                value
                for value in [item.display_name, item.canonical, *item.technical_names]
                if value
            )
        )
        for item in endpoint.business_identifiers
    ]


def _distinguishing_features(endpoint: EndpointRecord) -> dict[str, str]:
    return {
        **endpoint.distinguishing_features,
        **build_distinguishing_features(endpoint),
    }


def _feature_labels(features: dict[str, str], name: str) -> list[str]:
    value = features.get(name, "").strip()
    return [value] if value else []


def _route_signals(endpoint: EndpointRecord) -> list[str]:
    return infer_endpoint_route_signals(
        project=endpoint.project,
        service=endpoint.service,
        path=endpoint.path,
        operation_id=endpoint.operation_id,
        title=endpoint.title,
        actions=endpoint.actions,
        semantic_terms=(
            endpoint.purpose,
            *endpoint.domains,
            *endpoint.scenarios,
            *endpoint.aliases,
        ),
    )


def _authentication_labels(route_signals: list[str]) -> list[str]:
    return ["no_auth"] if "auth:no_auth" in route_signals else ["standard_or_unspecified"]


def _call_layer_labels(endpoint: EndpointRecord) -> list[str]:
    value = infer_endpoint_call_layer(
        project=endpoint.project,
        service=endpoint.service,
        path=endpoint.path,
        operation_id=endpoint.operation_id,
        title=endpoint.title,
        actions=endpoint.actions,
    )
    return [] if value == "unknown" else [value]


def _route_role_labels(route_signals: list[str]) -> list[str]:
    return [
        signal for signal in route_signals if signal.startswith(("role:", "layer:", "transport:"))
    ]


def _transport_mode_labels(route_signals: list[str]) -> list[str]:
    values = [signal for signal in route_signals if signal.startswith("transport:")]
    return values or ["not_transport_mode_limited"]


def _operation_labels(route_signals: list[str]) -> list[str]:
    return [signal for signal in route_signals if signal.startswith("operation:")]


def _output_form_labels(route_signals: list[str]) -> list[str]:
    return [signal for signal in route_signals if signal.startswith("output:")] or ["unspecified"]
