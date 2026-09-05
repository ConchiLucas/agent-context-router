from __future__ import annotations

from context_router.interface_search.domain import (
    InterfaceResolutionOption,
    InterfaceResolutionResponse,
    SearchResponse,
)


def resolve_for_user(response: SearchResponse) -> InterfaceResolutionResponse:
    """Turn shared retrieval results into one recommendation or a small user choice.

    The gate deliberately uses only exact evidence, score separation and conflicts.
    It does not call an LLM and contains no workspace-specific rules.
    """

    if not response.hits:
        return InterfaceResolutionResponse(
            search_id=response.search_id,
            workspace_id=response.workspace_id,
            query=response.query,
            status="no_candidate",
            reason="没有找到候选接口，请补充业务对象、动作或所属服务。",
            elapsed_ms=response.elapsed_ms,
        )

    first = response.hits[0]
    exact = first.score.exact >= 0.95
    strong_structured_match = len(first.matched_slots) >= 2 and not first.conflicting_slots
    separated = response.top_margin >= 0.12
    reliable = exact or (separated and strong_structured_match)
    options = [_option(hit) for hit in response.hits[:3]]
    if reliable:
        reason = (
            "接口路径或操作标识精确命中。"
            if exact
            else "第一名同时匹配多个明确条件，并与其他候选保持足够分差。"
        )
        return InterfaceResolutionResponse(
            search_id=response.search_id,
            workspace_id=response.workspace_id,
            query=response.query,
            status="resolved",
            selected_interface_id=first.interface_id,
            recommended_interface_id=first.interface_id,
            reason=reason,
            options=options[:1],
            elapsed_ms=response.elapsed_ms,
        )

    return InterfaceResolutionResponse(
        search_id=response.search_id,
        workspace_id=response.workspace_id,
        query=response.query,
        status="needs_selection",
        recommended_interface_id=first.interface_id,
        reason="候选已经缩小，但现有证据不足以安全地自动确定唯一接口。",
        question="请选择更符合需求的接口用途。",
        options=options,
        elapsed_ms=response.elapsed_ms,
    )


def _option(hit) -> InterfaceResolutionOption:
    return InterfaceResolutionOption(
        interface_id=hit.interface_id,
        method=hit.method,
        path=hit.path,
        title=hit.title,
        purpose=hit.purpose,
        audiences=hit.audiences,
        domains=hit.domains,
        resource=hit.resource,
        actions=hit.actions,
        lookup_keys=hit.lookup_keys,
        discriminators=hit.discriminators,
        matched_evidence=hit.reasons[:3],
    )
