"""Task-scoped agent projection of the stored table relations.

The REST layer serves the page and is addressed by workspace id; an agent holds
a task id instead, and the task already binds both the workspace and the
database environment. Resolving them here is what keeps the MCP tools from ever
answering for a different environment than the one ``prepare_task_context``
selected.

The returned rows are deliberately narrower than the page models. An agent gets
structured child/parent endpoints, one settled ``cardinality`` and an
``uncertain`` flag when the code and data readings differ. Evidence is opt-in:
``none`` returns no evidence, ``uncertain`` expands only soft verdicts, and
``all`` expands every relation.

Insert and update entry points are grouped by the file they live in and carry
method names only: several methods of one service persist the same table, and a
path repeated once per method was the largest thing in the payload. Paths stay
workspace-relative with the root stated once. No line numbers and no snippets —
a file and method name survive most edits that move code, where a line number
goes on looking exact after it has stopped being right.

``read`` takes several table names at once because an agent task rarely stops
at one table: writing table A means looking at its parent B and its child C in
the same breath. Names that cannot be resolved fail as entries of the answer
rather than as the answer, the same contract document reads follow — one typo
must not cost the agent the two tables that were spelled right.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from context_router.repositories.table_relation_repository import TableRelationReader
from context_router.repositories.task_repository import (
    TaskRecord,
    TaskRepositoryError,
    TaskStore,
)
from context_router.schemas.table_relations import (
    TableRelationDetail,
    TableRelationEndpoint,
    TableRelationGenerationSummary,
    TableRelationTableSummary,
    TableRelationUpdateSite,
    TableRelationView,
    TableRelationWriteSite,
)
from context_router.services.project_registry import (
    ProjectRegistry,
    ProjectRegistryError,
    WorkspaceSnapshot,
)
from context_router.services.table_relation_query import (
    TableRelationNotFoundError,
    TableRelationQueryService,
)

TableRelationContextSection = Literal["relations", "writes", "updates"]
TableRelationEvidenceMode = Literal["none", "uncertain", "all"]

_ALL_SECTIONS: tuple[TableRelationContextSection, ...] = (
    "relations",
    "writes",
    "updates",
)

_CARDINALITY_LABELS = {
    "one_to_one": "1:1",
    "one_to_many": "1:N",
    "many_to_one": "N:1",
    "unknown": "unknown",
}

# How the inspected table sits in a relation, said in the words an agent uses.
# The page's outbound/inbound is stated from the viewer; child/parent is stated
# from the schema and needs no viewer to make sense of.
_ROLE_BY_DIRECTION = {
    "outbound": "child",
    "inbound": "parent",
    "self": "self",
}

# How many close names to offer back when a lookup misses. Enough to catch a
# typo or a prefix guess, few enough that the error stays one line per name.
_CANDIDATE_LIMIT = 5


class TableRelationContextError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "table_relation_context_failed",
    ) -> None:
        super().__init__(message)
        self.code = code


class TableRelationContextService:
    def __init__(
        self,
        *,
        registry: ProjectRegistry,
        task_repository: TaskStore,
        reader: TableRelationReader,
    ) -> None:
        self._registry = registry
        self._task_repository = task_repository
        self._query = TableRelationQueryService(reader=reader)

    def read(
        self,
        *,
        task_id: int,
        tables: list[str],
        sections: list[str] | None = None,
        database: str | None = None,
        evidence: TableRelationEvidenceMode = "none",
    ) -> dict[str, object]:
        if evidence not in {"none", "uncertain", "all"}:
            raise TableRelationContextError(
                "evidence 只能是 none、uncertain 或 all",
                code="invalid_relation_evidence",
            )
        normalized_sections = self._normalize_sections(sections)
        requested = self._normalize_tables(tables)
        task = self._task(task_id)
        workspace = self._workspace(task)
        generation = self._generation(workspace.id)
        return {
            "environment": generation.environment,
            "generation": {
                "revision": generation.revision,
                "generated_at": (
                    generation.published_at.isoformat() if generation.published_at else None
                ),
            },
            "workspace_root": workspace.root_path,
            "tables": [
                self._table_entry(
                    workspace=workspace,
                    requested_table=name,
                    database=database,
                    sections=normalized_sections,
                    evidence=evidence,
                )
                for name in requested
            ],
        }

    def read_for_workspace(
        self,
        *,
        workspace_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
        mode: Literal["default", "full"] = "default",
    ) -> dict[str, object]:
        """The MCP ``read_table_relations`` payload for one known table identity.

        The page already knows which table was selected, so this path skips name
        resolution and returns the same projection an agent would receive, wrapped
        with the tool name and example arguments for inspection.
        """
        try:
            workspace = self._registry.get_workspace_snapshot(workspace_id)
        except ProjectRegistryError as exc:
            raise TableRelationContextError(
                "工作空间不存在",
                code="workspace_not_found",
            ) from exc
        generation = self._generation(workspace_id)
        sections = _ALL_SECTIONS if mode == "full" else ("relations",)
        evidence: TableRelationEvidenceMode = "all" if mode == "full" else "none"
        entry = self._table_entry_with_identity(
            workspace=workspace,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
            sections=sections,
            evidence=evidence,
        )
        if "error" in entry:
            error = entry["error"]
            assert isinstance(error, dict)
            raise TableRelationContextError(
                str(error.get("message", "表关联读取失败")),
                code=str(error.get("code", "table_relation_context_failed")),
            )
        result = {
            "environment": generation.environment,
            "generation": {
                "revision": generation.revision,
                "generated_at": (
                    generation.published_at.isoformat() if generation.published_at else None
                ),
            },
            "workspace_root": workspace.root_path,
            "tables": [entry],
        }
        arguments: dict[str, object] = {
            "task_id": "<from prepare_task_context>",
            "tables": [table_name],
            "database": database_key,
        }
        if mode == "full":
            arguments["sections"] = list(_ALL_SECTIONS)
            arguments["evidence"] = "all"
        return {
            "tool": "read_table_relations",
            "arguments": arguments,
            "result": result,
        }

    def search(
        self,
        *,
        task_id: int,
        query: str | None = None,
        database: str | None = None,
        only_related: bool = True,
        limit: int = 50,
    ) -> dict[str, object]:
        task = self._task(task_id)
        workspace = self._workspace(task)
        listing = self._query.list_tables(
            workspace.id,
            database_key=database,
            only_related=only_related,
            search=query.strip() if query else None,
            limit=limit + 1,
        )
        if listing.generation is None:
            raise TableRelationContextError(
                "这个工作空间还没有已发布的表关联数据",
                code="table_relation_generation_missing",
            )
        tables = listing.tables[:limit]
        return {
            "environment": listing.generation.environment,
            "generated_at": (
                listing.generation.published_at.isoformat()
                if listing.generation.published_at
                else None
            ),
            "truncated": len(listing.tables) > limit,
            "tables": [
                {
                    "database": item.database_key,
                    "schema": item.schema_name,
                    "name": item.table_name,
                    "relation_count": item.relation_count,
                }
                for item in tables
            ],
        }

    def _table_entry(
        self,
        *,
        workspace: WorkspaceSnapshot,
        requested_table: str,
        database: str | None,
        sections: tuple[TableRelationContextSection, ...],
        evidence: TableRelationEvidenceMode,
    ) -> dict[str, object]:
        try:
            identity = self._resolve_table(
                workspace_id=workspace.id,
                table=requested_table,
                database=database,
            )
        except TableRelationContextError as exc:
            if exc.code == "table_relation_generation_missing":
                raise
            return {
                "table_request": requested_table,
                "error": {"code": exc.code, "message": str(exc)},
            }
        return self._table_entry_with_identity(
            workspace=workspace,
            database_key=identity.database_key,
            schema_name=identity.schema_name,
            table_name=identity.table_name,
            sections=sections,
            evidence=evidence,
        )

    def _table_entry_with_identity(
        self,
        *,
        workspace: WorkspaceSnapshot,
        database_key: str,
        schema_name: str,
        table_name: str,
        sections: tuple[TableRelationContextSection, ...],
        evidence: TableRelationEvidenceMode,
    ) -> dict[str, object]:
        identity = TableRelationTableSummary(
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
        )
        entry: dict[str, object] = {
            "table": {
                "database": identity.database_key,
                "schema": identity.schema_name,
                "name": identity.table_name,
            },
        }
        common = {
            "database_key": identity.database_key,
            "schema_name": identity.schema_name,
            "table_name": identity.table_name,
        }
        try:
            if "relations" in sections:
                detail = self._query.get_table_detail(workspace.id, **common)
                entry["relations"] = [
                    self._relation_row(
                        view,
                        workspace=workspace,
                        identity=identity,
                        evidence=evidence,
                    )
                    for view in detail.relations
                ]
                if detail.hidden_count > 0:
                    entry["warnings"] = [
                        {
                            "code": "unresolved_relations",
                            "count": detail.hidden_count,
                        }
                    ]
            if "writes" in sections:
                writes = self._query.get_table_writes(workspace.id, **common)
                entry["writes"] = _entry_groups(writes.writes)
            if "updates" in sections:
                updates = self._query.get_table_updates(workspace.id, **common)
                entry["updates"] = _entry_groups(updates.updates)
        except TableRelationNotFoundError as exc:
            return {
                "table_request": table_name,
                "error": {"code": exc.code, "message": str(exc)},
            }
        return entry

    def _relation_row(
        self,
        view: TableRelationView,
        *,
        workspace: WorkspaceSnapshot,
        identity: TableRelationTableSummary,
        evidence: TableRelationEvidenceMode,
    ) -> dict[str, object]:
        row = _relation_view_row(view)
        if evidence == "none" or (evidence == "uncertain" and "uncertain" not in row):
            return row
        detail = self._query.get_relation_detail(
            workspace.id,
            database_key=identity.database_key,
            schema_name=identity.schema_name,
            table_name=identity.table_name,
            edge_id=view.edge_id,
        )
        row["evidence"] = _evidence(detail)
        return row

    @staticmethod
    def _normalize_sections(
        sections: list[str] | None,
    ) -> tuple[TableRelationContextSection, ...]:
        if sections is None:
            return ("relations",)
        normalized = tuple(dict.fromkeys(sections))
        if not normalized or any(section not in _ALL_SECTIONS for section in normalized):
            raise TableRelationContextError(
                "sections 只能包含 relations、writes 或 updates",
                code="invalid_relation_section",
            )
        return normalized  # type: ignore[return-value]

    @staticmethod
    def _normalize_tables(tables: list[str]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(name.strip() for name in tables if name.strip()))
        if not normalized:
            raise TableRelationContextError(
                "tables 至少要有一个非空表名",
                code="invalid_relation_tables",
            )
        return normalized

    def _task(self, task_id: int) -> TaskRecord:
        try:
            return self._task_repository.get_task(task_id)
        except TaskRepositoryError as exc:
            raise TableRelationContextError(
                "任务不存在，请重新 prepare",
                code="task_not_found",
            ) from exc

    def _workspace(self, task: TaskRecord) -> WorkspaceSnapshot:
        if task.scope != "workspace":
            raise TableRelationContextError(
                "当前任务不在工作空间内，表关联上下文不可用",
                code="workspace_task_required",
            )
        try:
            return self._registry.get_workspace_snapshot_for_task(
                workspace_id=task.workspace_id,
                workspace_key=task.workspace_key,
            )
        except ProjectRegistryError as exc:
            raise TableRelationContextError(
                "任务绑定的工作空间当前不可用，请重新 prepare",
                code="workspace_unavailable",
            ) from exc

    def _generation(
        self,
        workspace_id: str,
    ) -> TableRelationGenerationSummary:
        status = self._query.get_status(workspace_id)
        if status.generation is None:
            raise TableRelationContextError(
                "这个工作空间还没有已发布的表关联数据",
                code="table_relation_generation_missing",
            )
        return status.generation

    def _resolve_table(
        self,
        *,
        workspace_id: str,
        table: str,
        database: str | None,
    ) -> TableRelationTableSummary:
        wanted = table.strip()
        listing = self._query.list_tables(
            workspace_id,
            database_key=database,
            only_related=False,
            search=wanted,
            limit=200,
        )
        if listing.generation is None:
            raise TableRelationContextError(
                "这个工作空间还没有已发布的表关联数据",
                code="table_relation_generation_missing",
            )
        exact = [item for item in listing.tables if item.table_name.casefold() == wanted.casefold()]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            names = "、".join(
                f"{item.database_key}.{item.table_name}" for item in exact[:_CANDIDATE_LIMIT]
            )
            raise TableRelationContextError(
                f"同名表出现在多个库，请补充 database 参数：{names}",
                code="table_relation_table_ambiguous",
            )
        close = "、".join(
            f"{item.database_key}.{item.table_name}" for item in listing.tables[:_CANDIDATE_LIMIT]
        )
        message = "表关联数据里没有这张表"
        if close:
            message = f"{message}；名称相近的表：{close}"
        raise TableRelationContextError(message, code="table_relation_table_not_found")


def _relation_view_row(view: TableRelationView) -> dict[str, object]:
    code = _CARDINALITY_LABELS[view.code_cardinality]
    db = _CARDINALITY_LABELS[view.db_cardinality]
    # One verdict reaches the agent, because the choice between 1:N and 1:1 is
    # rarely what an insert or an update turns on. The code reading leads: it
    # states what the write paths permit, which is the question a caller is about
    # to face, where the data reading only reports what one snapshot contained.
    row: dict[str, object] = {
        "child": _endpoint_reference(view.child),
        "parent": _endpoint_reference(view.parent),
        "role": _ROLE_BY_DIRECTION[view.direction],
        "cardinality": code if view.code_cardinality != "unknown" else db,
    }
    if code != db or view.code_cardinality == "unknown":
        # Why the two readings differ is a data-quality question. Answering it
        # inline would charge every row for evidence keys that almost no row acts
        # on, so the flag says only that the verdict is soft; evidence=uncertain
        # or evidence=all carries the breakdown for whoever wants it.
        row["uncertain"] = True
    return row


def _endpoint_reference(endpoint: TableRelationEndpoint) -> str:
    parts = [endpoint.database_key, endpoint.schema_name, endpoint.table_name]
    if endpoint.column_name:
        parts.append(endpoint.column_name)
    return ".".join(str(part) for part in parts)


def _evidence(detail: TableRelationDetail) -> dict[str, object]:
    """The re-checkable part of one relation's verdicts.

    The SQL is served so the agent can rerun each check through
    ``execute_database_query`` against today's data instead of trusting the
    snapshot; the measurement is served so a rerun has stored numbers to
    contradict. This is also where the two per-dimension verdicts live, since the
    row above states one settled reading and this is the request for the rest.

    ``file`` is workspace-relative like everywhere else in this payload; join it
    onto the ``workspace_root`` stated once at the top.
    """
    measurement = detail.measurement
    relation = detail.relation
    return {
        "code_cardinality": _CARDINALITY_LABELS[relation.code_cardinality],
        "code_evidence": relation.code_evidence,
        "db_cardinality": _CARDINALITY_LABELS[relation.db_cardinality],
        "db_evidence": relation.db_evidence,
        "measurement": {
            "child_table_rows": measurement.child_table_rows,
            "child_rows_with_value": measurement.child_rows_with_value,
            "child_distinct_keys": measurement.child_distinct_keys,
            "parent_rows_with_value": measurement.parent_rows_with_value,
            "parent_distinct_keys": measurement.parent_distinct_keys,
            "orphan_keys": measurement.orphan_keys,
        },
        "checks": [
            {"key": check.key, "outcome": check.outcome, "sql": check.sql}
            for check in detail.checks
        ],
        "code_sites": [
            {
                "method": site.method_name,
                "kind": site.kind,
                "implies": _CARDINALITY_LABELS[site.implies],
                "file": site.file_path,
            }
            for site in detail.code_sites
        ],
    }


def _entry_groups(
    sites: Sequence[TableRelationWriteSite | TableRelationUpdateSite],
) -> list[dict[str, object]]:
    """Entry points folded onto the file they live in.

    Several methods of one service persist the same table, and repeating that
    service's path once per method was the largest single thing in this payload.
    The file is the artifact an agent opens and the stable grouping key, which
    makes it the natural place to hang the method list.

    Paths stay workspace-relative and the root is stated once per response. An
    absolute path per method was the same string prefix copied a dozen times.
    """
    grouped: dict[str, list[dict[str, str]]] = {}
    for site in sites:
        grouped.setdefault(site.file_path, []).append({"name": site.method_name, "kind": site.kind})
    return [
        {
            "file": file_path,
            "methods": methods,
        }
        for file_path, methods in grouped.items()
    ]
