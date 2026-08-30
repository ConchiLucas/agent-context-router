from __future__ import annotations

from uuid import uuid4

from context_router.config import Settings
from context_router.repositories.data_source_repository import (
    DataSourceRepositoryError,
    DataSourceStore,
)
from context_router.repositories.database_environment_repository import (
    DatabaseEnvironmentRepositoryError,
    DatabaseEnvironmentStore,
)
from context_router.repositories.project_repository import ProjectStore
from context_router.repositories.workspace_repository import (
    WorkspaceRecord,
    WorkspaceRepositoryError,
    WorkspaceStore,
)
from context_router.schemas.data_sources import WorkspaceDataSourceSummary
from context_router.schemas.projects import DocumentDetail, DocumentTreeNode, ProjectSummary
from context_router.schemas.workspaces import (
    WorkspaceProjectSummary,
    WorkspaceSummary,
)
from context_router.services.local_workspace_mapping import (
    LocalWorkspaceMappingError,
    LocalWorkspaceMappingService,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError
from context_router.services.runtime_paths import RuntimePathError, RuntimePathResolver
from context_router.services.workspace_paths import (
    WorkspacePathError,
    normalize_workspace_root_path,
)


class WorkspaceManagementError(ValueError):
    pass


class WorkspaceManagementService:
    def __init__(
        self,
        *,
        settings: Settings,
        workspace_repository: WorkspaceStore,
        project_repository: ProjectStore,
        project_registry: ProjectRegistry,
        data_source_repository: DataSourceStore,
        database_environment_repository: DatabaseEnvironmentStore | None = None,
        local_mapping: LocalWorkspaceMappingService | None = None,
    ) -> None:
        self._settings = settings
        self._paths = RuntimePathResolver(settings)
        self._workspace_repository = workspace_repository
        self._project_repository = project_repository
        self._project_registry = project_registry
        self._data_source_repository = data_source_repository
        self._database_environment_repository = database_environment_repository
        self._local_mapping = local_mapping

    def list_workspaces(self) -> list[WorkspaceSummary]:
        try:
            records = self._workspace_repository.list_workspaces()
        except WorkspaceRepositoryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        records = [
            mapped for record in records if (mapped := self._mapped_record(record)) is not None
        ]
        for record in records:
            self._project_registry.register_workspace(record)
        return [self._workspace_summary(record) for record in records]

    def reload_local_mapping(self) -> list[WorkspaceSummary]:
        if self._local_mapping is None or not self._local_mapping.is_configured:
            return self.list_workspaces()
        try:
            self._local_mapping.reload()
            self._project_registry.load_persisted_projects()
        except (LocalWorkspaceMappingError, ProjectRegistryError) as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        return self.list_workspaces()

    def get_workspace(self, workspace_id: str) -> WorkspaceSummary:
        return self._workspace_summary(self._workspace_record(workspace_id))

    def create_workspace(
        self,
        *,
        name: str,
        workspace_type: str,
        root_path: str,
    ) -> WorkspaceSummary:
        if self._local_mapping is not None and self._local_mapping.is_configured:
            raise WorkspaceManagementError(
                "启用本机映射文件后，请先创建数据库工作空间，再在映射文件中启用卡片"
            )
        normalized_name = name.strip()
        normalized_type = workspace_type.strip()
        if not normalized_name:
            raise WorkspaceManagementError("工作空间名称不能为空")
        if not normalized_type:
            raise WorkspaceManagementError("工作空间类型不能为空")
        normalized_root = self._validate_workspace_root(root_path)
        workspace_id = uuid4().hex
        try:
            self._workspace_repository.create_workspace(
                workspace_id=workspace_id,
                name=normalized_name,
                workspace_type=normalized_type,
                root_path=normalized_root,
            )
            record = self._workspace_repository.get_workspace(workspace_id)
        except WorkspaceRepositoryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        if self._database_environment_repository is not None:
            try:
                self._database_environment_repository.upsert_environment(
                    workspace_id=workspace_id,
                    environment="local",
                    display_name="LOCAL",
                    aliases=["local", "本地", "本地环境"],
                    sort_order=0,
                )
            except DatabaseEnvironmentRepositoryError as exc:
                raise WorkspaceManagementError(
                    "工作空间已创建，但默认 local 环境初始化失败"
                ) from exc
        self._project_registry.register_workspace(record)
        return self._workspace_summary(record)

    def update_workspace(
        self,
        workspace_id: str,
        *,
        name: str,
        workspace_type: str,
        root_path: str,
    ) -> WorkspaceSummary:
        current = self._workspace_record(workspace_id)
        normalized_name = name.strip()
        normalized_type = workspace_type.strip()
        if not normalized_name:
            raise WorkspaceManagementError("工作空间名称不能为空")
        if not normalized_type:
            raise WorkspaceManagementError("工作空间类型不能为空")
        normalized_root = self._validate_workspace_root(root_path)
        if normalized_root != current.root_path:
            try:
                self._project_registry.validate_workspace_root(
                    workspace_id,
                    normalized_root,
                )
            except ProjectRegistryError as exc:
                raise WorkspaceManagementError(str(exc)) from exc
        try:
            self._workspace_repository.update_workspace(
                workspace_id,
                name=normalized_name,
                workspace_type=normalized_type,
                root_path=normalized_root,
            )
            updated = self._workspace_repository.get_workspace(workspace_id)
        except WorkspaceRepositoryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        self._project_registry.apply_workspace_record(updated)
        return self._workspace_summary(updated)

    def delete_workspace(self, workspace_id: str) -> None:
        self._workspace_record(workspace_id)
        try:
            self._workspace_repository.delete_workspace(workspace_id)
        except WorkspaceRepositoryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        self._project_registry.remove_workspace_projects(workspace_id)

    def list_projects(self, workspace_id: str) -> list[WorkspaceProjectSummary]:
        self._workspace_record(workspace_id)
        return [
            self._workspace_project_summary(project)
            for project in self._project_registry.list_workspace_projects(workspace_id)
        ]

    def create_project(
        self,
        workspace_id: str,
        *,
        name: str,
        relative_path: str,
        document_relative_path: str,
        project_kind: str,
    ) -> WorkspaceProjectSummary:
        workspace = self._workspace_record(workspace_id)
        try:
            project = self._project_registry.add_workspace_project(
                workspace,
                name=name,
                relative_path=relative_path,
                document_relative_path=document_relative_path,
                project_kind=project_kind,
            )
        except ProjectRegistryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        return self._workspace_project_summary(project)

    def update_project(
        self,
        workspace_id: str,
        project_id: str,
        *,
        name: str,
        relative_path: str,
        document_relative_path: str,
        project_kind: str | None,
    ) -> WorkspaceProjectSummary:
        workspace = self._workspace_record(workspace_id)
        try:
            project = self._project_registry.update_workspace_project(
                workspace,
                project_id,
                name=name,
                relative_path=relative_path,
                document_relative_path=document_relative_path,
                project_kind=project_kind,
            )
        except ProjectRegistryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        return self._workspace_project_summary(project)

    def refresh_workspace(self, workspace_id: str) -> WorkspaceSummary:
        self._workspace_record(workspace_id)
        try:
            self._project_registry.refresh_workspace(workspace_id)
        except ProjectRegistryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        return self.get_workspace(workspace_id)

    def workspace_tree(self, workspace_id: str) -> DocumentTreeNode:
        self._workspace_record(workspace_id)
        try:
            return self._project_registry.get_workspace_tree(workspace_id)
        except ProjectRegistryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc

    def workspace_document(
        self,
        workspace_id: str,
        document_id: str,
    ) -> DocumentDetail:
        self._workspace_record(workspace_id)
        try:
            return self._project_registry.get_workspace_document(
                workspace_id,
                document_id,
            )
        except ProjectRegistryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc

    def delete_project(self, workspace_id: str, project_id: str) -> None:
        self._require_workspace_project(workspace_id, project_id)
        try:
            self._project_registry.delete_project(project_id)
        except ProjectRegistryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc

    def data_source_summary(
        self,
        workspace_id: str,
        *,
        environment: str | None = None,
    ) -> WorkspaceDataSourceSummary:
        self._workspace_record(workspace_id)
        try:
            record = self._data_source_repository.get_workspace_data_source_summary(
                workspace_id,
            )
        except DataSourceRepositoryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        summary = WorkspaceDataSourceSummary.model_validate(record)
        if environment is None:
            return summary
        repository = self._database_environment_repository
        if repository is None:
            if environment != "local":
                raise WorkspaceManagementError("工作空间没有配置所选环境")
            return summary
        try:
            if not repository.has_environment(workspace_id, environment):
                raise WorkspaceManagementError("工作空间没有配置所选环境")
            mappings_configured = bool(repository.list_mappings(workspace_id))
            targets = repository.list_mapping_targets(
                workspace_id=workspace_id,
                environment=environment,
            )
        except DatabaseEnvironmentRepositoryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        if not mappings_configured and environment == "local":
            return summary
        allowed_link_ids = {target.link_id for target in targets}
        sources = []
        for source in summary.sources:
            assignments = [
                assignment
                for assignment in source.assignments
                if assignment.link_id in allowed_link_ids
            ]
            if not assignments:
                continue
            sources.append(
                source.model_copy(
                    update={
                        "assignments": assignments,
                        "database_count": len({item.database_id for item in assignments}),
                        "assignment_count": len(assignments),
                        "project_count": len({item.project_id for item in assignments}),
                    }
                )
            )
        assignments = [item for source in sources for item in source.assignments]
        return WorkspaceDataSourceSummary(
            workspace_id=workspace_id,
            source_count=len(sources),
            database_count=len({item.database_id for item in assignments}),
            assignment_count=len(assignments),
            project_count=len({item.project_id for item in assignments}),
            sources=sources,
        )

    def _workspace_record(self, workspace_id: str) -> WorkspaceRecord:
        try:
            record = self._workspace_repository.get_workspace(workspace_id)
        except WorkspaceRepositoryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        mapped = self._mapped_record(record)
        if mapped is None:
            raise WorkspaceManagementError("工作空间未在本机映射文件中启用")
        self._project_registry.register_workspace(mapped)
        return mapped

    def _mapped_record(self, record: WorkspaceRecord) -> WorkspaceRecord | None:
        if self._local_mapping is None:
            return record
        try:
            return self._local_mapping.map_record(record)
        except LocalWorkspaceMappingError as exc:
            raise WorkspaceManagementError(str(exc)) from exc

    def _workspace_summary(self, record: WorkspaceRecord) -> WorkspaceSummary:
        projects = self._project_registry.list_workspace_projects(record.id)
        source_count = 0
        database_count = 0
        assignment_count = 0
        try:
            data_summary = self._data_source_repository.get_workspace_data_source_summary(
                record.id,
            )
            source_count = data_summary.source_count
            database_count = data_summary.database_count
            assignment_count = data_summary.assignment_count
        except DataSourceRepositoryError:
            pass
        return WorkspaceSummary(
            id=record.id,
            name=record.name,
            workspace_type=record.workspace_type,
            root_path=record.root_path,
            project_count=len(projects),
            frontend_project_count=sum(project.project_kind == "frontend" for project in projects),
            backend_project_count=sum(project.project_kind == "backend" for project in projects),
            error_project_count=sum(project.error is not None for project in projects),
            data_source_count=source_count,
            database_count=database_count,
            database_authorization_count=assignment_count,
            document_reader_count=(
                self._local_mapping.reader_count(record.id)
                if self._local_mapping is not None
                else 0
            ),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _workspace_project_summary(
        self,
        project: ProjectSummary,
    ) -> WorkspaceProjectSummary:
        links = self._data_source_repository.list_links(project_id=project.id)
        return WorkspaceProjectSummary(
            id=project.id,
            name=project.name,
            workspace_id=project.workspace_id or "",
            workspace_name=project.workspace_name or "",
            project_type=project.project_type,
            project_kind=project.project_kind,
            relative_path=project.relative_path,
            document_relative_path=project.document_relative_path,
            agents_path=project.agents_path,
            node_count=project.node_count,
            data_source_count=len({link.data_source_id for link in links}),
            database_count=len(links),
            refreshed_at=project.refreshed_at,
            error=project.error,
        )

    def _require_workspace_project(
        self,
        workspace_id: str,
        project_id: str,
    ) -> ProjectSummary:
        try:
            project = self._project_registry.get_project_summary(project_id)
        except ProjectRegistryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        if project.workspace_id != workspace_id:
            raise WorkspaceManagementError("项目不存在")
        return project

    def _validate_workspace_root(self, root_path: str) -> str:
        try:
            normalized = normalize_workspace_root_path(root_path)
        except WorkspacePathError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        try:
            resolved = self._paths.map_host_path(normalized)
        except RuntimePathError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        if not resolved.is_dir():
            raise WorkspaceManagementError(f"找不到工作空间目录：{normalized}")
        try:
            self._project_registry.validate_workspace_document_entry(normalized)
        except ProjectRegistryError as exc:
            raise WorkspaceManagementError(str(exc)) from exc
        return normalized
