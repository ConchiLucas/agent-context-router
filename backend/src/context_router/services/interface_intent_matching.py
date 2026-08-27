from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

InterfaceGoal = Literal["discover", "execute"]
InterfaceResultShape = Literal["page", "list", "detail"]

_CREATE_WORDS = ("新增", "创建", "发起", "提交", "保存", "生成", "上传")
_UPDATE_WORDS = ("修改", "更新", "编辑", "确认", "取消", "完成", "启用", "停用", "驳回")
_DELETE_WORDS = ("删除", "移除", "作废")
_READ_WORDS = ("查询", "查看", "获取", "搜索", "查找", "统计")
_EXECUTE_WORDS = (
    "调用",
    "执行",
    "发送请求",
    "请求接口",
    "新增",
    "创建",
    "发起",
    "提交",
    "保存",
    "修改",
    "更新",
    "编辑",
    "删除",
    "移除",
)
_DISCOVERY_WORDS = ("查找", "搜索", "找出", "找到", "有哪些", "哪个", "什么接口", "接口路径")
_POLITE_PREFIX = re.compile(r"^(?:请|请帮我|帮我|我想|我要|需要|麻烦|能不能|可以不可以|给我)+")
_ACTION_PREFIX = re.compile(
    r"^(?:分页查询|批量查询|查询详情|查询|查看|获取|搜索|查找|找到|调用|执行|发送|"
    r"新增|创建|发起|提交|保存|修改|更新|编辑|删除|移除|统计)+"
)
_META_SUFFIX = re.compile(
    r"(?:相关)?(?:的)?(?:接口|api)(?:是什么|有哪些|在哪(?:里)?|路径是什么|详情|信息)?$",
    re.IGNORECASE,
)
_ENTITY_SUFFIX = re.compile(r"(?:相关)?(?:的)?(?:数据|信息|记录|列表|详情)$")


@dataclass(frozen=True, slots=True)
class InterfaceIntent:
    raw_query: str
    normalized_query: str
    search_term: str
    business_entity: str
    goal: InterfaceGoal
    desired_crud: str | None
    result_shape: InterfaceResultShape | None

    def as_dict(self) -> dict[str, object]:
        return {
            "goal": self.goal,
            "business_entity": self.business_entity,
            "desired_crud": self.desired_crud,
            "result_shape": self.result_shape,
            "search_term": self.search_term,
        }


@dataclass(frozen=True, slots=True)
class InterfaceMatch:
    score: int
    reasons: tuple[str, ...]
    mismatches: tuple[str, ...]
    score_breakdown: tuple[dict[str, object], ...]


class InterfaceIntentMatcher:
    """Deterministic interface intent parsing and source-backed candidate ranking."""

    @classmethod
    def analyze(cls, query: str) -> InterfaceIntent:
        raw = query.strip()
        normalized = cls._normalize(raw)
        goal: InterfaceGoal = "discover" if cls.is_discovery_request(raw) else "execute"
        desired_crud = cls._desired_crud(normalized)
        shape = cls._result_shape(normalized)
        if shape is None and goal == "discover" and desired_crud == "read":
            shape = "page"
        entity = cls._entity_hint(raw)
        return InterfaceIntent(
            raw_query=raw,
            normalized_query=normalized,
            search_term=entity or raw,
            business_entity=entity,
            goal=goal,
            desired_crud=desired_crud,
            result_shape=shape,
        )

    @classmethod
    def is_discovery_request(cls, task: str) -> bool:
        normalized = cls._normalize(task)
        if not normalized or "接口" not in normalized and "api" not in normalized:
            return False
        if any(word in normalized for word in _EXECUTE_WORDS):
            # 查询/查找可以描述接口发现；真正的调用、写动作必须保持 execute。
            non_read_execute = tuple(word for word in _EXECUTE_WORDS if word not in _READ_WORDS)
            if any(word in normalized for word in non_read_execute):
                return False
        if any(word in normalized for word in _DISCOVERY_WORDS):
            return True
        return bool(
            re.search(
                r"(?:查询|查看|获取).+(?:的)?(?:接口|api)(?:是什么|有哪些|在哪)?$", normalized
            )
        )

    @classmethod
    def score(cls, intent: InterfaceIntent, candidate: dict[str, Any]) -> InterfaceMatch:
        score = 0
        reasons: list[str] = []
        mismatches: list[str] = []
        score_breakdown: list[dict[str, object]] = []

        def apply(delta: int, category: str, reason: str, *, mismatch: bool = False) -> None:
            nonlocal score
            score += delta
            score_breakdown.append({"category": category, "delta": delta, "reason": reason})
            (mismatches if mismatch else reasons).append(reason)

        entity = cls._normalize(intent.business_entity)
        business_entity = cls._normalize(candidate.get("business_entity"))
        business_action = cls._normalize(candidate.get("business_action"))
        scenario = cls._normalize(candidate.get("business_scenario"))
        name = cls._normalize(candidate.get("name"))
        path = cls._normalize(candidate.get("path"))
        aliases = cls._strings(candidate.get("aliases"))
        positive_examples = cls._strings(candidate.get("positive_examples"))
        negative_examples = cls._strings(candidate.get("negative_examples"))
        crud = str(candidate.get("crud_type") or "unknown")

        if entity and business_entity == entity:
            apply(120, "business_entity", f"业务对象完全匹配：{candidate.get('business_entity')}")
        elif (
            entity and business_entity and (entity in business_entity or business_entity in entity)
        ):
            apply(80, "business_entity", f"业务对象相关：{candidate.get('business_entity')}")

        raw_norm = intent.normalized_query
        if business_action and (business_action in raw_norm or raw_norm in business_action):
            apply(100, "business_action", f"业务动作匹配：{candidate.get('business_action')}")

        alias_match = cls._best_text_match(entity or raw_norm, aliases)
        if alias_match == "exact":
            apply(65, "alias", "业务别名完全匹配")
        elif alias_match == "partial":
            apply(35, "alias", "业务别名相关")

        example_match = cls._best_text_match(raw_norm, positive_examples)
        if example_match == "exact":
            apply(45, "positive_example", "命中正向示例")
        elif example_match == "partial":
            apply(25, "positive_example", "与正向示例相关")

        if scenario and entity and entity in scenario:
            apply(30, "business_scenario", "业务场景匹配")

        if intent.desired_crud:
            if crud == intent.desired_crud:
                apply(90, "crud", f"CRUD 匹配：{crud}")
            elif crud != "unknown":
                apply(
                    -180,
                    "crud",
                    f"期望 {intent.desired_crud}，候选为 {crud}",
                    mismatch=True,
                )

        shape_text = " ".join((name, business_action, path))
        if intent.result_shape:
            if cls._shape_matches(intent.result_shape, shape_text):
                apply(60, "result_shape", f"接口形态匹配：{intent.result_shape}")
            elif cls._has_other_shape(intent.result_shape, shape_text):
                apply(
                    -25,
                    "result_shape",
                    f"接口形态不是 {intent.result_shape}",
                    mismatch=True,
                )

        if entity and entity in name:
            apply(25, "name", "接口名称包含业务对象")
        elif raw_norm and (raw_norm in name or name in raw_norm):
            apply(20, "name", "接口名称匹配")

        if raw_norm and raw_norm in path:
            apply(15, "path", "接口路径匹配")

        table_names = [
            cls._normalize(effect.get("table_name"))
            for effect in candidate.get("table_effects") or []
            if isinstance(effect, dict)
        ]
        if entity and any(entity in table_name for table_name in table_names):
            apply(25, "table_effect", "数据影响表匹配")

        request_schema = cls._normalize(candidate.get("request_schema"))
        if entity and entity in request_schema:
            apply(15, "request_contract", "请求参数合同包含业务对象")

        if cls._best_text_match(raw_norm, negative_examples) != "none":
            apply(-120, "negative_example", "命中负向示例", mismatch=True)

        confidence = candidate.get("intent_confidence")
        if isinstance(confidence, int) and confidence > 0:
            apply(min(confidence // 20, 5), "profile_confidence", "业务语义档案置信度")
        successful_requests = int(candidate.get("successful_request_count") or 0)
        if successful_requests > 0:
            apply(
                min(5 + successful_requests, 20),
                "successful_history",
                f"同接口已有 {successful_requests} 次成功请求",
            )
        return InterfaceMatch(
            score=score,
            reasons=tuple(dict.fromkeys(reasons)),
            mismatches=tuple(dict.fromkeys(mismatches)),
            score_breakdown=tuple(score_breakdown),
        )

    @staticmethod
    def confidence(score: int, margin: int) -> str:
        if score >= 180 and margin >= 25:
            return "high"
        if score >= 100:
            return "medium"
        return "low"

    @staticmethod
    def _desired_crud(normalized: str) -> str | None:
        if any(word in normalized for word in _DELETE_WORDS):
            return "delete"
        if any(word in normalized for word in _CREATE_WORDS):
            return "create"
        if any(word in normalized for word in _UPDATE_WORDS):
            return "update"
        if any(word in normalized for word in _READ_WORDS):
            return "read"
        return None

    @staticmethod
    def _result_shape(normalized: str) -> InterfaceResultShape | None:
        if "分页" in normalized:
            return "page"
        if any(word in normalized for word in ("列表", "全部", "所有", "批量")):
            return "list"
        if any(word in normalized for word in ("详情", "单条", "一个", "根据id", "按id")):
            return "detail"
        return None

    @classmethod
    def _entity_hint(cls, raw: str) -> str:
        if "/" in raw and not re.search(r"[\u4e00-\u9fff]", raw):
            return raw.strip()
        value = re.sub(r"\s+", "", raw.strip())
        value = _POLITE_PREFIX.sub("", value)
        value = re.sub(
            r"^在?(?:uat|test|local|pre|prod|生产|测试|本地)(?:环境)?",
            "",
            value,
            flags=re.I,
        )
        value = _META_SUFFIX.sub("", value)
        value = _ACTION_PREFIX.sub("", value)
        value = _ENTITY_SUFFIX.sub("", value)
        return value.strip("的：:，,。 ") or raw.strip()

    @classmethod
    def _best_text_match(cls, query: str, values: list[str]) -> str:
        if not query:
            return "none"
        normalized_values = [cls._normalize(value) for value in values if value]
        if query in normalized_values:
            return "exact"
        if any(query in value or value in query for value in normalized_values if len(value) >= 2):
            return "partial"
        return "none"

    @staticmethod
    def _shape_matches(shape: InterfaceResultShape, text: str) -> bool:
        if shape == "page":
            return "分页" in text or "/page" in text
        if shape == "list":
            return any(word in text for word in ("列表", "批量", "/list"))
        return any(word in text for word in ("详情", "根据id", "按id", "getbyid", "/detail"))

    @classmethod
    def _has_other_shape(cls, shape: InterfaceResultShape, text: str) -> bool:
        return any(
            cls._shape_matches(other, text)
            for other in ("page", "list", "detail")
            if other != shape
        )

    @staticmethod
    def _strings(value: Any) -> list[str]:
        return [str(item) for item in value] if isinstance(value, list) else []

    @staticmethod
    def _normalize(value: Any) -> str:
        return re.sub(r"\s+", "", str(value or "").strip().casefold())
