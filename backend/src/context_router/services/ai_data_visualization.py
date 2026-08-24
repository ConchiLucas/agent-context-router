from __future__ import annotations

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
    ) -> None:
        self._records = records
        self._workspaces = workspaces
        self._environments = environments
        self._relations = relations

    def create(self, payload: AiDataQueryWrite) -> AiDataQueryRecord:
        workspace = self._workspace(payload.workspace_id)
        if not self._environments.has_environment(payload.workspace_id, payload.environment):
            raise AiDataVisualizationError("工作空间没有配置所选环境", code="environment_not_found")
        generation = self._relations.get_generation(
            workspace_id=payload.workspace_id,
            status="published",
        )
        if generation is None:
            raise AiDataVisualizationError(
                "工作空间没有已发布的表关联", code="relation_snapshot_not_found"
            )
        table = self._relations.get_table(
            generation_id=generation.id,
            database_key=payload.database_key.strip(),
            schema_name=payload.schema_name.strip(),
            table_name=payload.table_name.strip(),
        )
        if table is None or table.relation_count < 1:
            raise AiDataVisualizationError(
                "查询表不在已发布的关联数据清单中", code="relation_table_not_found"
            )
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
            created_at=datetime.now(UTC),
        )
        try:
            saved = self._records.create(record)
        except AiDataQueryRepositoryError as exc:
            raise AiDataVisualizationError(str(exc)) from exc
        return self._view(saved, workspace.name)

    def latest(self) -> AiDataQueryLatest:
        try:
            record = self._records.latest()
        except AiDataQueryRepositoryError as exc:
            raise AiDataVisualizationError(str(exc)) from exc
        return AiDataQueryLatest(record=self._view_record(record) if record else None)

    def history(self, *, limit: int) -> AiDataQueryHistory:
        try:
            records = self._records.history(limit=limit)
        except AiDataQueryRepositoryError as exc:
            raise AiDataVisualizationError(str(exc)) from exc
        return AiDataQueryHistory(items=[self._view_record(record) for record in records])

    def _view_record(self, record: AiDataQueryRecordData) -> AiDataQueryRecord:
        workspace = self._workspace(record.workspace_id)
        return self._view(record, workspace.name)

    def _workspace(self, workspace_id: str) -> WorkspaceRecord:
        try:
            return self._workspaces.get_workspace(workspace_id)
        except WorkspaceRepositoryError as exc:
            raise AiDataVisualizationError("工作空间不存在", code="workspace_not_found") from exc

    @staticmethod
    def _view(record: AiDataQueryRecordData, workspace_name: str) -> AiDataQueryRecord:
        return AiDataQueryRecord(
            **asdict(record),
            workspace_name=workspace_name,
        )
