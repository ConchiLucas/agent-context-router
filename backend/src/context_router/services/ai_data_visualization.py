from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from context_router.repositories.ai_data_query_repository import (
    AiDataQueryRecordData,
    AiDataQueryRepositoryError,
    AiDataQueryStore,
)
from context_router.repositories.database_environment_repository import DatabaseEnvironmentStore
from context_router.repositories.table_relation_repository import TableRelationReader
from context_router.repositories.task_repository import TaskRepositoryError, TaskStore
from context_router.repositories.workspace_repository import (
    WorkspaceRecord,
    WorkspaceRepositoryError,
    WorkspaceStore,
)
from context_router.schemas.ai_data_visualization import (
    AiDataQueryHistory,
    AiDataQueryLatest,
    AiDataQueryRecord,
    AiDataQueryWrite,
)
from context_router.services.mcp_trace import current_tool_call_id


class AiDataVisualizationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "ai_data_visualization_failed") -> None:
        super().__init__(message)
        self.code = code


class AiDataVisualizationService:
    def __init__(
        self,
        *,
        records: AiDataQueryStore,
        workspaces: WorkspaceStore,
        environments: DatabaseEnvironmentStore,
        relations: TableRelationReader,
        tasks: TaskStore | None = None,
    ) -> None:
        self._records = records
        self._workspaces = workspaces
        self._environments = environments
        self._relations = relations
        self._tasks = tasks

    def create(self, payload: AiDataQueryWrite) -> AiDataQueryRecord:
        workspace = self._workspace(payload.workspace_id)
        task = self._task(payload.task_id) if payload.task_id is not None else None
        if task is not None:
            if task.workspace_id != payload.workspace_id:
                raise AiDataVisualizationError(
                    "任务不属于所选工作空间",
                    code="task_workspace_mismatch",
                )
            task_environment = task.database_environment or "local"
            if task_environment != payload.environment:
                raise AiDataVisualizationError(
                    "查询环境与任务环境不一致",
                    code="task_environment_mismatch",
                )
        self._validate_target(payload)
        now = datetime.now(UTC)
        idempotency_key = self._idempotency_key(payload)
        record = AiDataQueryRecordData(
            id=str(uuid4()),
            workspace_id=payload.workspace_id,
            source=payload.source.strip(),
            description=payload.description.strip(),
            environment=payload.environment.strip(),
            database_key=payload.database_key.strip(),
            schema_name=payload.schema_name.strip(),
            table_name=payload.table_name.strip(),
            keyword=payload.keyword.strip(),
            created_at=now,
            task_id=payload.task_id,
            tool_call_id=current_tool_call_id(),
            idempotency_key=idempotency_key,
            updated_at=now,
        )
        try:
            saved = self._records.upsert(record)
        except AiDataQueryRepositoryError as exc:
            raise AiDataVisualizationError(str(exc)) from exc
        return self._view(saved, workspace.name)

    def create_for_task(
        self,
        *,
        task_id: int,
        description: str,
        database_key: str,
        schema_name: str,
        table_name: str,
        keyword: str,
    ) -> AiDataQueryRecord:
        task = self._task(task_id)
        if task.workspace_id is None:
            raise AiDataVisualizationError(
                "任务没有关联工作空间",
                code="task_workspace_mismatch",
            )
        return self.create(
            AiDataQueryWrite(
                source=_source_key(task.agent_name),
                description=description or task.task,
                workspace_id=task.workspace_id,
                environment=task.database_environment or "local",
                database_key=database_key,
                schema_name=schema_name,
                table_name=table_name,
                keyword=keyword,
                task_id=task_id,
            )
        )

    def latest(
        self,
        *,
        workspace_id: str | None,
        environment: str | None,
        task_id: int | None = None,
    ) -> AiDataQueryLatest:
        if workspace_id is not None:
            self._workspace(workspace_id)
        try:
            record = self._records.latest(
                workspace_id=workspace_id,
                environment=environment,
                task_id=task_id,
            )
        except AiDataQueryRepositoryError as exc:
            raise AiDataVisualizationError(str(exc)) from exc
        return AiDataQueryLatest(record=self._view_record(record) if record else None)

    def history(
        self,
        *,
        workspace_id: str | None,
        environment: str | None,
        source: str | None,
        task_id: int | None = None,
        limit: int,
    ) -> AiDataQueryHistory:
        if workspace_id is not None:
            self._workspace(workspace_id)
        try:
            records = self._records.history(
                workspace_id=workspace_id,
                environment=environment,
                source=source,
                task_id=task_id,
                limit=limit,
            )
        except AiDataQueryRepositoryError as exc:
            raise AiDataVisualizationError(str(exc)) from exc
        return AiDataQueryHistory(items=[self._view_record(record) for record in records])

    def record_execution(
        self,
        *,
        record_id: str,
        workspace_id: str,
        environment: str,
        succeeded: bool,
        result_card_count: int | None,
        result_row_count: int | None,
        duration_ms: int,
        error_summary: str | None = None,
    ) -> None:
        try:
            current = self._records.get(record_id)
        except AiDataQueryRepositoryError as exc:
            raise AiDataVisualizationError(str(exc)) from exc
        if current is None:
            raise AiDataVisualizationError("AI 数据查询记录不存在", code="record_not_found")
        if current.workspace_id != workspace_id or current.environment != environment:
            raise AiDataVisualizationError(
                "执行摘要与查询记录的工作空间或环境不一致",
                code="record_scope_mismatch",
            )
        try:
            self._records.mark_execution(
                record_id=record_id,
                status="succeeded" if succeeded else "failed",
                executed_at=datetime.now(UTC),
                result_card_count=result_card_count,
                result_row_count=result_row_count,
                duration_ms=max(0, duration_ms),
                error_summary=(error_summary or "")[:1000] or None,
            )
        except AiDataQueryRepositoryError as exc:
            raise AiDataVisualizationError(str(exc)) from exc

    def _validate_target(self, payload: AiDataQueryWrite) -> None:
        if not self._environments.has_environment(payload.workspace_id, payload.environment):
            raise AiDataVisualizationError(
                "工作空间没有配置所选环境",
                code="environment_not_found",
            )
        generation = self._relations.get_generation(
            workspace_id=payload.workspace_id,
            status="published",
        )
        if generation is None:
            raise AiDataVisualizationError(
                "工作空间没有已发布的表关联",
                code="relation_snapshot_not_found",
            )
        table = self._relations.get_table(
            generation_id=generation.id,
            database_key=payload.database_key.strip(),
            schema_name=payload.schema_name.strip(),
            table_name=payload.table_name.strip(),
        )
        if table is None or table.relation_count < 1:
            raise AiDataVisualizationError(
                "查询表不在已发布的关联数据清单中",
                code="relation_table_not_found",
            )

    def _view_record(self, record: AiDataQueryRecordData) -> AiDataQueryRecord:
        workspace = self._workspace(record.workspace_id)
        return self._view(record, workspace.name)

    def _workspace(self, workspace_id: str) -> WorkspaceRecord:
        try:
            return self._workspaces.get_workspace(workspace_id)
        except WorkspaceRepositoryError as exc:
            raise AiDataVisualizationError("工作空间不存在", code="workspace_not_found") from exc

    def _task(self, task_id: int):
        if self._tasks is None:
            raise AiDataVisualizationError("任务数据库尚未配置", code="task_not_found")
        try:
            return self._tasks.get_task(task_id)
        except TaskRepositoryError as exc:
            raise AiDataVisualizationError("任务不存在", code="task_not_found") from exc

    @staticmethod
    def _idempotency_key(payload: AiDataQueryWrite) -> str:
        if payload.idempotency_key:
            raw = f"{payload.workspace_id}:{payload.idempotency_key}"
        elif payload.task_id is not None:
            raw = json.dumps(
                {
                    "task_id": payload.task_id,
                    "workspace_id": payload.workspace_id,
                    "environment": payload.environment,
                    "database_key": payload.database_key.strip(),
                    "schema_name": payload.schema_name.strip(),
                    "table_name": payload.table_name.strip(),
                    "keyword": payload.keyword.strip(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        else:
            raw = str(uuid4())
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _view(record: AiDataQueryRecordData, workspace_name: str) -> AiDataQueryRecord:
        values = asdict(record)
        values.pop("idempotency_key", None)
        values.pop("tool_call_id", None)
        values.pop("updated_at", None)
        return AiDataQueryRecord(
            **values,
            workspace_name=workspace_name,
        )


def _source_key(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", (value or "agent").strip().lower()).strip("-")
    if not normalized or not normalized[0].isalpha():
        return "agent"
    return normalized[:32]
