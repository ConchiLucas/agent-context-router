from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from mcp.server.fastmcp.tools.base import Tool

from context_router.schemas.context import TaskIntentType


@dataclass(frozen=True, slots=True)
class TaskToolSpec:
    name: str
    title: str
    capability: str
    keywords: tuple[str, ...]
    priority_by_intent: dict[TaskIntentType, int] = field(default_factory=dict)


@dataclass(slots=True)
class TaskToolDefinition:
    spec: TaskToolSpec
    tool: Tool
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    definition_revision: str

    def as_dict(
        self,
        *,
        reason: str,
        readiness: str,
        recommended_arguments: dict[str, Any] | None = None,
        match_reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        annotations = self.tool.annotations
        return {
            "name": self.spec.name,
            "title": self.spec.title,
            "description": self.tool.description,
            "capability": self.spec.capability,
            "reason": reason,
            "readiness": readiness,
            "match_reasons": match_reasons or [],
            "input_schema": copy.deepcopy(self.input_schema),
            "output_schema": copy.deepcopy(self.output_schema),
            "annotations": (
                annotations.model_dump(mode="json", exclude_none=True)
                if annotations is not None
                else {}
            ),
            "recommended_arguments": recommended_arguments or {},
            "definition_revision": self.definition_revision,
        }


_SPECS: tuple[TaskToolSpec, ...] = (
    TaskToolSpec(
        "read_task_context",
        "读取任务数据库与通用环境上下文",
        "task_context.read",
        ("数据库列表", "环境配置", "environment", "database alias"),
        {"code_change": 20, "bug_fix": 20, "data_query": 10},
    ),
    TaskToolSpec(
        "read_middleware_context",
        "读取当前环境实时中间件配置",
        "middleware.read",
        ("redis", "mq", "minio", "elasticsearch", "nacos", "中间件", "缓存"),
        {"bug_fix": 45, "bug_investigate": 45, "code_change": 30},
    ),
    TaskToolSpec(
        "resolve_database_target",
        "解析当前任务的数据库目标",
        "database.read",
        ("数据库", "表", "sql", "schema", "数据"),
        {"data_query": 50, "bug_fix": 30, "code_change": 25},
    ),
    TaskToolSpec(
        "search_database_objects",
        "渐进搜索数据库对象",
        "database.read",
        ("字段", "列", "表结构", "索引", "schema", "column", "table"),
        {"data_query": 35, "bug_fix": 35, "code_change": 35},
    ),
    TaskToolSpec(
        "execute_database_query",
        "执行有界只读 SQL",
        "database.read",
        ("sql", "查询数据", "数据库验证", "select", "记录"),
        {"data_query": 45, "bug_fix": 35, "code_change": 30},
    ),
    TaskToolSpec(
        "save_data_visualization_query",
        "保存数据可视化查询条件",
        "visualization.data.write",
        ("数据可视化", "查询条件", "页面展示", "保存查询"),
        {"data_query": 70},
    ),
    TaskToolSpec(
        "list_task_containers",
        "列出任务 Workspace 已注册容器",
        "logs.read",
        ("容器", "docker", "服务", "日志", "报错"),
        {"bug_fix": 90, "bug_investigate": 90, "task_execute": 50},
    ),
    TaskToolSpec(
        "inspect_container_errors",
        "检查并保存容器错误证据",
        "logs.read",
        ("错误日志", "报错", "exception", "timeout", "容器日志"),
        {"bug_fix": 85, "bug_investigate": 85, "task_execute": 45},
    ),
    TaskToolSpec(
        "read_table_relations",
        "读取表关联与代码写入入口",
        "relation.read",
        ("表关联", "外键", "写入入口", "更新入口", "关系"),
        {"code_change": 55, "bug_fix": 45, "data_query": 25},
    ),
    TaskToolSpec(
        "search_relation_tables",
        "按业务词搜索关联表",
        "relation.read",
        ("表名", "业务表", "关联表", "实体"),
        {"code_change": 45, "bug_fix": 35, "data_query": 25},
    ),
    TaskToolSpec(
        "search_value_mappings",
        "搜索已发布业务值映射",
        "mapping.read",
        ("业务值", "id", "编码", "编号", "映射", "货主", "承运商"),
        {"data_query": 100, "interface_execute": 55, "bug_fix": 30, "code_change": 25},
    ),
    TaskToolSpec(
        "resolve_value_candidates",
        "解析业务值候选",
        "mapping.read",
        ("候选值", "随机", "任意一个", "映射值", "业务id"),
        {"data_query": 80, "interface_execute": 50},
    ),
    TaskToolSpec(
        "execute_mapped_data_query",
        "按映射查询并记录数据结果",
        "database.read",
        ("映射查询", "业务数据", "数据可视化", "随机数据"),
        {"data_query": 95, "bug_fix": 25, "code_change": 20},
    ),
    TaskToolSpec(
        "search_forwarding_interfaces",
        "搜索当前任务可调用接口",
        "interface.read",
        ("接口", "api", "controller", "路径", "请求"),
        {
            "interface_discovery": 100,
            "interface_execute": 100,
            "bug_fix": 45,
            "code_change": 35,
        },
    ),
    TaskToolSpec(
        "read_forwarding_interface_detail",
        "读取接口业务语义和请求响应详情",
        "interface.read",
        ("接口详情", "请求参数", "响应字段", "影响表", "接口语义"),
        {"interface_discovery": 90, "interface_execute": 80, "bug_fix": 40, "code_change": 30},
    ),
    TaskToolSpec(
        "read_forwarding_request_history",
        "读取接口最近请求历史",
        "interface.read",
        ("请求历史", "最近成功", "响应取值", "接口参数"),
        {"interface_execute": 70, "bug_fix": 50, "code_change": 35},
    ),
    TaskToolSpec(
        "prepare_forwarding_request",
        "准备受控接口请求",
        "interface.execute",
        ("组装参数", "准备请求", "请求计划", "接口调用"),
        {"interface_execute": 90, "bug_fix": 40, "code_change": 30},
    ),
    TaskToolSpec(
        "execute_forwarding_request",
        "执行已准备的接口计划",
        "interface.execute",
        ("发送请求", "执行接口", "验证接口", "plan"),
        {"interface_execute": 85, "bug_fix": 50, "code_change": 45},
    ),
)


PARAMETER_DESCRIPTIONS: dict[str, str] = {
    "task_id": "当前任务由 prepare_task_context 返回的正整数 ID；必须在整条链路中原样复用。",
    "sections": "需要读取的限定章节集合；只传当前步骤真正需要的值。",
    "components": "可选中间件组件 ID 列表；省略表示读取当前环境全部已配置组件。",
    "reveal_secrets": "是否在当前本机授权调用中返回明文连接字段；默认 true，禁止持久化返回值。",
    "query": "用于业务语义或名称检索的短文本；应保留用户原始业务关键词。",
    "limit": "服务端允许返回的最大结果数；必须在 Schema 给定范围内。",
    "requests": "按顺序读取的文档 ID 与可选章节请求，document_id 必须来自 prepare 或 search。",
    "mapping_id": "由 search_value_mappings 返回的已发布映射 ID；必须原样复用，禁止编造。",
    "table_name": "已知的裸表名，用于解析数据库目标；不包含数据库别名或任意连接信息。",
    "business_hint": "当表名未知时用于解析数据库目标的业务描述，例如合同、订单或承运商。",
    "database_context_id": (
        "由 resolve_database_target 为同一 task 返回的 36 位不透明 ID；禁止传数据库别名。"
    ),
    "object_type": "要搜索的对象类型，只能使用 Schema 枚举中的 schema/table/view/column/index。",
    "pattern": "数据库对象名称 glob 模式；* 表示任意字符，已知名称时应尽量缩小范围。",
    "detail": "返回细节级别：names=仅名称，summary=关键元数据，full=完整元数据；不存在 columns。",
    "schema": "可选 Schema 名过滤；必须属于 database_context_id 绑定的数据库目标。",
    "table": "可选表名过滤；搜索 column/index 时应与 schema 一起用于缩小范围。",
    "sql": "必填的一条有界只读 SQL；不得为空、多语句、写入或跨数据库访问。",
    "description": "面向可视化或任务记录的简短业务描述，不得包含凭据、原始日志或敏感正文。",
    "keyword": "用户业务关键词或精确候选搜索词；空字符串表示使用映射默认顺序。",
    "database": "仅在同名表跨数据库歧义时传稳定数据库别名；不要传物理连接信息。",
    "schema_name": "已确认的 Schema 名；不能用用户猜测值绕过发布关系校验。",
    "execution_tool_call_id": "同一 task 中真实成功查询调用返回的 tool_call_id，用作执行证据。",
    "container_id": "必须来自 list_task_containers 当前 task 返回的完整容器 ID。",
    "since_minutes": "向前读取日志的分钟数，默认 15，最大 1440。",
    "tail": "最多读取的日志行数，默认 500，最大 1000，不会持续 follow。",
    "keywords": "可选错误关键词列表，用于在有界日志快照内辅助提取错误块。",
    "tables": "需要读取关系的 1 至 10 个精确裸表名。",
    "evidence": "关系证据展开级别：none、uncertain 或 all。",
    "interface_id": "由 search_forwarding_interfaces 返回的已导入接口 ID，必须原样复用。",
    "location": "接口参数位置，只能是 path、query 或 body。",
    "parameter_path": "接口参数在对应位置中的稳定字段路径。",
    "selection": "候选选择方式：default 保持规则顺序；random 仅在用户明确要求随机时使用。",
    "purpose": ("数据查询主任务使用 primary_visualization；其他任务默认使用 supporting_evidence。"),
    "service": "可选接口服务名过滤，来自已导入接口元数据。",
    "role": "可选账号角色语义过滤，不是请求头或凭据。",
    "success_only": "是否只读取成功请求历史，默认 true。",
    "include_response": "是否包含有界脱敏响应；仅在确需从结构化响应取值时设为 true。",
    "address_id": "可选具名转发地址 ID；省略时服务端复用有效历史或唯一候选。",
    "login_account": "可选已保存登录账号选择；不是密码或请求头。",
    "role_name": "可选已保存账号角色名，用于选择服务端身份配置。",
    "path": "调用方明确提供的 OpenAPI path 参数对象；显式值优先。",
    "body": "调用方明确提供的 OpenAPI JSON 请求体对象；显式值优先。",
    "value_strategy": "参数复用策略；默认 reuse_successful，只有用户明确要求时才刷新或忽略历史。",
    "refresh_value_keys": "refresh_selected 时需要刷新的稳定 value_key 列表。",
    "plan_id": "prepare_forwarding_request 返回的短期不可变执行计划 ID。",
    "request_sha256": "准备结果返回的 64 位小写 SHA-256，必须原样回传以防请求被替换。",
}


class TaskToolRegistry:
    def __init__(self) -> None:
        self._specs = {spec.name: spec for spec in _SPECS}
        self._definitions: dict[str, TaskToolDefinition] = {}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def bind(self, name: str, tool: Tool) -> None:
        spec = self._specs[name]
        input_schema = _enrich_schema(tool.parameters, tool_name=name)
        tool.parameters = copy.deepcopy(input_schema)
        revision_payload = {
            "name": name,
            "description": tool.description,
            "input_schema": input_schema,
            "output_schema": tool.output_schema,
            "annotations": (
                tool.annotations.model_dump(mode="json", exclude_none=True)
                if tool.annotations is not None
                else {}
            ),
        }
        revision = hashlib.sha256(
            json.dumps(
                revision_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self._definitions[name] = TaskToolDefinition(
            spec=spec,
            tool=tool,
            input_schema=input_schema,
            output_schema=copy.deepcopy(tool.output_schema),
            definition_revision=revision,
        )

    def get(self, name: str) -> TaskToolDefinition | None:
        return self._definitions.get(name)

    def discover(
        self,
        *,
        intent_type: TaskIntentType,
        query: str,
        enabled_capabilities: set[str],
        limit: int,
        task_id: int,
    ) -> list[dict[str, Any]]:
        normalized_query = query.strip().lower()
        ranked: list[tuple[int, str, TaskToolDefinition, list[str]]] = []
        for name, definition in self._definitions.items():
            spec = definition.spec
            score = spec.priority_by_intent.get(intent_type, 0)
            reasons: list[str] = []
            if score:
                reasons.append(f"主意图 {intent_type} 的推荐动作")
            if spec.capability in enabled_capabilities:
                score += 20
                reasons.append(f"任务已启用 {spec.capability}")
            if name.lower() in normalized_query or spec.title.lower() in normalized_query:
                score += 80
                reasons.append("精确命中动作名称或标题")
            for keyword in spec.keywords:
                if keyword.lower() in normalized_query:
                    score += 25
                    reasons.append(f"命中关键词 {keyword}")
                    break
            if score <= 0:
                continue
            ranked.append((score, name, definition, reasons))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        results: list[dict[str, Any]] = []
        for _, _, definition, reasons in ranked[:limit]:
            readiness = (
                "ready"
                if definition.spec.capability in enabled_capabilities
                else "capability_expandable"
            )
            action = definition.as_dict(
                reason=reasons[0] if reasons else "与当前任务相关",
                readiness=readiness,
                match_reasons=reasons,
            )
            action["invocation"] = {
                "tool": "invoke_task_tool",
                "arguments": {
                    "task_id": task_id,
                    "tool_name": definition.spec.name,
                    "arguments": {},
                    "definition_revision": definition.definition_revision,
                },
            }
            results.append(action)
        return results


def _enrich_schema(schema: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    enriched = copy.deepcopy(schema)
    properties = enriched.get("properties")
    if not isinstance(properties, dict):
        return enriched
    for name, value in properties.items():
        if not isinstance(value, dict) or value.get("description"):
            continue
        if tool_name == "prepare_forwarding_request" and name == "query":
            value["description"] = "调用方明确提供的 OpenAPI query 参数对象；显式值优先。"
            continue
        value["description"] = PARAMETER_DESCRIPTIONS.get(
            name,
            f"{name} 参数；必须符合当前工具 JSON Schema，不能使用猜测值绕过服务端校验。",
        )
    return enriched
