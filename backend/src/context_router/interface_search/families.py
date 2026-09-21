from __future__ import annotations

import re

from context_router.interface_search.domain import EndpointCreate

ACTION_DESCRIPTIONS = {
    "page": "分页返回多条结果",
    "list": "返回不分页列表",
    "detail": "按标识返回单条详情",
    "create": "创建新资源",
    "update": "修改已有资源",
    "delete": "删除已有资源",
    "cancel": "取消或撤销已有业务",
    "export": "导出或下载数据",
    "approve": "处理审批动作",
    "execute": "执行或提交业务动作",
    "query": "读取业务数据",
}

GENERIC_CRUD_OPERATIONS = {
    "add",
    "create",
    "delete",
    "deletebyid",
    "deletebyids",
    "detail",
    "get",
    "getbyid",
    "list",
    "page",
    "query",
    "remove",
    "save",
    "saveorupdate",
    "update",
}


def infer_controller_name(operation_id: str) -> str:
    source_class, separator, _method = operation_id.partition(".")
    return source_class.strip() if separator else ""


def infer_interface_family(*, resource: str, controller_name: str, path: str) -> str:
    if resource:
        return resource
    if controller_name:
        name = controller_name.removesuffix("Controller")
        name = re.sub(r"(?:Admin|Portal|Internal|Remote)$", "", name)
        normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower().strip("_")
        if normalized:
            return normalized
    segments = [segment for segment in path.split("/") if segment and "{" not in segment]
    return (
        segments[-2].lower() if len(segments) >= 2 else (segments[-1].lower() if segments else "")
    )


def build_distinguishing_features(endpoint: EndpointCreate) -> dict[str, str]:
    actions = _specific_actions(endpoint.actions)
    primary_action = actions[0] if actions else "query"
    operation_selector = _operation_selector(endpoint)
    path_segments = [
        segment for segment in endpoint.path.split("/") if segment and not segment.startswith("{")
    ]
    values = {
        "primary_action": primary_action,
        "action_meaning": ACTION_DESCRIPTIONS.get(primary_action, primary_action),
        "cardinality": endpoint.cardinality,
        "ownership": endpoint.ownership,
        "service_identity": " / ".join(
            item for item in (endpoint.project, endpoint.service) if item
        ),
    }
    if path_segments:
        values["api_namespace"] = path_segments[0]
    if len(path_segments) >= 2:
        values["path_resource_scope"] = path_segments[-2]
    if operation_selector:
        values["endpoint_operation"] = operation_selector
        values["operation_specificity"] = (
            "generic_crud"
            if operation_selector.casefold() in GENERIC_CRUD_OPERATIONS
            else "specialized"
        )
    if endpoint.lookup_keys:
        values["lookup_keys"] = "、".join(endpoint.lookup_keys[:6])
    if endpoint.required_inputs:
        values["required_inputs"] = "、".join(
            item.zh_name or item.name for item in endpoint.required_inputs[:6]
        )
    if endpoint.discriminators:
        values["semantic_difference"] = "；".join(endpoint.discriminators[:4])
    return values


def sibling_action_keys(actions: list[str]) -> list[str]:
    return _specific_actions(actions)


def _specific_actions(actions: list[str]) -> list[str]:
    specific = [action for action in actions if action != "query"]
    return specific or (["query"] if "query" in actions else [])


def _operation_selector(endpoint: EndpointCreate) -> str:
    _controller, separator, method = endpoint.operation_id.rpartition(".")
    if separator and method.strip():
        return method.strip()
    segments = [
        segment for segment in endpoint.path.split("/") if segment and not segment.startswith("{")
    ]
    return segments[-1] if segments else ""
