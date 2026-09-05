from __future__ import annotations

from context_router.interface_search.domain import (
    EndpointRecord,
    InterfaceCompareResponse,
    InterfaceComparisonItem,
)


def compare_interfaces(endpoints: list[EndpointRecord]) -> InterfaceCompareResponse:
    if len(endpoints) < 2:
        raise ValueError("at_least_two_interfaces_required")
    workspace_ids = {item.workspace_id for item in endpoints}
    if len(workspace_ids) != 1:
        raise ValueError("interfaces_must_share_workspace")

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
            "输入、输出或场景，选择它；若候选满足相同明确意图、仅在用户未说明的端侧、数据范围"
            "或调用入口等关键维度上不同，提出最小澄清问题；不得臆造未出现在 items 中的替代接口。"
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
                distinguishing_features=endpoint.distinguishing_features,
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
