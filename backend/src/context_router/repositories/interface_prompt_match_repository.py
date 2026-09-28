from __future__ import annotations

import hashlib
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb


class InterfacePromptMatchRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class InterfacePromptMatchRecord:
    id: str
    workspace_id: str
    environment_key: str
    prompt: str
    verdict: str
    first_interface_id: str | None
    candidates: list[dict[str, object]]
    remaining_count: int
    search_id: str
    reason: str
    differing_dimensions: list[str]
    expected_interface_id: str | None
    expected_method: str
    expected_path: str
    expected_title: str
    note: str
    created_at: datetime
    client_results: list[dict[str, object]]


class InterfacePromptMatchStore(Protocol):
    def list_for_workspace(
        self,
        workspace_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        prioritized_prompt_digests: Collection[str] = (),
        prioritized_prompts: Collection[str] = (),
        prioritized_client: str | None = None,
    ) -> list[InterfacePromptMatchRecord]: ...

    def count_for_workspace(self, workspace_id: str) -> int: ...

    def count_client_results(self, workspace_id: str, client: str) -> int: ...

    def insert(self, record: InterfacePromptMatchRecord) -> InterfacePromptMatchRecord: ...

    def delete_for_workspace(self, workspace_id: str) -> int: ...

    def import_client_results(
        self, workspace_id: str, records: list[dict[str, object]]
    ) -> int: ...

    def delete_client_results(
        self, workspace_id: str, client: str, expected_count: int
    ) -> int: ...


def new_prompt_match_id() -> str:
    return uuid4().hex


class InMemoryInterfacePromptMatchRepository:
    def __init__(self) -> None:
        self._items: dict[str, InterfacePromptMatchRecord] = {}

    def list_for_workspace(
        self,
        workspace_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        prioritized_prompt_digests: Collection[str] = (),
        prioritized_prompts: Collection[str] = (),
        prioritized_client: str | None = None,
    ) -> list[InterfacePromptMatchRecord]:
        items = [item for item in self._items.values() if item.workspace_id == workspace_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        digests = set(prioritized_prompt_digests)
        prompts = {item.strip() for item in prioritized_prompts}
        if digests or prompts or prioritized_client:
            items.sort(
                key=lambda item: (
                    0
                    if _prompt_digest(item.prompt) in digests
                    or item.prompt.strip() in prompts
                    or any(
                        result.get("client") == prioritized_client
                        for result in item.client_results
                    )
                    else 1
                )
            )
        start = max(offset, 0)
        return items[start : start + max(limit, 0)]

    def count_for_workspace(self, workspace_id: str) -> int:
        return sum(1 for item in self._items.values() if item.workspace_id == workspace_id)

    def count_client_results(self, workspace_id: str, client: str) -> int:
        return sum(
            1
            for item in self._items.values()
            if item.workspace_id == workspace_id
            for result in item.client_results
            if result.get("client") == client
        )

    def insert(self, record: InterfacePromptMatchRecord) -> InterfacePromptMatchRecord:
        self._items[record.id] = record
        return record

    def delete_for_workspace(self, workspace_id: str) -> int:
        keep = {
            item_id: item
            for item_id, item in self._items.items()
            if item.workspace_id != workspace_id
        }
        deleted = len(self._items) - len(keep)
        self._items = keep
        return deleted

    def import_client_results(
        self, workspace_id: str, records: list[dict[str, object]]
    ) -> int:
        imported = 0
        for result in records:
            record_id = str(result["record_id"])
            existing = self._items.get(record_id)
            if existing is None or existing.workspace_id != workspace_id:
                raise InterfacePromptMatchRepositoryError(f"接口测试记录不存在：{record_id}")
            client = str(result["client"])
            client_results = [
                item for item in existing.client_results if item.get("client") != client
            ]
            stored = dict(result.get("payload", {}))
            stored.update(
                {
                    key: result[key]
                    for key in (
                        "client", "task_id", "batch_id", "model",
                        "reasoning_effort", "source_file",
                    )
                }
            )
            client_results.append(stored)
            from dataclasses import replace

            self._items[record_id] = replace(existing, client_results=client_results)
            imported += 1
        return imported

    def delete_client_results(
        self, workspace_id: str, client: str, expected_count: int
    ) -> int:
        actual = self.count_client_results(workspace_id, client)
        if actual != expected_count:
            raise ValueError("客户端持久化结果已变化，请重新核对后再删除")
        for record_id, existing in list(self._items.items()):
            if existing.workspace_id != workspace_id:
                continue
            filtered = [item for item in existing.client_results if item.get("client") != client]
            if len(filtered) != len(existing.client_results):
                from dataclasses import replace

                self._items[record_id] = replace(existing, client_results=filtered)
        return actual


class PostgresInterfacePromptMatchRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def list_for_workspace(
        self,
        workspace_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        prioritized_prompt_digests: Collection[str] = (),
        prioritized_prompts: Collection[str] = (),
        prioritized_client: str | None = None,
    ) -> list[InterfacePromptMatchRecord]:
        digests = list(dict.fromkeys(prioritized_prompt_digests))
        prompts = list(dict.fromkeys(item.strip() for item in prioritized_prompts))
        priority_order = ""
        parameters: tuple[object, ...]
        if digests or prompts or prioritized_client:
            priority_order = """
                        CASE WHEN
                            encode(sha256(convert_to(btrim(prompt), 'UTF8')), 'hex') = ANY(%s)
                            OR btrim(prompt) = ANY(%s)
                            OR EXISTS (
                                SELECT 1 FROM interface_prompt_client_results AS result
                                 WHERE result.prompt_match_id = interface_prompt_matches.id
                                   AND result.client = %s
                            )
                        THEN 0 ELSE 1 END,
            """
            parameters = (
                workspace_id,
                digests,
                prompts,
                prioritized_client or "",
                max(limit, 0),
                max(offset, 0),
            )
        else:
            parameters = (workspace_id, max(limit, 0), max(offset, 0))
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                rows = connection.execute(
                    f"""SELECT id, workspace_id, environment_key, prompt, verdict,
                              first_interface_id, candidates, remaining_count,
                              search_id, reason, differing_dimensions,
                              expected_interface_id, expected_method, expected_path,
                              expected_title, note, created_at,
                              COALESCE((
                                  SELECT jsonb_agg(
                                      result.payload || jsonb_build_object(
                                          'client', result.client,
                                          'task_id', result.task_id,
                                          'batch_id', result.batch_id,
                                          'model', result.model,
                                          'reasoning_effort', result.reasoning_effort,
                                          'source_file', result.source_file
                                      )
                                  )
                                    FROM interface_prompt_client_results AS result
                                   WHERE result.prompt_match_id = interface_prompt_matches.id
                              ), '[]'::jsonb)
                         FROM interface_prompt_matches
                        WHERE workspace_id = %s
                        ORDER BY {priority_order} created_at DESC
                        LIMIT %s OFFSET %s""",
                    parameters,
                ).fetchall()
        except psycopg.Error as exc:
            raise InterfacePromptMatchRepositoryError("读取提示词匹配失败") from exc
        return [self._row(row) for row in rows]

    def count_for_workspace(self, workspace_id: str) -> int:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    "SELECT count(*) FROM interface_prompt_matches WHERE workspace_id = %s",
                    (workspace_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise InterfacePromptMatchRepositoryError("读取提示词匹配失败") from exc
        return int(row[0]) if row else 0

    def count_client_results(self, workspace_id: str, client: str) -> int:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """SELECT count(*)
                         FROM interface_prompt_client_results AS result
                         JOIN interface_prompt_matches AS prompt_match
                           ON prompt_match.id = result.prompt_match_id
                        WHERE prompt_match.workspace_id = %s AND result.client = %s""",
                    (workspace_id, client),
                ).fetchone()
        except psycopg.Error as exc:
            raise InterfacePromptMatchRepositoryError("读取客户端测试结果失败") from exc
        return int(row[0]) if row else 0

    def insert(self, record: InterfacePromptMatchRecord) -> InterfacePromptMatchRecord:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                connection.execute(
                    """INSERT INTO interface_prompt_matches (
                           id, workspace_id, environment_key, prompt, verdict,
                           first_interface_id, candidates, remaining_count,
                           search_id, reason, differing_dimensions,
                           expected_interface_id, expected_method, expected_path,
                           expected_title, note, created_at
                       ) VALUES (
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        record.id,
                        record.workspace_id,
                        record.environment_key,
                        record.prompt,
                        record.verdict,
                        record.first_interface_id,
                        Jsonb(record.candidates),
                        record.remaining_count,
                        record.search_id,
                        record.reason,
                        Jsonb(list(record.differing_dimensions)),
                        record.expected_interface_id,
                        record.expected_method,
                        record.expected_path,
                        record.expected_title,
                        record.note,
                        record.created_at,
                    ),
                )
        except psycopg.Error as exc:
            raise InterfacePromptMatchRepositoryError("保存提示词匹配失败") from exc
        return record

    def delete_for_workspace(self, workspace_id: str) -> int:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    "DELETE FROM interface_prompt_matches WHERE workspace_id = %s",
                    (workspace_id,),
                )
                return int(row.rowcount or 0)
        except psycopg.Error as exc:
            raise InterfacePromptMatchRepositoryError("删除提示词匹配失败") from exc

    def import_client_results(
        self, workspace_id: str, records: list[dict[str, object]]
    ) -> int:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                imported = 0
                for result in records:
                    row = connection.execute(
                        """INSERT INTO interface_prompt_client_results (
                               prompt_match_id, client, task_id, batch_id, model,
                               reasoning_effort, source_file, payload, imported_at
                           )
                           SELECT prompt_match.id, %s, %s, %s, %s, %s, %s, %s, now()
                             FROM interface_prompt_matches AS prompt_match
                            WHERE prompt_match.id = %s AND prompt_match.workspace_id = %s
                           ON CONFLICT (prompt_match_id, client) DO UPDATE SET
                               task_id = EXCLUDED.task_id,
                               batch_id = EXCLUDED.batch_id,
                               model = EXCLUDED.model,
                               reasoning_effort = EXCLUDED.reasoning_effort,
                               source_file = EXCLUDED.source_file,
                               payload = EXCLUDED.payload,
                               imported_at = now()
                           RETURNING prompt_match_id""",
                        (
                            result["client"], result["task_id"], result["batch_id"],
                            result.get("model", ""), result.get("reasoning_effort", ""),
                            result["source_file"], Jsonb(result["payload"]),
                            result["record_id"], workspace_id,
                        ),
                    ).fetchone()
                    if row is None:
                        raise InterfacePromptMatchRepositoryError(
                            f"接口测试记录不存在：{result['record_id']}"
                        )
                    imported += 1
                return imported
        except InterfacePromptMatchRepositoryError:
            raise
        except psycopg.Error as exc:
            raise InterfacePromptMatchRepositoryError("导入客户端测试结果失败") from exc

    def delete_client_results(
        self, workspace_id: str, client: str, expected_count: int
    ) -> int:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """SELECT count(*)
                         FROM interface_prompt_client_results AS result
                         JOIN interface_prompt_matches AS prompt_match
                           ON prompt_match.id = result.prompt_match_id
                        WHERE prompt_match.workspace_id = %s AND result.client = %s""",
                    (workspace_id, client),
                ).fetchone()
                actual = int(row[0]) if row else 0
                if actual != expected_count:
                    raise ValueError("客户端持久化结果已变化，请重新核对后再删除")
                deleted = connection.execute(
                    """DELETE FROM interface_prompt_client_results AS result
                         USING interface_prompt_matches AS prompt_match
                         WHERE prompt_match.id = result.prompt_match_id
                           AND prompt_match.workspace_id = %s
                           AND result.client = %s""",
                    (workspace_id, client),
                )
                return int(deleted.rowcount or 0)
        except ValueError:
            raise
        except psycopg.Error as exc:
            raise InterfacePromptMatchRepositoryError("删除客户端持久化结果失败") from exc

    def _require_database_url(self) -> str:
        if not self._database_url:
            raise InterfacePromptMatchRepositoryError("控制面数据库未配置")
        return self._database_url

    @staticmethod
    def _row(row: tuple[object, ...]) -> InterfacePromptMatchRecord:
        candidates = row[6] if isinstance(row[6], list) else []
        dimensions = row[10] if isinstance(row[10], list) else []
        return InterfacePromptMatchRecord(
            id=str(row[0]),
            workspace_id=str(row[1]),
            environment_key=str(row[2]),
            prompt=str(row[3]),
            verdict=str(row[4]),
            first_interface_id=None if row[5] is None else str(row[5]),
            candidates=[item for item in candidates if isinstance(item, dict)],
            remaining_count=int(row[7]),
            search_id=str(row[8]),
            reason=str(row[9]),
            differing_dimensions=[str(item) for item in dimensions],
            expected_interface_id=None if row[11] is None else str(row[11]),
            expected_method=str(row[12] or ""),
            expected_path=str(row[13] or ""),
            expected_title=str(row[14] or ""),
            note=str(row[15] or ""),
            created_at=row[16],  # type: ignore[arg-type]
            client_results=[item for item in row[17] if isinstance(item, dict)]
            if isinstance(row[17], list)
            else [],
        )


def new_prompt_match_record(
    *,
    workspace_id: str,
    environment_key: str,
    prompt: str,
    verdict: str,
    first_interface_id: str | None,
    candidates: list[dict[str, object]],
    remaining_count: int,
    search_id: str,
    reason: str,
    differing_dimensions: list[str],
    expected_interface_id: str | None = None,
    expected_method: str = "",
    expected_path: str = "",
    expected_title: str = "",
    note: str = "",
) -> InterfacePromptMatchRecord:
    return InterfacePromptMatchRecord(
        id=new_prompt_match_id(),
        workspace_id=workspace_id,
        environment_key=environment_key,
        prompt=prompt,
        verdict=verdict,
        first_interface_id=first_interface_id,
        candidates=candidates,
        remaining_count=remaining_count,
        search_id=search_id,
        reason=reason,
        differing_dimensions=differing_dimensions,
        expected_interface_id=expected_interface_id,
        expected_method=expected_method,
        expected_path=expected_path,
        expected_title=expected_title,
        note=note,
        created_at=datetime.now(UTC),
        client_results=[],
    )


def _prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()
