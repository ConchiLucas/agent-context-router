from __future__ import annotations

import re
from collections.abc import Iterable

from context_router.interface_search.workspaces import WorkspaceProfile

CORE_TAXONOMY: dict[str, dict[str, tuple[str, ...]]] = {
    "action": {
        "query": (
            "查询",
            "搜索",
            "获取",
            "查看",
            "看看",
            "查找",
            "精确找",
            "查出",
            "找出",
            "摸清",
            "弄清",
            "拉出",
            "拉回来",
            "取出",
            "取回来",
            "拿回来",
            "query",
            "search",
            "get",
        ),
        "page": ("分页", "翻页", "page"),
        "list": ("列表", "清单", "列出", "罗列", "批量查询", "list"),
        "detail": (
            "详情",
            "单条",
            "明细",
            "点开",
            "打开",
            "detail",
            "getbyid",
            "findone",
            "getinfo",
        ),
        "create": (
            "新增",
            "新建",
            "创建",
            "录入",
            "登记",
            "补充",
            "补一条",
            "填入",
            "记下",
            "生成",
            "建出来",
            "提报成",
            "添加",
            "保存",
            "上传",
            "create",
            "add",
            "insert",
            "save",
            "upload",
        ),
        "update": (
            "修改",
            "改掉",
            "改成",
            "更新",
            "编辑",
            "覆盖",
            "维护",
            "标成",
            "标记为",
            "设为",
            "设置为",
            "挂上去",
            "update",
            "edit",
            "modify",
        ),
        "delete": (
            "删除",
            "删掉",
            "批量删",
            "清掉",
            "清除",
            "扔掉",
            "删",
            "移除",
            "delete",
            "remove",
        ),
        "cancel": ("取消", "撤销", "作废", "cancel", "revoke", "void"),
        "export": ("导出", "下载", "export", "download"),
        "approve": (
            "审批",
            "审核",
            "送审",
            "提审",
            "接受",
            "同意",
            "确认",
            "通过",
            "approve",
            "audit",
            "review",
        ),
        "execute": (
            "执行",
            "提交",
            "发送",
            "手工发",
            "开始作业",
            "开始干",
            "开工",
            "execute",
            "submit",
            "send",
        ),
    }
}

# Compatibility alias for callers that only need the universal action vocabulary.
TAXONOMY = CORE_TAXONOMY


def effective_taxonomy(
    profile: WorkspaceProfile | None = None,
) -> dict[str, dict[str, tuple[str, ...]]]:
    dimensions = {key: dict(value) for key, value in CORE_TAXONOMY.items()}
    if profile:
        for dimension in {term.dimension for term in profile.terms if term.active}:
            target = dimensions.setdefault(dimension, {})
            for canonical, aliases in profile.mapping(dimension).items():
                target[canonical] = tuple(dict.fromkeys([*target.get(canonical, ()), *aliases]))
    return dimensions


def match_taxonomy(text: str, dimension: str, profile: WorkspaceProfile | None = None) -> list[str]:
    lowered = _normalize(text)
    mapping = effective_taxonomy(profile).get(dimension, {})
    return [
        canonical
        for canonical, aliases in mapping.items()
        if any(_normalize(alias) in lowered for alias in aliases)
    ]


def canonicalize_value(
    value: str,
    dimension: str,
    *,
    preserve_unknown: bool = True,
    profile: WorkspaceProfile | None = None,
) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    lowered = _normalize(normalized)
    for canonical, aliases in effective_taxonomy(profile).get(dimension, {}).items():
        if lowered == _normalize(canonical) or any(
            lowered == _normalize(alias) for alias in aliases
        ):
            return canonical
    return normalized if preserve_unknown else None


def canonicalize_values(
    values: Iterable[str],
    dimension: str,
    *,
    preserve_unknown: bool = True,
    profile: WorkspaceProfile | None = None,
) -> list[str]:
    canonical = [
        item
        for value in values
        if (
            item := canonicalize_value(
                value,
                dimension,
                preserve_unknown=preserve_unknown,
                profile=profile,
            )
        )
    ]
    return list(dict.fromkeys(canonical))


def synonym_groups(
    dimensions: tuple[str, ...] = ("audience", "action", "domain"),
    profile: WorkspaceProfile | None = None,
) -> tuple[tuple[str, ...], ...]:
    taxonomy = effective_taxonomy(profile)
    return tuple(
        (canonical, *aliases)
        for dimension in dimensions
        for canonical, aliases in taxonomy.get(dimension, {}).items()
    )


def canonical_names(dimension: str, profile: WorkspaceProfile | None = None) -> tuple[str, ...]:
    return tuple(effective_taxonomy(profile).get(dimension, {}))


def normalize_actions(
    values: Iterable[str], technical_text: str, profile: WorkspaceProfile | None = None
) -> list[str]:
    actions = canonicalize_values(values, "action", preserve_unknown=False, profile=profile)
    lowered = _normalize(technical_text)
    actions.extend(match_taxonomy(technical_text, "action", profile))
    if re.search(r"(?:/|\b)(?:page|list)(?:/|\b|[a-z])", technical_text.lower()) or any(
        marker in lowered for marker in ("分页", "列表", "candidatepage")
    ):
        if "page" in lowered or "分页" in lowered:
            actions = [item for item in actions if item != "list"]
            actions.append("page")
        else:
            actions.append("list")
    return list(dict.fromkeys(actions))


def _normalize(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value).lower()
