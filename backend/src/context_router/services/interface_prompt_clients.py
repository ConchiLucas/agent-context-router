from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import psycopg

from context_router.mcp_contract import CONTEXT_ROUTER_INTERFACE_FORWARDING_TOOL_NAMES
from context_router.repositories.interface_prompt_match_repository import (
    InterfacePromptMatchRepositoryError,
)
from context_router.repositories.mcp_tool_call_repository import (
    McpToolCallRecord,
    McpToolCallStore,
)
from context_router.schemas.interface_prompt_matches import (
    InterfacePromptClientJudgment,
    InterfacePromptIdentity,
    InterfacePromptMatchCandidate,
)

InterfaceIdentityLookup = Callable[[str], InterfacePromptIdentity | None]

CLIENT_AGENTS = (
    "codex",
    "codex-root",
    "codex-astra",
    "cursor",
    "antigravity",
    "grok-heavy",
)
(
    SEARCH_TOOL,
    COMPARE_TOOL,
    DETAIL_TOOL,
    _HISTORY_TOOL,
    PREPARE_REQUEST_TOOL,
    EXECUTE_REQUEST_TOOL,
) = CONTEXT_ROUTER_INTERFACE_FORWARDING_TOOL_NAMES
PROHIBITED_TOOLS = frozenset(
    {
        PREPARE_REQUEST_TOOL,
        EXECUTE_REQUEST_TOOL,
        "apply_workspace_changes",
        "start_workspace",
    }
)


@dataclass(frozen=True, slots=True)
class ReturnedPromptKeys:
    digests: frozenset[str] = frozenset()
    prompts: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class InterfaceClientResultCounts:
    task_count: int = 0
    tool_call_count: int = 0


class InterfaceClientJudgmentFinder(Protocol):
    def find_latest_calls(
        self,
        *,
        workspace_id: str,
        record_id: str,
        prompt: str,
    ) -> dict[str, tuple[int, list[McpToolCallRecord]]]: ...

    def returned_prompt_keys(
        self,
        *,
        workspace_id: str,
        client: str,
    ) -> ReturnedPromptKeys: ...

    def preview_reset(self, *, workspace_id: str, client: str) -> InterfaceClientResultCounts: ...

    def reset_results(
        self,
        *,
        workspace_id: str,
        client: str,
        expected_task_count: int,
        expected_tool_call_count: int,
    ) -> InterfaceClientResultCounts: ...


class EmptyInterfaceClientJudgmentFinder:
    def find_latest_calls(
        self,
        *,
        workspace_id: str,
        record_id: str,
        prompt: str,
    ) -> dict[str, tuple[int, list[McpToolCallRecord]]]:
        return {}

    def returned_prompt_keys(
        self,
        *,
        workspace_id: str,
        client: str,
    ) -> ReturnedPromptKeys:
        return ReturnedPromptKeys()

    def preview_reset(self, *, workspace_id: str, client: str) -> InterfaceClientResultCounts:
        return InterfaceClientResultCounts()

    def reset_results(
        self,
        *,
        workspace_id: str,
        client: str,
        expected_task_count: int,
        expected_tool_call_count: int,
    ) -> InterfaceClientResultCounts:
        return InterfaceClientResultCounts()


@dataclass(frozen=True, slots=True)
class _TaskHit:
    agent: str
    task_id: int


class PostgresInterfaceClientJudgmentFinder:
    def __init__(self, database_url: str | None, tool_calls: McpToolCallStore) -> None:
        self._database_url = database_url.strip() if database_url else None
        self._tool_calls = tool_calls

    def find_latest_calls(
        self,
        *,
        workspace_id: str,
        record_id: str,
        prompt: str,
    ) -> dict[str, tuple[int, list[McpToolCallRecord]]]:
        if not self._database_url:
            return {}
        try:
            with psycopg.connect(self._database_url) as connection:
                found = self._find_record_scoped_calls(
                    connection,
                    workspace_id=workspace_id,
                    record_id=record_id,
                )
                if self._prompt_record_count(connection, workspace_id, prompt) == 1:
                    for agent, hit in self._find_legacy_prompt_calls(
                        connection,
                        workspace_id=workspace_id,
                        prompt=prompt,
                    ).items():
                        found.setdefault(agent, hit)
                return found
        except psycopg.Error:
            return {}

    def _find_record_scoped_calls(
        self,
        connection: psycopg.Connection,
        *,
        workspace_id: str,
        record_id: str,
    ) -> dict[str, tuple[int, list[McpToolCallRecord]]]:
        rows = connection.execute(
            """
            SELECT DISTINCT ON (lower(task.agent_name))
                   lower(task.agent_name), task.id,
                   call.trace_context->>'run_id', call.id
              FROM mcp_tasks AS task
              JOIN mcp_tool_calls AS call
                ON call.task_id = task.id
             WHERE task.workspace_id = %s
               AND lower(task.agent_name) = ANY(%s)
               AND call.trace_context->>'item_id' = %s
               AND nullif(call.trace_context->>'run_id', '') IS NOT NULL
             ORDER BY lower(task.agent_name), call.id DESC
            """,
            (workspace_id, list(CLIENT_AGENTS), record_id),
        ).fetchall()
        found: dict[str, tuple[int, list[McpToolCallRecord]]] = {}
        for row in rows:
            agent = str(row[0])
            task_id = int(row[1])
            run_id = str(row[2])
            found[agent] = (
                task_id,
                self._tool_calls.list_calls(
                    task_id,
                    run_id=run_id,
                    item_id=record_id,
                ),
            )
        return found

    def _find_legacy_prompt_calls(
        self,
        connection: psycopg.Connection,
        *,
        workspace_id: str,
        prompt: str,
    ) -> dict[str, tuple[int, list[McpToolCallRecord]]]:
        digest = prompt_query_sha256(prompt)
        rows = connection.execute(
            """
            SELECT DISTINCT ON (lower(task.agent_name))
                   lower(task.agent_name), task.id
              FROM mcp_tasks AS task
              JOIN mcp_tool_calls AS call
                ON call.task_id = task.id
             WHERE task.workspace_id = %s
               AND lower(task.agent_name) = ANY(%s)
               AND (
                    (
                        call.tool_name = %s
                        AND call.request_summary->>'query_sha256' = %s
                        AND call.trace_context IS NULL
                    )
                    OR (
                        btrim(task.task) = %s
                        AND NOT EXISTS (
                            SELECT 1
                              FROM mcp_tool_calls AS correlated_call
                             WHERE correlated_call.task_id = task.id
                               AND correlated_call.trace_context IS NOT NULL
                        )
                    )
               )
             ORDER BY lower(task.agent_name), task.id DESC
            """,
            (workspace_id, list(CLIENT_AGENTS), SEARCH_TOOL, digest, prompt),
        ).fetchall()
        return {
            str(row[0]): (int(row[1]), self._tool_calls.list_calls(int(row[1]))) for row in rows
        }

    @staticmethod
    def _prompt_record_count(
        connection: psycopg.Connection,
        workspace_id: str,
        prompt: str,
    ) -> int:
        row = connection.execute(
            """SELECT count(*)
                 FROM interface_prompt_matches
                WHERE workspace_id = %s AND btrim(prompt) = %s""",
            (workspace_id, prompt.strip()),
        ).fetchone()
        return int(row[0]) if row else 0

    def returned_prompt_keys(
        self,
        *,
        workspace_id: str,
        client: str,
    ) -> ReturnedPromptKeys:
        if not self._database_url or client not in CLIENT_AGENTS:
            return ReturnedPromptKeys()
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT task.id, btrim(task.task), call.id, call.tool_name,
                           call.status, call.request_summary
                      FROM mcp_tasks AS task
                      JOIN mcp_tool_calls AS call
                        ON call.task_id = task.id
                     WHERE task.workspace_id = %s
                       AND lower(task.agent_name) = %s
                       AND call.tool_name IN (%s, %s)
                     ORDER BY task.id, call.id
                    """,
                    (workspace_id, client, SEARCH_TOOL, DETAIL_TOOL),
                ).fetchall()
        except psycopg.Error:
            return ReturnedPromptKeys()
        return _returned_prompt_keys(rows)

    def preview_reset(self, *, workspace_id: str, client: str) -> InterfaceClientResultCounts:
        if not self._database_url:
            return InterfaceClientResultCounts()
        try:
            with psycopg.connect(self._database_url) as connection:
                task_ids = self._matching_task_ids(connection, workspace_id, client)
                return self._counts(connection, task_ids)
        except psycopg.Error as exc:
            raise InterfacePromptMatchRepositoryError("读取客户端测试结果失败") from exc

    def reset_results(
        self,
        *,
        workspace_id: str,
        client: str,
        expected_task_count: int,
        expected_tool_call_count: int,
    ) -> InterfaceClientResultCounts:
        if not self._database_url:
            return InterfaceClientResultCounts()
        try:
            with psycopg.connect(self._database_url) as connection:
                task_ids = self._matching_task_ids(connection, workspace_id, client)
                counts = self._counts(connection, task_ids)
                if counts != InterfaceClientResultCounts(
                    task_count=expected_task_count,
                    tool_call_count=expected_tool_call_count,
                ):
                    raise ValueError("客户端测试结果已变化，请重新预览后再删除")
                if task_ids:
                    connection.execute(
                        "DELETE FROM mcp_tasks WHERE id = ANY(%s)",
                        (task_ids,),
                    )
                return counts
        except psycopg.Error as exc:
            raise InterfacePromptMatchRepositoryError("删除客户端测试结果失败") from exc

    @staticmethod
    def _matching_task_ids(
        connection: psycopg.Connection,
        workspace_id: str,
        client: str,
    ) -> list[int]:
        rows = connection.execute(
            """
            SELECT task.id
              FROM mcp_tasks AS task
             WHERE task.workspace_id = %s
               AND lower(task.agent_name) = %s
               AND (
                    EXISTS (
                        SELECT 1
                          FROM interface_prompt_matches AS prompt_match
                         WHERE prompt_match.workspace_id = task.workspace_id
                           AND btrim(prompt_match.prompt) = btrim(task.task)
                    )
                    OR EXISTS (
                        SELECT 1
                          FROM mcp_tool_calls AS call
                          JOIN interface_prompt_matches AS prompt_match
                            ON prompt_match.workspace_id = task.workspace_id
                           AND call.request_summary->>'query_sha256' = encode(
                               sha256(convert_to(btrim(prompt_match.prompt), 'UTF8')),
                               'hex'
                           )
                         WHERE call.task_id = task.id
                           AND call.tool_name = %s
                    )
               )
             ORDER BY task.id
            """,
            (workspace_id, client, SEARCH_TOOL),
        ).fetchall()
        return [int(row[0]) for row in rows]

    @staticmethod
    def _counts(
        connection: psycopg.Connection,
        task_ids: list[int],
    ) -> InterfaceClientResultCounts:
        if not task_ids:
            return InterfaceClientResultCounts()
        row = connection.execute(
            "SELECT count(*) FROM mcp_tool_calls WHERE task_id = ANY(%s)",
            (task_ids,),
        ).fetchone()
        return InterfaceClientResultCounts(
            task_count=len(task_ids),
            tool_call_count=int(row[0]) if row else 0,
        )


def prompt_query_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()


def _returned_prompt_keys(rows: list[tuple[object, ...]]) -> ReturnedPromptKeys:
    tasks: dict[int, tuple[str, list[tuple[int, str, str, dict[str, object]]]]] = {}
    for row in rows:
        task_id = int(row[0])
        task_prompt = str(row[1] or "").strip()
        calls = tasks.setdefault(task_id, (task_prompt, []))[1]
        calls.append(
            (
                int(row[2]),
                str(row[3]),
                str(row[4]),
                row[5] if isinstance(row[5], dict) else {},
            )
        )

    digest_states: dict[str, tuple[int, int, bool]] = {}
    prompt_states: dict[str, tuple[int, bool]] = {}
    for task_id, (task_prompt, calls) in tasks.items():
        searches = [
            index
            for index, call in enumerate(calls)
            if call[1] == SEARCH_TOOL and call[2] != "cancelled"
        ]
        search_states: dict[str, tuple[int, bool]] = {}
        for position, start in enumerate(searches):
            digest = calls[start][3].get("query_sha256")
            if not isinstance(digest, str) or not digest:
                continue
            end = searches[position + 1] if position + 1 < len(searches) else len(calls)
            returned = any(
                call[1] == DETAIL_TOOL and call[2] != "cancelled" for call in calls[start:end]
            )
            search_states[digest] = (calls[start][0], returned)
            digest_states[digest] = (task_id, calls[start][0], returned)

        if task_prompt:
            matching_search = search_states.get(prompt_query_sha256(task_prompt))
            returned = (
                matching_search[1]
                if matching_search is not None
                else any(call[1] == DETAIL_TOOL and call[2] != "cancelled" for call in calls)
            )
            prompt_states[task_prompt] = (task_id, returned)

    return ReturnedPromptKeys(
        digests=frozenset(
            digest for digest, (_task_id, _call_id, returned) in digest_states.items() if returned
        ),
        prompts=frozenset(
            prompt for prompt, (_task_id, returned) in prompt_states.items() if returned
        ),
    )


def attach_client_judgments(
    *,
    workspace_id: str,
    record_id: str,
    prompt: str,
    candidates: list[InterfacePromptMatchCandidate],
    finder: InterfaceClientJudgmentFinder,
    lookup: InterfaceIdentityLookup | None = None,
) -> list[InterfacePromptClientJudgment]:
    found = finder.find_latest_calls(
        workspace_id=workspace_id,
        record_id=record_id,
        prompt=prompt,
    )
    by_id = {item.interface_id: item for item in candidates}
    judgments = []
    for agent in CLIENT_AGENTS:
        hit = found.get(agent)
        if hit is None:
            judgments.append(
                InterfacePromptClientJudgment(
                    client=agent,
                    status="missing",
                    reason="尚未有该客户端的 MCP 裁定",
                )
            )
            continue
        task_id, calls = hit
        judgments.append(
            build_client_judgment(
                agent,
                task_id,
                calls,
                by_id,
                lookup=lookup,
                prompt=prompt,
            )
        )
    return judgments


def build_client_judgment(
    client: str,
    task_id: int,
    calls: list[McpToolCallRecord],
    candidates: dict[str, InterfacePromptMatchCandidate],
    lookup: InterfaceIdentityLookup | None = None,
    prompt: str = "",
) -> InterfacePromptClientJudgment:
    scoped = _calls_for_prompt(calls, prompt)
    tool_calls = [call.tool_name for call in scoped]
    prohibited = [name for name in tool_calls if name in PROHIBITED_TOOLS]
    compared_ids = _ids_from_calls(scoped, COMPARE_TOOL, "interface_ids")
    detailed_ids = _ids_from_calls(scoped, DETAIL_TOOL, "interface_id")
    searched = any(call.tool_name == SEARCH_TOOL and call.status != "cancelled" for call in scoped)
    search_failed = any(call.tool_name == SEARCH_TOOL and call.status == "error" for call in scoped)
    selected_id = detailed_ids[-1] if detailed_ids else None
    selected = _selected_identity(selected_id, candidates, lookup)

    if prohibited:
        status = "violated"
        reason = "检索任务调用了禁止的准备/执行或工作空间写工具。"
    elif search_failed:
        status = "failed"
        reason = "search_forwarding_interfaces 调用失败。"
    elif selected_id:
        status = "selected"
        reason = "已读取接口合同，按最后一次详情视为选定。"
    elif compared_ids:
        status = "clarify"
        reason = "已比较候选但未读取合同，按协议应澄清或继续读详情。"
    elif searched:
        status = "searching"
        reason = "已搜索，尚未比较或读取详情。"
    else:
        status = "searching"
        reason = "已建立任务，尚未完成检索协议。"

    return InterfacePromptClientJudgment(
        client=client,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        task_id=task_id,
        selected_interface_id=selected_id,
        selected_method=None if selected is None or not selected.method else selected.method,
        selected_path=None if selected is None or not selected.path else selected.path,
        selected_title=None if selected is None or not selected.title else selected.title,
        in_candidates=None if selected_id is None else selected_id in candidates,
        compared=bool(compared_ids) or any(name == COMPARE_TOOL for name in tool_calls),
        compared_interface_ids=compared_ids,
        detailed_interface_ids=detailed_ids,
        tool_calls=tool_calls,
        prohibited_tool_calls=prohibited,
        reason=reason,
    )


def _calls_for_prompt(calls: list[McpToolCallRecord], prompt: str) -> list[McpToolCallRecord]:
    ordered = sorted(calls, key=lambda item: item.id)
    digest = prompt_query_sha256(prompt) if prompt.strip() else ""
    if not digest:
        return ordered
    start: int | None = None
    for index, call in enumerate(ordered):
        if call.tool_name != SEARCH_TOOL or call.status == "cancelled":
            continue
        summary = call.request_summary or {}
        if summary.get("query_sha256") == digest:
            start = index
    if start is None:
        return ordered
    end = len(ordered)
    for index in range(start + 1, len(ordered)):
        if ordered[index].tool_name == SEARCH_TOOL and ordered[index].status != "cancelled":
            end = index
            break
    return ordered[start:end]


def _selected_identity(
    selected_id: str | None,
    candidates: dict[str, InterfacePromptMatchCandidate],
    lookup: InterfaceIdentityLookup | None,
) -> InterfacePromptIdentity | None:
    if not selected_id:
        return None
    candidate = candidates.get(selected_id)
    if candidate is not None:
        return InterfacePromptIdentity(
            interface_id=candidate.interface_id,
            method=candidate.method,
            path=candidate.path,
            title=candidate.title,
        )
    if lookup is None:
        return None
    return lookup(selected_id)


def _ids_from_calls(calls: list[McpToolCallRecord], tool_name: str, key: str) -> list[str]:
    found: list[str] = []
    for call in calls:
        if call.tool_name != tool_name or call.status == "cancelled":
            continue
        summary = call.request_summary or {}
        raw = summary.get(key)
        if isinstance(raw, str) and raw:
            found.append(raw)
        elif isinstance(raw, list):
            found.extend(item for item in raw if isinstance(item, str) and item)
    return found
