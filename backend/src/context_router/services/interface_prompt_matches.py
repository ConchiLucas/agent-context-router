from __future__ import annotations

import re

from context_router.interface_search.comparison import compare_interfaces
from context_router.interface_search.domain import SearchHit, SearchRequest, SearchResponse
from context_router.interface_search.resolution import resolve_for_user
from context_router.interface_search.search import SearchService
from context_router.repositories.database_environment_repository import DatabaseEnvironmentStore
from context_router.repositories.interface_prompt_match_repository import (
    InterfacePromptMatchRecord,
    InterfacePromptMatchRepositoryError,
    InterfacePromptMatchStore,
    new_prompt_match_record,
)
from context_router.repositories.workspace_repository import (
    WorkspaceRepositoryError,
    WorkspaceStore,
)
from context_router.schemas.interface_prompt_matches import (
    InterfacePromptClientJudgment,
    InterfacePromptClientResultImport,
    InterfacePromptClientResultImportResponse,
    InterfacePromptClientResultReset,
    InterfacePromptClientStoredResultReset,
    InterfacePromptIdentity,
    InterfacePromptMatch,
    InterfacePromptMatchCandidate,
    InterfacePromptMatchCreate,
    InterfacePromptMatchList,
    PromptClientName,
)
from context_router.services.interface_prompt_clients import (
    CLIENT_AGENTS,
    EmptyInterfaceClientJudgmentFinder,
    InterfaceClientJudgmentFinder,
    attach_client_judgments,
)

VISIBLE_CANDIDATE_LIMIT = 3
STORED_CANDIDATE_LIMIT = 20
_ENVIRONMENT_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class InterfacePromptMatchError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        not_found: bool = False,
        unavailable: bool = False,
        conflict: bool = False,
    ) -> None:
        super().__init__(message)
        self.not_found = not_found
        self.unavailable = unavailable
        self.conflict = conflict


class InterfacePromptMatchService:
    def __init__(
        self,
        repository: InterfacePromptMatchStore,
        workspaces: WorkspaceStore,
        environments: DatabaseEnvironmentStore,
        search_service: SearchService | None,
        client_finder: InterfaceClientJudgmentFinder | None = None,
    ) -> None:
        self._repository = repository
        self._workspaces = workspaces
        self._environments = environments
        self._search_service = search_service
        self._client_finder = client_finder or EmptyInterfaceClientJudgmentFinder()

    def preview_client_result_reset(
        self,
        workspace_id: str,
        *,
        client: str,
    ) -> InterfacePromptClientResultReset:
        workspace = self._validated_reset_scope(workspace_id, client)
        counts = self._client_finder.preview_reset(workspace_id=workspace, client=client)
        return InterfacePromptClientResultReset(
            workspace_id=workspace,
            client="antigravity",
            matched_task_count=counts.task_count,
            matched_tool_call_count=counts.tool_call_count,
        )

    def reset_client_results(
        self,
        workspace_id: str,
        *,
        client: str,
        expected_task_count: int,
        expected_tool_call_count: int,
    ) -> InterfacePromptClientResultReset:
        workspace = self._validated_reset_scope(workspace_id, client)
        try:
            counts = self._client_finder.reset_results(
                workspace_id=workspace,
                client=client,
                expected_task_count=expected_task_count,
                expected_tool_call_count=expected_tool_call_count,
            )
        except ValueError as exc:
            raise InterfacePromptMatchError(str(exc), conflict=True) from exc
        return InterfacePromptClientResultReset(
            workspace_id=workspace,
            client="antigravity",
            matched_task_count=counts.task_count,
            matched_tool_call_count=counts.tool_call_count,
            deleted_task_count=counts.task_count,
        )

    def _validated_reset_scope(self, workspace_id: str, client: str) -> str:
        workspace = workspace_id.strip()
        if not workspace:
            raise InterfacePromptMatchError("工作空间不能为空")
        if client != "antigravity":
            raise InterfacePromptMatchError("仅允许重置 Antigravity 接口测试结果")
        self._require_workspace(workspace)
        return workspace

    def list_matches(
        self,
        workspace_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        prioritize_returned_for: PromptClientName | None = None,
    ) -> InterfacePromptMatchList:
        workspace = workspace_id.strip()
        if not workspace:
            raise InterfacePromptMatchError("工作空间不能为空")
        self._require_workspace(workspace)
        size = min(max(page_size, 1), 100)
        current = max(page, 1)
        total = self._repository.count_for_workspace(workspace)
        has_imported_priority = (
            prioritize_returned_for is not None
            and self._repository.count_client_results(workspace, prioritize_returned_for) > 0
        )
        priority = (
            self._client_finder.returned_prompt_keys(
                workspace_id=workspace,
                client=prioritize_returned_for,
            )
            if prioritize_returned_for is not None and not has_imported_priority
            else None
        )
        items = self._repository.list_for_workspace(
            workspace,
            limit=size,
            offset=(current - 1) * size,
            prioritized_prompt_digests=() if priority is None else priority.digests,
            prioritized_prompts=() if priority is None else priority.prompts,
            prioritized_client=prioritize_returned_for,
        )
        return InterfacePromptMatchList(
            items=[self._schema(item) for item in items],
            total=total,
            page=current,
            page_size=size,
        )

    def import_client_results(
        self, payload: InterfacePromptClientResultImport
    ) -> InterfacePromptClientResultImportResponse:
        workspace = payload.workspace_id.strip()
        self._require_workspace(workspace)
        prepared: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for item in payload.records:
            key = (item.record_id, item.client)
            if key in seen:
                raise InterfacePromptMatchError(
                    f"同一请求中记录与客户端重复：{item.record_id}/{item.client}"
                )
            seen.add(key)
            if item.status == "selected":
                if not item.selected_interface_id:
                    raise InterfacePromptMatchError("selected 结果必须包含 selected_interface_id")
                if not item.detail_read:
                    raise InterfacePromptMatchError("selected 结果必须有详情读取证据")
                if self._lookup_identity(item.selected_interface_id) is None:
                    raise InterfacePromptMatchError(f"选定接口不存在：{item.selected_interface_id}")
            elif item.selected_interface_id:
                raise InterfacePromptMatchError("非 selected 结果不能包含 selected_interface_id")
            if item.status == "needs_clarification" and (
                not item.compared or len(item.compared_interface_ids) < 2
            ):
                raise InterfacePromptMatchError("澄清结果必须包含至少两个已比较接口")
            prepared.append(
                {
                    "record_id": item.record_id,
                    "client": item.client,
                    "task_id": item.task_id,
                    "batch_id": item.batch_id,
                    "model": item.model,
                    "reasoning_effort": item.reasoning_effort,
                    "source_file": item.source_file,
                    "payload": {
                        "status": item.status,
                        "selected_interface_id": item.selected_interface_id,
                        "clarification_question": item.clarification_question,
                        "ambiguity_dimensions": item.ambiguity_dimensions,
                        "candidate_interface_ids": item.candidate_interface_ids,
                        "compared_interface_ids": item.compared_interface_ids,
                        "searched": item.searched,
                        "compared": item.compared,
                        "detail_read": item.detail_read,
                    },
                }
            )
        imported = self._repository.import_client_results(workspace, prepared)
        return InterfacePromptClientResultImportResponse(
            workspace_id=workspace,
            imported_count=imported,
        )

    def delete_stored_client_results(
        self,
        workspace_id: str,
        *,
        client: PromptClientName,
        expected_count: int,
    ) -> InterfacePromptClientStoredResultReset:
        workspace = workspace_id.strip()
        self._require_workspace(workspace)
        matched = self._repository.count_client_results(workspace, client)
        try:
            deleted = self._repository.delete_client_results(workspace, client, expected_count)
        except ValueError as exc:
            raise InterfacePromptMatchError(str(exc), conflict=True) from exc
        return InterfacePromptClientStoredResultReset(
            workspace_id=workspace,
            client=client,
            matched_result_count=matched,
            deleted_result_count=deleted,
        )

    def delete_matches(self, workspace_id: str) -> int:
        workspace = workspace_id.strip()
        if not workspace:
            raise InterfacePromptMatchError("工作空间不能为空")
        self._require_workspace(workspace)
        return self._repository.delete_for_workspace(workspace)

    def create_match(self, payload: InterfacePromptMatchCreate) -> InterfacePromptMatch:
        if self._search_service is None:
            raise InterfacePromptMatchError("接口检索未配置", unavailable=True)
        workspace_id = payload.workspace_id.strip()
        prompt = payload.prompt.strip()
        if not workspace_id:
            raise InterfacePromptMatchError("工作空间不能为空")
        if not prompt:
            raise InterfacePromptMatchError("提示词不能为空")
        self._require_workspace(workspace_id)
        environment_key = self._environment_key(workspace_id, payload.environment_key)
        response = self._search_service.search(
            SearchRequest(
                workspace_id=workspace_id,
                query=prompt,
                top_k=STORED_CANDIDATE_LIMIT,
            )
        )
        resolution = resolve_for_user(response)
        candidates = [_candidate(hit) for hit in response.hits[:STORED_CANDIDATE_LIMIT]]
        expected = self._expected_identity(payload.expected_interface_id)
        record = new_prompt_match_record(
            workspace_id=workspace_id,
            environment_key=environment_key,
            prompt=prompt,
            verdict=resolution.status,
            first_interface_id=resolution.selected_interface_id
            or resolution.recommended_interface_id,
            candidates=candidates,
            remaining_count=max(0, len(response.hits) - VISIBLE_CANDIDATE_LIMIT),
            search_id=response.search_id,
            reason=resolution.reason,
            differing_dimensions=self._differing_dimensions(response, resolution.status),
            expected_interface_id=None if expected is None else expected.interface_id,
            expected_method="" if expected is None else expected.method,
            expected_path="" if expected is None else expected.path,
            expected_title="" if expected is None else expected.title,
            note=payload.note.strip(),
        )
        return self._schema(self._repository.insert(record))

    def _require_workspace(self, workspace_id: str) -> None:
        try:
            self._workspaces.get_workspace(workspace_id)
        except WorkspaceRepositoryError as exc:
            raise InterfacePromptMatchError(str(exc), not_found="不存在" in str(exc)) from exc

    def _environment_key(self, workspace_id: str, raw: str) -> str:
        key = (raw or "local").strip().lower() or "local"
        if not _ENVIRONMENT_KEY.fullmatch(key):
            raise InterfacePromptMatchError("环境键不合法")
        if not self._environments.has_environment(workspace_id, key):
            raise InterfacePromptMatchError(f"环境 {key} 未登记")
        return key

    def _differing_dimensions(self, response: SearchResponse, verdict: str) -> list[str]:
        if verdict != "needs_selection":
            return []
        hits = response.hits[:VISIBLE_CANDIDATE_LIMIT]
        if len(hits) < 2 or self._search_service is None:
            return []
        endpoints = []
        for hit in hits:
            endpoint = self._search_service.repository.get(hit.interface_id)
            if endpoint is None:
                return _differing_from_hits(hits)
            endpoints.append(endpoint)
        try:
            return list(compare_interfaces(endpoints).differing_dimensions)
        except ValueError:
            return _differing_from_hits(hits)

    def _schema(self, record: InterfacePromptMatchRecord) -> InterfacePromptMatch:
        candidates = [
            InterfacePromptMatchCandidate.model_validate(item) for item in record.candidates
        ]
        return InterfacePromptMatch(
            id=record.id,
            workspace_id=record.workspace_id,
            environment_key=record.environment_key,
            prompt=record.prompt,
            verdict=record.verdict,  # type: ignore[arg-type]
            first_interface_id=record.first_interface_id,
            candidates=candidates,
            remaining_count=record.remaining_count,
            search_id=record.search_id,
            reason=record.reason,
            differing_dimensions=list(record.differing_dimensions),
            created_at=record.created_at,
            note=record.note,
            expected=self._expected_from_record(record),
            clients=self._client_judgments(record, candidates),
        )

    def _client_judgments(
        self,
        record: InterfacePromptMatchRecord,
        candidates: list[InterfacePromptMatchCandidate],
    ) -> list[InterfacePromptClientJudgment]:
        imported = {
            str(item.get("client")): item
            for item in record.client_results
            if isinstance(item, dict)
        }
        if imported:
            return [
                self._imported_judgment(imported[client], candidates)
                if client in imported
                else InterfacePromptClientJudgment(
                    client=client,  # type: ignore[arg-type]
                    status="missing",
                    reason="该题未由此执行者运行。",
                )
                for client in CLIENT_AGENTS
            ]
        return attach_client_judgments(
            workspace_id=record.workspace_id,
            record_id=record.id,
            prompt=record.prompt,
            candidates=candidates,
            finder=self._client_finder,
            lookup=self._lookup_identity,
        )

    def _imported_judgment(
        self,
        item: dict[str, object],
        candidates: list[InterfacePromptMatchCandidate],
    ) -> InterfacePromptClientJudgment:
        raw_status = str(item.get("status", ""))
        status = {
            "selected": "selected",
            "needs_clarification": "clarify",
            "tool_failure": "failed",
        }.get(raw_status, "failed")
        selected_id = item.get("selected_interface_id")
        selected_id = selected_id if isinstance(selected_id, str) and selected_id else None
        identity = self._lookup_identity(selected_id) if selected_id else None
        candidate_ids = {candidate.interface_id for candidate in candidates}
        compared_ids = item.get("compared_interface_ids")
        compared_ids = (
            [str(value) for value in compared_ids if isinstance(value, str)]
            if isinstance(compared_ids, list)
            else []
        )
        reason = {
            "selected": "已导入经审核的模型最终选择。",
            "clarify": str(item.get("clarification_question") or "模型判定需要澄清。"),
            "failed": "模型执行工具失败。",
        }[status]
        return InterfacePromptClientJudgment(
            client=str(item["client"]),  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            task_id=int(item["task_id"]),
            selected_interface_id=selected_id,
            selected_method=None if identity is None else identity.method,
            selected_path=None if identity is None else identity.path,
            selected_title=None if identity is None else identity.title,
            in_candidates=None if selected_id is None else selected_id in candidate_ids,
            compared=bool(item.get("compared")),
            compared_interface_ids=compared_ids,
            detailed_interface_ids=[selected_id] if selected_id else [],
            tool_calls=(["search_forwarding_interfaces"] if item.get("searched") else [])
            + (["compare_forwarding_interfaces"] if item.get("compared") else [])
            + (["read_forwarding_interface_detail"] if item.get("detail_read") else []),
            reason=reason,
        )

    def _expected_identity(self, raw: str | None) -> InterfacePromptIdentity | None:
        interface_id = (raw or "").strip()
        if not interface_id:
            return None
        identity = self._lookup_identity(interface_id)
        if identity is None:
            raise InterfacePromptMatchError("正确接口不存在")
        return identity

    def _expected_from_record(
        self, record: InterfacePromptMatchRecord
    ) -> InterfacePromptIdentity | None:
        if record.expected_interface_id:
            looked = self._lookup_identity(record.expected_interface_id)
            if looked is not None:
                return looked
        if not (record.expected_interface_id or record.expected_method or record.expected_path):
            return None
        return InterfacePromptIdentity(
            interface_id=record.expected_interface_id,
            method=record.expected_method,
            path=record.expected_path,
            title=record.expected_title,
        )

    def _lookup_identity(self, interface_id: str) -> InterfacePromptIdentity | None:
        if self._search_service is None:
            return None
        endpoint = self._search_service.repository.get(interface_id)
        if endpoint is None:
            return None
        return InterfacePromptIdentity(
            interface_id=endpoint.id,
            method=endpoint.method,
            path=endpoint.path,
            title=endpoint.title,
            service=endpoint.service,
        )


def _candidate(hit: SearchHit) -> dict[str, object]:
    return {
        "interface_id": hit.interface_id,
        "method": hit.method,
        "path": hit.path,
        "title": hit.title,
        "service": hit.service,
        "controller_name": hit.controller_name,
        "audiences": list(hit.audiences),
        "domains": list(hit.domains),
        "resource": hit.resource,
        "actions": list(hit.actions),
        "discriminators": list(hit.discriminators)[:6],
        "reasons": list(hit.reasons)[:3],
        "matched_slots": list(hit.matched_slots),
        "conflicting_slots": list(hit.conflicting_slots),
    }


def _differing_from_hits(hits: list[SearchHit]) -> list[str]:
    dimensions = {
        "audiences": [list(hit.audiences) for hit in hits],
        "domains": [list(hit.domains) for hit in hits],
        "resource": [[hit.resource] if hit.resource else [] for hit in hits],
        "actions": [list(hit.actions) for hit in hits],
    }
    return [
        name
        for name, values in dimensions.items()
        if len({tuple(sorted(item)) for item in values}) > 1
    ]


def http_status_for_prompt_match_error(
    exc: InterfacePromptMatchError | InterfacePromptMatchRepositoryError,
) -> int:
    if isinstance(exc, InterfacePromptMatchError) and exc.unavailable:
        return 503
    if isinstance(exc, InterfacePromptMatchError) and exc.not_found:
        return 404
    if isinstance(exc, InterfacePromptMatchError) and exc.conflict:
        return 409
    if isinstance(exc, InterfacePromptMatchRepositoryError) and str(exc) == "控制面数据库未配置":
        return 503
    return 400
