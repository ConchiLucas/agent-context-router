from __future__ import annotations

import re

from context_router.interface_search.domain import IntentCandidate, NegativeConstraint, QueryIntent
from context_router.interface_search.embedding import tokenize
from context_router.interface_search.slots import (
    infer_cardinality,
    infer_lookup_keys,
    infer_ownership,
    infer_resource,
)
from context_router.interface_search.taxonomy import effective_taxonomy, match_taxonomy
from context_router.interface_search.workspaces import WorkspaceProfile


def understand_query(query: str, profile: WorkspaceProfile | None = None) -> QueryIntent:
    normalized = " ".join(query.strip().split())
    (
        positive_text,
        negative_slots,
        negative_confidences,
        negative_constraints,
    ) = _split_negative_slots(normalized, profile)
    method_match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", normalized, re.I)
    identifiers = re.findall(
        r"/[a-zA-Z0-9_{}./:-]+"
        r"|[A-Za-z_$][\w$]*(?:Controller|Service|Api)(?:\.[A-Za-z_$][\w$]*)?"
        r"|\b[a-z][A-Za-z0-9_$]*[A-Z][A-Za-z0-9_$]*\b",
        normalized,
    )
    field_paths = _extract_field_paths(positive_text)
    field_identifiers = _extract_field_identifiers(positive_text, identifiers, field_paths)
    endpoint_identifiers = [value for value in identifiers if value not in field_identifiers]
    # Keep technical identifiers as retrieval signals, but do not let their
    # substrings masquerade as natural-language business taxonomy matches.
    semantic_text = _mask_technical_identifiers(positive_text, identifiers)
    stop = {"我", "想", "要", "一个", "接口", "的", "用来", "帮我", "请", "api"}
    entities = [token for token in tokenize(positive_text) if token not in stop and len(token) > 1]
    audiences = match_taxonomy(semantic_text, "audience", profile)
    audiences = _resolve_audience_roles(semantic_text, audiences, profile)
    explicit_audiences = list(audiences)
    domains = match_taxonomy(semantic_text, "domain", profile)
    service_hints = match_taxonomy(semantic_text, "service", profile)
    action_text = _mask_workspace_resources(semantic_text, profile)
    actions = match_taxonomy(action_text, "action", profile)
    actions = _remove_grammar_only_execute(actions, action_text)
    actions = _remove_cardinality_only_detail(actions, action_text)
    actions = _remove_field_label_actions(actions, action_text)
    actions = _refine_action_roles(action_text, actions, profile)
    resource_values = profile.match(semantic_text, "resource") if profile else []
    resource, context_resources = _resolve_resource_roles(semantic_text, domains, profile)
    resource = resource or infer_resource(semantic_text, domains, profile)
    if not resource:
        # Controller names remain a useful low-confidence family hint, but are
        # interpreted independently of workspace business vocabulary.
        resource = infer_resource(positive_text, domains, None)
    domains = _refine_domains_for_resource(domains, resource, profile)
    resource_candidates = [
        IntentCandidate(value=value, confidence=0.92, evidence=[value]) for value in resource_values
    ]
    if resource and resource not in resource_values:
        resource_candidates.append(
            IntentCandidate(
                value=resource,
                confidence=0.72,
                evidence=["controller_or_technical_name"],
            )
        )
    lookup_keys = infer_lookup_keys(positive_text, profile)
    identifier_types = [item for item in lookup_keys if not _is_generic_identifier(item)]
    binding_keys = identifier_types or [
        item for item in lookup_keys if _is_generic_identifier(item)
    ]
    if resource and binding_keys:
        # A shared alias can map to several mode-specific resources. Do not
        # manufacture a scoped identifier for an arbitrary first match.
        domain_set = set(domains)
        domain_specific_contexts = [
            value
            for value in context_resources
            if profile
            and (term := profile.term("resource", value))
            and domain_set & set(term.metadata.get("domains", []))
        ]
        identifier_owner = (
            context_resources[0]
            if len(context_resources) == 1
            else (
                domain_specific_contexts[0]
                if len(domain_specific_contexts) == 1
                else (resource if not context_resources else "")
            )
        )
        if identifier_owner:
            lookup_keys.append(f"{identifier_owner}:{_identifier_suffix(binding_keys[0])}")
        lookup_keys = list(dict.fromkeys(lookup_keys))
    if (
        _has_many_lookup_cue(positive_text)
        and "detail" not in actions
        and not set(actions)
        & {
            "create",
            "update",
            "delete",
            "cancel",
            "export",
            "approve",
            "execute",
        }
    ):
        actions.append("list")
        actions = list(dict.fromkeys(actions))
    if (
        lookup_keys
        and _has_single_lookup_cue(positive_text)
        and not _has_many_lookup_cue(positive_text)
        and not set(actions)
        & {
            "page",
            "list",
            "create",
            "update",
            "delete",
            "cancel",
            "export",
            "approve",
            "execute",
        }
    ):
        actions.append("detail")
        actions = list(dict.fromkeys(actions))
    cardinality = infer_cardinality(positive_text, actions)
    ownership = infer_ownership(positive_text)
    if lookup_keys and cardinality == "one":
        ownership = "by_id"
    positive_slots = {
        "audience": audiences,
        "domain": domains,
        "service": service_hints,
        "action": actions,
        "resource": [resource] if resource else [],
        "context_resource": context_resources,
        "lookup_key": lookup_keys,
        "identifier_type": identifier_types,
        "cardinality": [cardinality] if cardinality != "unknown" else [],
        "ownership": [ownership] if ownership != "unknown" else [],
    }
    positive_slots = {key: value for key, value in positive_slots.items() if value}
    negative_slots, negative_constraints, negative_confidences = _remove_positive_negative_overlap(
        positive_slots,
        negative_slots,
        negative_constraints,
        negative_confidences,
    )
    slot_confidences = {
        key: 0.95 if key in {"audience", "domain", "service", "action"} else 0.82
        for key in positive_slots
    }
    slot_confidences.update(negative_confidences)
    return QueryIntent(
        raw_query=query,
        normalized_query=normalized,
        positive_query=" ".join(positive_text.split()).strip("，,；;。"),
        audiences=audiences,
        domains=domains,
        actions=actions,
        entities=list(dict.fromkeys(entities))[:20],
        qualifiers=[],
        explicit_method=method_match.group(1).upper() if method_match else None,
        exact_identifiers=identifiers,
        endpoint_identifiers=endpoint_identifiers,
        field_identifiers=field_identifiers,
        field_paths=field_paths,
        schema_direction=_infer_schema_direction(positive_text),
        resource=resource,
        target_resource=resource,
        context_resources=context_resources,
        resource_candidates=resource_candidates,
        service_hints=service_hints,
        explicit_audiences=explicit_audiences,
        lookup_keys=lookup_keys,
        identifier_types=identifier_types,
        cardinality=cardinality,
        ownership=ownership,
        positive_slots=positive_slots,
        negative_slots=negative_slots,
        negative_constraints=negative_constraints,
        slot_confidences=slot_confidences,
        uncertain_slots=[],
    )


def _split_negative_slots(
    text: str, profile: WorkspaceProfile | None = None
) -> tuple[
    str,
    dict[str, list[str]],
    dict[str, float],
    list[NegativeConstraint],
]:
    """Extract clause-scoped exclusions and remove the full clause from positives."""

    masked = list(text)
    negative: dict[str, list[str]] = {}
    confidence_by_dimension: dict[str, float] = {}
    constraints: list[NegativeConstraint] = []
    prefix_marker_pattern = re.compile(
        r"不是|不要|不用|别走|别用|别查|别选|排除|不需要|无需|除外|而非|"
        r"(?<![\w\u4e00-\u9fff])别|(?<![\w\u4e00-\u9fff])非",
        re.I,
    )
    suffix_marker_pattern = re.compile(r"(?:都)?(?:别走|别动|不算|不对|不要|不用)", re.I)
    boundaries = set("，,；;。.!！？?\n")
    taxonomy = effective_taxonomy(profile)
    negative_clauses: list[tuple[int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []
    for marker_match in prefix_marker_pattern.finditer(text):
        clause_end = _next_boundary(text, marker_match.end(), boundaries)
        negative_clauses.append(
            (
                marker_match.start(),
                clause_end,
                text[marker_match.end() : clause_end].strip(),
                marker_match.group(0),
            )
        )
        occupied.append((marker_match.start(), clause_end))
    for marker_match in suffix_marker_pattern.finditer(text):
        if any(start <= marker_match.start() < end for start, end in occupied):
            continue
        clause_start = _previous_boundary(text, marker_match.start(), boundaries)
        scope = text[clause_start : marker_match.start()].strip()
        if not scope:
            continue
        negative_clauses.append(
            (
                clause_start,
                marker_match.end(),
                scope,
                marker_match.group(0),
            )
        )

    for clause_start, clause_end, scope, marker in sorted(negative_clauses):
        if not scope:
            continue
        for index in range(clause_start, clause_end):
            masked[index] = " "
        for dimension, mapping in taxonomy.items():
            for canonical, aliases in mapping.items():
                for alias in sorted({canonical, *aliases}, key=len, reverse=True):
                    alias_match = re.search(re.escape(alias), scope, re.I)
                    if not alias_match:
                        continue
                    modifier = scope[: alias_match.start()].strip()
                    structural_modifier = re.sub(
                        r"(?:一?整份|整个|整张|全部|所有)$", "", modifier
                    ).strip()
                    # Structural read shapes such as "detail" and "list" are
                    # frequently the noun suffix of a negated resource variant
                    # ("不要装货详情"). Only negate them when stated directly.
                    if (
                        dimension == "action"
                        and canonical in {"detail", "page", "list"}
                        and structural_modifier
                    ):
                        continue
                    confidence = 0.98 if not modifier else (0.9 if len(modifier) <= 4 else 0.8)
                    negative.setdefault(dimension, []).append(canonical)
                    confidence_by_dimension[dimension] = max(
                        confidence_by_dimension.get(dimension, 0), confidence
                    )
                    constraints.append(
                        NegativeConstraint(
                            slot=dimension,
                            value=canonical,
                            scope=scope,
                            marker=marker,
                            confidence=confidence,
                        )
                    )
                    break
        # Technical selectors such as a plain `id` are intentionally not part
        # of the universal taxonomy, but still need clause-scoped negation.
        for lookup_key in infer_lookup_keys(scope, profile):
            if any(
                item.slot == "lookup_key" and item.value == lookup_key and item.scope == scope
                for item in constraints
            ):
                continue
            negative.setdefault("lookup_key", []).append(lookup_key)
            confidence_by_dimension["lookup_key"] = max(
                confidence_by_dimension.get("lookup_key", 0), 0.9
            )
            constraints.append(
                NegativeConstraint(
                    slot="lookup_key",
                    value=lookup_key,
                    scope=scope,
                    marker=marker,
                    confidence=0.9,
                )
            )
    if set(negative.get("action", [])) & {"page", "list"}:
        negative.setdefault("cardinality", []).append("many")
    if "detail" in negative.get("action", []):
        negative.setdefault("cardinality", []).append("one")
    normalized_negative = {key: list(dict.fromkeys(values)) for key, values in negative.items()}
    scopes_with_selector = {item.scope for item in constraints if item.slot == "resource"}
    scopes_with_selector.update(item.scope for item in constraints if item.slot == "lookup_key")
    if scopes_with_selector and "action" in normalized_negative:
        scoped_actions = {
            item.value
            for item in constraints
            if item.slot == "action" and item.scope in scopes_with_selector
        }
        normalized_negative["action"] = [
            value for value in normalized_negative["action"] if value not in scoped_actions
        ]
        if not normalized_negative["action"]:
            normalized_negative.pop("action")
    scopes_with_lookup_key = {item.scope for item in constraints if item.slot == "lookup_key"}
    if scopes_with_lookup_key and "resource" in normalized_negative:
        scoped_resources = {
            item.value
            for item in constraints
            if item.slot == "resource" and item.scope in scopes_with_lookup_key
        }
        normalized_negative["resource"] = [
            value for value in normalized_negative["resource"] if value not in scoped_resources
        ]
        if not normalized_negative["resource"]:
            normalized_negative.pop("resource")
    confidences = {
        f"negative.{key}": confidence_by_dimension.get(key, 0.8) for key in normalized_negative
    }
    return "".join(masked), normalized_negative, confidences, constraints


def _next_boundary(text: str, start: int, boundaries: set[str]) -> int:
    return next(
        (index for index in range(start, len(text)) if text[index] in boundaries),
        len(text),
    )


def _previous_boundary(text: str, end: int, boundaries: set[str]) -> int:
    return next(
        (index + 1 for index in range(end - 1, -1, -1) if text[index] in boundaries),
        0,
    )


def _resolve_resource_roles(
    text: str,
    domains: list[str],
    profile: WorkspaceProfile | None,
) -> tuple[str, list[str]]:
    if profile is None:
        return "", []
    occurrences = profile.match_occurrences(text, "resource")
    if not occurrences:
        return "", []

    normalized = re.sub(r"[\s_-]+", "", text).lower()

    # Relationship commands normally name the object being changed before the
    # verb and the referenced object after it: "给司机绑定承运商".
    relation = re.search(r"(?:给|为)(.+?)(?:绑定|绑到|绑在|关联到|关联)(.+)", normalized)
    if relation:
        context_start = relation.start(2)
        before = [item for item in occurrences if item[2] <= context_start]
        after = [item for item in occurrences if item[1] >= context_start]
        if before:
            target = max(before, key=lambda item: (item[2], item[3]))[0]
            contexts = list(dict.fromkeys(item[0] for item in after if item[0] != target))
            return target, contexts

    def is_lookup_bound(
        occurrence: tuple[str, int, int, int, str],
    ) -> bool:
        suffix = normalized[occurrence[2] : occurrence[2] + 8]
        return bool(re.match(r"(?:id|号|编号|编码|code|no|number)", suffix, re.I))

    # Determine grammatical roles before phrase-length pruning. A resource
    # immediately followed by an identifier marker usually owns the lookup key
    # rather than the requested result (for example, "find records by source
    # order number"). Keeping those occurrences as context prevents a long
    # condition phrase from replacing a shorter but explicit target resource.
    lookup_occurrences = [item for item in occurrences if is_lookup_bound(item)]
    target_occurrences = [item for item in occurrences if not is_lookup_bound(item)]
    selection_pool = target_occurrences or occurrences

    # Select the most specific phrase first. Domain hints normally disambiguate
    # shared short aliases, but a substantially longer compound resource may
    # correct a domain inferred from a participant noun. Domain compatibility
    # is evaluated only for target-role occurrences; lookup owners are context
    # and must not force the target into their domain.
    domain_set = set(domains)
    if domain_set:
        compatible = [
            item
            for item in selection_pool
            if not (term := profile.term("resource", item[0]))
            or not term.metadata.get("domains")
            or domain_set & set(term.metadata.get("domains", []))
        ]
        if not compatible:
            strongest = max(
                selection_pool,
                key=lambda item: (
                    len(re.sub(r"[\s_-]+", "", item[4])),
                    item[3],
                ),
            )
            strongest_length = len(re.sub(r"[\s_-]+", "", strongest[4]))
            if strongest_length < 6 or strongest[3] < 50:
                return "", []
        else:
            max_all_length = max(len(re.sub(r"[\s_-]+", "", item[4])) for item in selection_pool)
            max_compatible_length = max(len(re.sub(r"[\s_-]+", "", item[4])) for item in compatible)
            if max_all_length < max_compatible_length + 2:
                selection_pool = compatible

    max_alias_length = max(len(re.sub(r"[\s_-]+", "", item[4])) for item in selection_pool)
    selection_pool = [
        item for item in selection_pool if len(re.sub(r"[\s_-]+", "", item[4])) == max_alias_length
    ]

    target = max(
        selection_pool,
        key=lambda item: (len(re.sub(r"[\s_-]+", "", item[4])), item[3], item[2]),
    )[0]
    contexts = list(dict.fromkeys(item[0] for item in lookup_occurrences if item[0] != target))
    return target, contexts


def _refine_domains_for_resource(
    domains: list[str],
    resource: str,
    profile: WorkspaceProfile | None,
) -> list[str]:
    if not profile or not resource:
        return domains
    term = profile.term("resource", resource)
    resource_domains = list((term.metadata if term else {}).get("domains", []))
    if not resource_domains:
        return domains
    compatible = [value for value in domains if value in resource_domains]
    return list(dict.fromkeys([*compatible, *resource_domains]))


def _resolve_audience_roles(
    text: str,
    audiences: list[str],
    profile: WorkspaceProfile | None,
) -> list[str]:
    """Prefer the grammatical actor over an audience mentioned as a source.

    Actor vocabulary and its audience mapping live in the workspace profile.
    The code only supplies reusable grammar, so another workspace can describe
    its own roles without adding business names here.
    """

    if profile is None:
        return audiences
    normalized = re.sub(r"[\s_-]+", "", text).lower()
    actor_audiences: list[str] = []
    for canonical, _start, end, _priority, _alias in profile.match_occurrences(text, "actor"):
        suffix = normalized[end : end + 10]
        if not re.match(
            r"(?:已经|正|正在|将|准备|想|需要|要|可以|可|来|会|需)?"
            r"(?:查询|查看|获取|接受|同意|确认|提交|新增|修改|删除|标记|设置|操作|处理)",
            suffix,
        ):
            continue
        term = profile.term("actor", canonical)
        if term:
            actor_audiences.extend(term.mapped_values.get("audience", []))
    if not actor_audiences:
        return audiences

    contextual_audiences: set[str] = set()
    for canonical, _start, end, _priority, _alias in profile.match_occurrences(text, "audience"):
        if re.match(
            r"(?:端|侧)?(?:提交|提供|发起|返回|给出|推送|传来|录入)的",
            normalized[end : end + 10],
        ):
            contextual_audiences.add(canonical)
    return list(
        dict.fromkeys(
            [
                *actor_audiences,
                *(value for value in audiences if value not in contextual_audiences),
            ]
        )
    )


def _refine_action_roles(
    text: str,
    actions: list[str],
    profile: WorkspaceProfile | None,
) -> list[str]:
    """Remove verbs that describe context or a subordinate side effect.

    Taxonomy matching intentionally favors recall. This second pass handles a
    small set of language-level scopes without knowing any business resource.
    """

    if not actions:
        return actions
    normalized = re.sub(r"[\s_-]+", "", text).lower()
    occurrences: dict[str, list[tuple[int, int, str]]] = {action: [] for action in actions}
    mapping = effective_taxonomy(profile).get("action", {})
    for action in actions:
        for alias in sorted(
            dict.fromkeys([action, *mapping.get(action, ())]),
            key=lambda value: len(re.sub(r"[\s_-]+", "", value)),
            reverse=True,
        ):
            needle = re.sub(r"[\s_-]+", "", alias).lower()
            if not needle:
                continue
            for match in re.finditer(re.escape(needle), normalized):
                occurrences[action].append((match.start(), match.end(), needle))

    read_actions = {"query", "detail", "page", "list"}
    write_actions = {"create", "update", "delete", "cancel", "approve", "execute"}
    read_positions = [item for action in read_actions for item in occurrences.get(action, [])]

    ignored: set[str] = set()
    for action in write_actions & set(actions):
        relevant = []
        for start, end, alias in occurrences.get(action, []):
            suffix = normalized[end : end + 12]
            # Participial verbs describe where data came from, not the user's
            # requested operation: "submitted quote", "generated document".
            if suffix.startswith("的"):
                continue
            if (
                action == "create"
                and any(marker in suffix for marker in ("所需", "需要的", "用的"))
                and any(position > end for position, _end, _alias in read_positions)
            ):
                continue
            relevant.append((start, end, alias))
        if not relevant:
            ignored.add(action)
            continue

        # "First ... inspect" makes the read clause the immediate target and
        # an earlier mutation only future context.
        first_position = normalized.rfind("先")
        if (
            first_position >= 0
            and any(position > first_position for position, _end, _alias in read_positions)
            and all(end <= first_position for _start, end, _alias in relevant)
        ):
            ignored.add(action)

    # Clearing a reason/note/field while confirming another object is a side
    # effect of the confirmation endpoint, not a delete-resource request.
    if "delete" in actions and ({"approve", "update"} & (set(actions) - ignored)):
        if re.search(
            r"(?:原因|备注|说明|字段|内容|值).{0,8}(?:清掉|清除|删除|移除)",
            normalized,
        ):
            ignored.add("delete")

    return [action for action in actions if action not in ignored]


def _is_generic_identifier(value: str) -> bool:
    return value.strip().lower() in {"id", "编号", "编码", "number", "code", "key"}


def _identifier_suffix(value: str) -> str:
    compact = value.strip().lower().replace("_", "").replace("-", "")
    if compact.endswith("id"):
        return "id"
    if compact.endswith(("no", "number")) or value.endswith(("号", "编号")):
        return "number"
    if compact.endswith("code") or value.endswith("编码"):
        return "code"
    return compact


def _has_single_lookup_cue(text: str) -> bool:
    lowered = text.lower().replace(" ", "")
    return bool(
        re.search(
            r"(?:根据|按|通过).{0,16}(?:查询|查看|获取|预览|详情|信息|查出|摸清|弄清|拉出)",
            lowered,
        )
        or any(
            term in lowered
            for term in (
                "详情",
                "预览",
                "单条",
                "查出来",
                "摸清",
                "弄清",
                "getbyid",
                "findone",
            )
        )
    )


def _has_many_lookup_cue(text: str) -> bool:
    lowered = text.lower().replace(" ", "")
    if any(term in lowered for term in ("汇总", "合计", "统计", "概览", "指标卡", "卡片")):
        return False
    return bool(
        re.search(
            r"(?:[二两三四五六七八九十百]+|[2-9]|[1-9]\d+)(?:条|张|份|个)",
            lowered,
        )
    ) or any(
        term in lowered
        for term in (
            "集合",
            "多个",
            "多条",
            "若干条",
            "几条",
            "几张",
            "几份",
            "一批",
            "数组",
            "一组",
            "批量查询",
        )
    )


def _mask_workspace_resources(text: str, profile: WorkspaceProfile | None) -> str:
    if profile is None:
        return text
    masked = text
    # Preserve explicit action phrases before masking resource aliases. Chinese
    # words can overlap at character boundaries (for example, "场站点开" contains
    # the resource alias "站点" and the action "点开"). A global resource
    # replacement must not erase the action evidence.
    protected_actions: dict[str, str] = {}
    action_aliases = {
        alias
        for aliases in effective_taxonomy(profile).get("action", {}).values()
        for alias in aliases
    }
    for index, alias in enumerate(sorted(action_aliases, key=len, reverse=True)):
        if not re.search(re.escape(alias), masked, re.I):
            continue
        placeholder = f"\ufff0{index}\ufff1"
        masked = re.sub(re.escape(alias), placeholder, masked, flags=re.I)
        protected_actions[placeholder] = alias
    aliases = {
        alias
        for _canonical, _start, _end, _priority, alias in profile.match_occurrences(
            masked, "resource"
        )
    }
    for alias in sorted(aliases, key=len, reverse=True):
        masked = re.sub(re.escape(alias), " ", masked, flags=re.I)
    for placeholder, alias in protected_actions.items():
        masked = masked.replace(placeholder, alias)
    return " ".join(masked.split())


def _remove_grammar_only_execute(actions: list[str], text: str) -> list[str]:
    specific = [action for action in actions if action not in {"query", "execute"}]
    if not specific or "execute" not in actions:
        return actions
    lowered = text.lower()
    if any(re.search(rf"执行\s*{re.escape(action)}\s*动作", lowered) for action in specific):
        return [action for action in actions if action != "execute"]
    return actions


def _remove_cardinality_only_detail(actions: list[str], text: str) -> list[str]:
    write_actions = {"create", "update", "delete", "cancel", "export", "approve", "execute"}
    if "detail" not in actions or not set(actions) & write_actions:
        return actions
    lowered = text.lower().replace(" ", "")
    if any(term in lowered for term in ("查看", "查询", "点开", "打开", "getbyid", "findone")):
        return actions
    return [action for action in actions if action != "detail"]


def _remove_field_label_actions(actions: list[str], text: str) -> list[str]:
    lowered = text.lower().replace(" ", "")
    cleaned = list(actions)
    if "create" in cleaned:
        without_field_labels = re.sub(r"创建(?:时间|日期|人|者)", "", lowered)
        if not any(
            cue in without_field_labels
            for cue in (
                "创建",
                "新增",
                "新建",
                "录入",
                "登记",
                "添加",
                "保存",
                "上传",
                "生成",
                "补充",
                "补一条",
                "填入",
                "记下",
            )
        ):
            cleaned = [action for action in cleaned if action != "create"]
    if "execute" in cleaned:
        without_noun_labels = re.sub(r"执行(?:批次|记录|日志|结果|状态|详情|实例)", "", lowered)
        if not any(
            cue in without_noun_labels
            for cue in ("执行", "提交", "触发", "启动", "发送", "开始作业", "开始干", "开工")
        ):
            cleaned = [action for action in cleaned if action != "execute"]
    return cleaned


def _remove_positive_negative_overlap(
    positive_slots: dict[str, list[str]],
    negative_slots: dict[str, list[str]],
    constraints: list[NegativeConstraint],
    confidences: dict[str, float],
) -> tuple[dict[str, list[str]], list[NegativeConstraint], dict[str, float]]:
    cleaned = {
        dimension: [
            value for value in values if value not in set(positive_slots.get(dimension, []))
        ]
        for dimension, values in negative_slots.items()
    }
    cleaned = {dimension: values for dimension, values in cleaned.items() if values}
    cleaned_constraints = [item for item in constraints if item.value in cleaned.get(item.slot, [])]
    cleaned_confidences = {
        key: value for key, value in confidences.items() if key.removeprefix("negative.") in cleaned
    }
    return cleaned, cleaned_constraints, cleaned_confidences


def _mask_technical_identifiers(text: str, identifiers: list[str]) -> str:
    masked = text
    for identifier in sorted(set(identifiers), key=len, reverse=True):
        masked = re.sub(re.escape(identifier), " ", masked, flags=re.I)
    return " ".join(masked.split())


def _extract_field_identifiers(
    text: str, identifiers: list[str], field_paths: list[str] | None = None
) -> list[str]:
    fields = {
        value
        for value in identifiers
        if not value.startswith("/")
        and not re.search(r"(?:Controller|Service|Api)(?:\.|$)", value)
        and re.search(r"(?:Ids?|Nos?|Codes?|Names?|Statuses?|Types?)$", value)
    }
    if not field_paths:
        for match in re.finditer(
            r"(?:字段|入参|出参|参数)\s*[:：为是]?\s*([A-Za-z_$][\w$]*)",
            text,
            re.I,
        ):
            fields.add(match.group(1))
    for path in field_paths or []:
        terminal = _field_path_terminal(path)
        if terminal:
            fields.add(terminal)
    return [value for value in dict.fromkeys([*identifiers, *fields]) if value in fields]


_FIELD_CUE = re.compile(
    r"(?:返回字段|响应字段|请求字段|请求参数|响应参数|入参|出参|字段|参数)"
    r"\s*[:：为是]?\s*",
    re.I,
)
_FIELD_PATH = re.compile(
    r"(?<![A-Za-z0-9_$])"
    r"(?:\[\]|[A-Za-z_$][\w$]*(?:\[\])?)"
    r"(?:\.(?:\[\]|[A-Za-z_$][\w$]*(?:\[\])?))*"
)


def _extract_field_paths(text: str) -> list[str]:
    """Extract technical field paths only from a schema-directed query segment."""

    paths: list[str] = []
    for cue in _FIELD_CUE.finditer(text):
        segment = re.split(r"[，。；;！？!?<]", text[cue.end() :], maxsplit=1)[0][:160]
        for match in _FIELD_PATH.finditer(segment):
            value = match.group(0).strip(".")
            if value.lower() in {
                "and",
                "or",
                "json",
                "api",
                "http",
                "get",
                "post",
                "put",
                "patch",
                "delete",
            }:
                continue
            paths.append(value)
    return list(dict.fromkeys(paths))


def _field_path_terminal(path: str) -> str:
    parts = [part.removesuffix("[]") for part in path.split(".")]
    return next((part for part in reversed(parts) if part), "")


def _infer_schema_direction(text: str) -> str:
    request = any(cue in text for cue in ("请求字段", "请求参数", "入参", "传入", "需要传"))
    response = any(cue in text for cue in ("返回字段", "响应字段", "响应参数", "出参"))
    if request and not response:
        return "request"
    if response and not request:
        return "response"
    return "unknown"
