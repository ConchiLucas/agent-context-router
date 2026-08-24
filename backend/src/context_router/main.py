import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from context_router.api.ai_data_visualization import router as ai_data_visualization_router
from context_router.api.ai_interface_visualization import (
    router as ai_interface_visualization_router,
)
from context_router.api.ai_log_visualization import router as ai_log_visualization_router
from context_router.api.data_sources import router as data_sources_router
from context_router.api.database_environments import router as database_environments_router
from context_router.api.document_chain_analytics import (
    router as document_chain_analytics_router,
)
from context_router.api.document_read_stats import router as document_read_stats_router
from context_router.api.interface_forwarding import router as interface_forwarding_router
from context_router.api.mcp_integration import router as mcp_integration_router
from context_router.api.mcp_traces import router as mcp_traces_router
from context_router.api.nacos_profiles import router as nacos_profiles_router
from context_router.api.projects import router as projects_router
from context_router.api.runtime_configs import router as runtime_configs_router
from context_router.api.runtime_runner import router as runtime_runner_router
from context_router.api.shared_config import router as shared_config_router
from context_router.api.system_guides import router as system_guides_router
from context_router.api.table_relations import router as table_relations_router
from context_router.api.tasks import router as tasks_router
from context_router.api.value_mappings import router as value_mappings_router
from context_router.api.workspace_runtime import router as workspace_runtime_router
from context_router.api.workspaces import router as workspaces_router
from context_router.config import Settings
from context_router.database.connectors import (
    ClickHouseConnector,
    MySQLConnector,
    PostgreSQLConnector,
)
from context_router.database.manager import ConnectorManager
from context_router.database.policy import SqlSafetyPolicy
from context_router.database.registry import ConnectorRegistry
from context_router.database.result import DatabaseResultFormatter
from context_router.mcp_server import create_context_router_mcp
from context_router.middleware.browser_read_only import BrowserReadOnlyMiddleware
from context_router.repositories.ai_data_query_repository import (
    AiDataQueryStore,
    InMemoryAiDataQueryRepository,
    PostgresAiDataQueryRepository,
)
from context_router.repositories.ai_log_investigation_repository import (
    AiLogInvestigationStore,
    InMemoryAiLogInvestigationRepository,
    PostgresAiLogInvestigationRepository,
)
from context_router.repositories.data_source_repository import (
    DataSourceStore,
    InMemoryDataSourceRepository,
    PostgresDataSourceRepository,
)
from context_router.repositories.database_call_repository import (
    DatabaseCallStore,
    InMemoryDatabaseCallRepository,
    PostgresDatabaseCallRepository,
)
from context_router.repositories.database_environment_repository import (
    DatabaseEnvironmentStore,
    InMemoryDatabaseEnvironmentRepository,
    PostgresDatabaseEnvironmentRepository,
)
from context_router.repositories.database_tool_payload_repository import (
    DatabaseToolPayloadStore,
    InMemoryDatabaseToolPayloadRepository,
    PostgresDatabaseToolPayloadRepository,
)
from context_router.repositories.document_chain_analytics_repository import (
    DocumentChainAnalyticsStore,
    PostgresDocumentChainAnalyticsRepository,
)
from context_router.repositories.document_read_repository import (
    DocumentReadStore,
    PostgresDocumentReadRepository,
)
from context_router.repositories.document_read_stats_repository import (
    DocumentReadStatsStore,
    PostgresDocumentReadStatsRepository,
)
from context_router.repositories.document_search_repository import (
    DocumentSearchStore,
    PostgresDocumentSearchRepository,
)
from context_router.repositories.mcp_environment_default_repository import (
    InMemoryMcpEnvironmentDefaultRepository,
    McpEnvironmentDefaultStore,
    PostgresMcpEnvironmentDefaultRepository,
)
from context_router.repositories.mcp_tool_call_repository import (
    InMemoryMcpToolCallRepository,
    McpToolCallStore,
    PostgresMcpToolCallRepository,
)
from context_router.repositories.nacos_profile_repository import (
    InMemoryNacosProfileRepository,
    NacosProfileStore,
    PostgresNacosProfileRepository,
)
from context_router.repositories.project_repository import (
    InMemoryProjectRepository,
    PostgresProjectRepository,
    ProjectStore,
)
from context_router.repositories.runtime_config_repository import (
    InMemoryRuntimeConfigRepository,
    PostgresRuntimeConfigRepository,
    RuntimeConfigStore,
)
from context_router.repositories.runtime_operation_repository import (
    InMemoryRuntimeOperationRepository,
    PostgresRuntimeOperationRepository,
    RuntimeOperationRepositoryError,
    RuntimeOperationStore,
)
from context_router.repositories.runtime_run_repository import (
    InMemoryRuntimeRunRepository,
    PostgresRuntimeRunRepository,
    RuntimeRunStore,
)
from context_router.repositories.runtime_runner_repository import (
    InMemoryRuntimeRunnerRepository,
    PostgresRuntimeRunnerRepository,
    RuntimeRunnerStore,
)
from context_router.repositories.shared_ai_default_repository import (
    InMemorySharedAiDefaultRepository,
    PostgresSharedAiDefaultRepository,
    SharedAiDefaultStore,
)
from context_router.repositories.system_guide_repository import (
    InMemorySystemGuideRepository,
    PostgresSystemGuideRepository,
    SystemGuideStore,
)
from context_router.repositories.table_relation_repository import (
    InMemoryTableRelationRepository,
    PostgresTableRelationRepository,
    TableRelationStore,
)
from context_router.repositories.task_repository import PostgresTaskRepository, TaskStore
from context_router.repositories.workspace_deploy_repository import (
    InMemoryWorkspaceDeployRepository,
    PostgresWorkspaceDeployRepository,
    WorkspaceDeployStore,
)
from context_router.repositories.workspace_repository import (
    InMemoryWorkspaceRepository,
    PostgresWorkspaceRepository,
    WorkspaceRepositoryError,
    WorkspaceStore,
)
from context_router.repositories.workspace_runtime_repository import (
    InMemoryWorkspaceRuntimeRepository,
    PostgresWorkspaceRuntimeRepository,
    WorkspaceRuntimeStore,
)
from context_router.repositories.workspace_shared_file_repository import (
    InMemoryWorkspaceSharedFileRepository,
    PostgresWorkspaceSharedFileRepository,
    WorkspaceSharedFileStore,
)
from context_router.services.ai_data_visualization import AiDataVisualizationService
from context_router.services.ai_interface_visualization import AiInterfaceVisualizationService
from context_router.services.ai_log_visualization import AiLogVisualizationService
from context_router.services.context_document_read import ContextDocumentReadService
from context_router.services.context_document_search import ContextDocumentSearchService
from context_router.services.context_preparation import ContextPreparationService
from context_router.services.database_access import DatabaseAccessService
from context_router.services.database_catalog import DatabaseCatalogService
from context_router.services.database_query import DatabaseQueryService
from context_router.services.database_tool_payload import DatabaseToolPayloadService
from context_router.services.document_chain_analytics import DocumentChainAnalyticsService
from context_router.services.document_read_stats import DocumentReadStatsService
from context_router.services.document_search_index import DocumentSearchIndexer
from context_router.services.interface_forwarding import InterfaceForwardingService
from context_router.services.interface_forwarding_context import InterfaceForwardingContextService
from context_router.services.local_workspace_mapping import LocalWorkspaceMappingService
from context_router.services.mcp_integration import McpIntegrationService
from context_router.services.mcp_trace import McpTraceService
from context_router.services.nacos_middleware import MiddlewareContextService
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError
from context_router.services.runtime_execution import RuntimeExecutionService
from context_router.services.runtime_materialization import RuntimeMaterializationService
from context_router.services.shared_ai_config import SharedAiConfigService
from context_router.services.shared_config_client import SharedConfigCenterClient
from context_router.services.system_guides import SystemGuideService
from context_router.services.table_relation_context import TableRelationContextService
from context_router.services.value_mapping import ValueMappingService
from context_router.services.workspace_containers import WorkspaceContainerService
from context_router.services.workspace_deploy_sync import WorkspaceDeploySyncService
from context_router.services.workspace_management import WorkspaceManagementService
from context_router.services.workspace_runtime_orchestration import (
    WorkspaceRuntimeOrchestrationService,
)
from context_router.services.workspace_shared_files import WorkspaceSharedFilesService

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    task_repository: TaskStore | None = None,
    document_read_repository: DocumentReadStore | None = None,
    project_repository: ProjectStore | None = None,
    data_source_repository: DataSourceStore | None = None,
    database_call_repository: DatabaseCallStore | None = None,
    mcp_tool_call_repository: McpToolCallStore | None = None,
    database_payload_repository: DatabaseToolPayloadStore | None = None,
    connector_registry: ConnectorRegistry | None = None,
    connector_manager: ConnectorManager | None = None,
    document_search_repository: DocumentSearchStore | None = None,
    workspace_repository: WorkspaceStore | None = None,
    database_environment_repository: DatabaseEnvironmentStore | None = None,
    table_relation_repository: TableRelationStore | None = None,
    runtime_config_repository: RuntimeConfigStore | None = None,
    runtime_run_repository: RuntimeRunStore | None = None,
    workspace_runtime_repository: WorkspaceRuntimeStore | None = None,
    runtime_operation_repository: RuntimeOperationStore | None = None,
    runtime_runner_repository: RuntimeRunnerStore | None = None,
    workspace_deploy_repository: WorkspaceDeployStore | None = None,
    workspace_shared_file_repository: WorkspaceSharedFileStore | None = None,
    document_read_stats_repository: DocumentReadStatsStore | None = None,
    document_chain_analytics_repository: DocumentChainAnalyticsStore | None = None,
    system_guide_repository: SystemGuideStore | None = None,
    nacos_profile_repository: NacosProfileStore | None = None,
    mcp_environment_default_repository: McpEnvironmentDefaultStore | None = None,
    shared_ai_default_repository: SharedAiDefaultStore | None = None,
    ai_data_query_repository: AiDataQueryStore | None = None,
    ai_log_investigation_repository: AiLogInvestigationStore | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    if workspace_repository is not None:
        resolved_workspace_repository = workspace_repository
    elif project_repository is not None and hasattr(
        project_repository,
        "workspace_repository",
    ):
        resolved_workspace_repository = project_repository.workspace_repository
    elif resolved_settings.database_url:
        resolved_workspace_repository = PostgresWorkspaceRepository(resolved_settings.database_url)
    else:
        resolved_workspace_repository = InMemoryWorkspaceRepository()

    if project_repository is not None:
        resolved_project_repository = project_repository
    elif resolved_settings.database_url:
        resolved_project_repository = PostgresProjectRepository(resolved_settings.database_url)
    else:
        resolved_project_repository = InMemoryProjectRepository(resolved_workspace_repository)
    resolved_document_search_repository = (
        document_search_repository
        or PostgresDocumentSearchRepository(resolved_settings.database_url)
    )
    document_search_indexer = DocumentSearchIndexer(
        resolved_document_search_repository,
    )
    local_workspace_mapping = LocalWorkspaceMappingService(resolved_settings)
    registry = ProjectRegistry(
        resolved_settings,
        resolved_project_repository,
        document_search_indexer,
        local_workspace_mapping,
    )
    resolved_data_source_repository = data_source_repository or (
        PostgresDataSourceRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryDataSourceRepository(resolved_project_repository)
    )
    if database_environment_repository is not None:
        resolved_database_environment_repository = database_environment_repository
    elif isinstance(resolved_workspace_repository, InMemoryWorkspaceRepository):
        resolved_database_environment_repository = InMemoryDatabaseEnvironmentRepository()
    elif resolved_settings.database_url:
        resolved_database_environment_repository = PostgresDatabaseEnvironmentRepository(
            resolved_settings.database_url
        )
    else:
        resolved_database_environment_repository = InMemoryDatabaseEnvironmentRepository()
    resolved_table_relation_repository = table_relation_repository or (
        PostgresTableRelationRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryTableRelationRepository()
    )
    resolved_nacos_profile_repository = nacos_profile_repository or (
        PostgresNacosProfileRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryNacosProfileRepository()
    )
    resolved_mcp_environment_default_repository = mcp_environment_default_repository or (
        PostgresMcpEnvironmentDefaultRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryMcpEnvironmentDefaultRepository()
    )
    resolved_shared_ai_default_repository = shared_ai_default_repository or (
        PostgresSharedAiDefaultRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemorySharedAiDefaultRepository()
    )
    resolved_ai_data_query_repository = ai_data_query_repository or (
        PostgresAiDataQueryRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryAiDataQueryRepository()
    )
    resolved_ai_log_investigation_repository = ai_log_investigation_repository or (
        PostgresAiLogInvestigationRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryAiLogInvestigationRepository()
    )
    resolved_runtime_config_repository = runtime_config_repository or (
        PostgresRuntimeConfigRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryRuntimeConfigRepository()
    )
    runtime_materialization_service = RuntimeMaterializationService(
        resolved_settings.runtime_root,
    )
    resolved_runtime_run_repository = runtime_run_repository or (
        PostgresRuntimeRunRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryRuntimeRunRepository()
    )
    runtime_execution_service = RuntimeExecutionService(
        settings=resolved_settings,
        registry=registry,
        config_repository=resolved_runtime_config_repository,
        run_repository=resolved_runtime_run_repository,
        materialization_service=runtime_materialization_service,
    )
    resolved_task_repository = task_repository or PostgresTaskRepository(
        resolved_settings.database_url
    )
    resolved_runtime_runner_repository = runtime_runner_repository or (
        PostgresRuntimeRunnerRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryRuntimeRunnerRepository()
    )
    resolved_system_guide_repository = system_guide_repository or (
        PostgresSystemGuideRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemorySystemGuideRepository()
    )
    system_guide_service = SystemGuideService(resolved_system_guide_repository)
    shared_ai_config_service = SharedAiConfigService(
        SharedConfigCenterClient(
            resolved_settings.shared_config_center_base_url,
            resolved_settings.shared_config_center_timeout_seconds,
        ),
        resolved_shared_ai_default_repository,
    )
    interface_forwarding_service = InterfaceForwardingService(resolved_settings.database_url)
    resolved_workspace_runtime_repository = workspace_runtime_repository or (
        PostgresWorkspaceRuntimeRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryWorkspaceRuntimeRepository()
    )
    resolved_workspace_deploy_repository = workspace_deploy_repository or (
        PostgresWorkspaceDeployRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryWorkspaceDeployRepository(
            workspace_runtime=resolved_workspace_runtime_repository,
            project_runtime=resolved_runtime_config_repository,
        )
    )
    workspace_deploy_sync_service = WorkspaceDeploySyncService(
        workspace_repository=resolved_workspace_repository,
        project_repository=resolved_project_repository,
        workspace_runtime_repository=resolved_workspace_runtime_repository,
        project_runtime_repository=resolved_runtime_config_repository,
        deploy_repository=resolved_workspace_deploy_repository,
        workspace_root_resolver=lambda workspace_id: (
            registry.get_workspace_snapshot(workspace_id).resolved_root_path
        ),
    )
    workspace_container_service = WorkspaceContainerService(resolved_settings.runtime_docker_socket)
    resolved_workspace_shared_file_repository = workspace_shared_file_repository or (
        PostgresWorkspaceSharedFileRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryWorkspaceSharedFileRepository(resolved_workspace_deploy_repository)
    )
    workspace_shared_files_service = WorkspaceSharedFilesService(
        settings=resolved_settings,
        local_mapping=local_workspace_mapping,
        workspace_repository=resolved_workspace_repository,
        project_repository=resolved_project_repository,
        shared_file_repository=resolved_workspace_shared_file_repository,
        registry=registry,
    )
    resolved_runtime_operation_repository = runtime_operation_repository or (
        PostgresRuntimeOperationRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryRuntimeOperationRepository()
    )
    workspace_runtime_orchestration_service = WorkspaceRuntimeOrchestrationService(
        task_repository=resolved_task_repository,
        registry=registry,
        project_config_repository=resolved_runtime_config_repository,
        workspace_runtime_repository=resolved_workspace_runtime_repository,
        operation_repository=resolved_runtime_operation_repository,
        materialization_service=runtime_materialization_service,
        runner_available=lambda: resolved_runtime_runner_repository.is_available(
            resolved_settings.runtime_runner_heartbeat_ttl_seconds
        ),
        local_mapping=local_workspace_mapping,
    )
    resolved_read_repository = document_read_repository or PostgresDocumentReadRepository(
        resolved_settings.database_url
    )
    resolved_document_read_stats_repository = (
        document_read_stats_repository
        or PostgresDocumentReadStatsRepository(resolved_settings.database_url)
    )
    resolved_document_chain_analytics_repository = (
        document_chain_analytics_repository
        or PostgresDocumentChainAnalyticsRepository(resolved_settings.database_url)
    )
    resolved_database_call_repository = database_call_repository or (
        PostgresDatabaseCallRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryDatabaseCallRepository()
    )
    resolved_mcp_tool_call_repository = mcp_tool_call_repository or (
        PostgresMcpToolCallRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryMcpToolCallRepository()
    )
    resolved_database_payload_repository = database_payload_repository or (
        PostgresDatabaseToolPayloadRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryDatabaseToolPayloadRepository()
    )
    resolved_connector_registry = connector_registry or _create_connector_registry()
    resolved_connector_manager = connector_manager or ConnectorManager(
        resolved_connector_registry,
        max_cached_connectors=resolved_settings.database_max_cached_connectors,
        max_concurrency_per_source=resolved_settings.database_max_concurrency_per_source,
    )
    workspace_management_service = WorkspaceManagementService(
        settings=resolved_settings,
        workspace_repository=resolved_workspace_repository,
        project_repository=resolved_project_repository,
        project_registry=registry,
        data_source_repository=resolved_data_source_repository,
        database_environment_repository=resolved_database_environment_repository,
        local_mapping=local_workspace_mapping,
    )
    database_access_service = DatabaseAccessService(
        settings=resolved_settings,
        registry=registry,
        task_repository=resolved_task_repository,
        data_source_repository=resolved_data_source_repository,
        connector_registry=resolved_connector_registry,
        database_environment_repository=resolved_database_environment_repository,
        local_mapping=local_workspace_mapping,
    )
    result_formatter = DatabaseResultFormatter()
    database_catalog_service = DatabaseCatalogService(
        settings=resolved_settings,
        access_service=database_access_service,
        connector_manager=resolved_connector_manager,
        result_formatter=result_formatter,
        call_repository=resolved_database_call_repository,
    )
    database_query_service = DatabaseQueryService(
        access_service=database_access_service,
        connector_manager=resolved_connector_manager,
        sql_policy=SqlSafetyPolicy(),
        result_formatter=result_formatter,
        call_repository=resolved_database_call_repository,
    )
    value_mapping_service = ValueMappingService(
        database_url=resolved_settings.database_url,
        database_access_service=database_access_service,
        connector_manager=resolved_connector_manager,
        sql_policy=SqlSafetyPolicy(),
        task_repository=resolved_task_repository,
    )
    ai_data_visualization_service = AiDataVisualizationService(
        records=resolved_ai_data_query_repository,
        workspaces=resolved_workspace_repository,
        environments=resolved_database_environment_repository,
        relations=resolved_table_relation_repository,
        tasks=resolved_task_repository,
    )
    ai_interface_visualization_service = AiInterfaceVisualizationService(
        resolved_settings.database_url
    )
    ai_log_visualization_service = AiLogVisualizationService(
        records=resolved_ai_log_investigation_repository,
        tasks=resolved_task_repository,
        projects=resolved_project_repository,
        workspaces=resolved_workspace_repository,
        containers=workspace_container_service,
    )
    interface_forwarding_context_service = InterfaceForwardingContextService(
        database_url=resolved_settings.database_url,
        task_repository=resolved_task_repository,
        database_environment_repository=resolved_database_environment_repository,
        value_mapping_service=value_mapping_service,
        host_runner_available=lambda: resolved_runtime_runner_repository.is_available(
            resolved_settings.runtime_runner_heartbeat_ttl_seconds,
            "interface-forwarding",
        ),
    )
    context_service = ContextPreparationService(
        registry,
        resolved_task_repository,
        database_access_service,
        resolved_mcp_environment_default_repository,
    )
    middleware_context_service = MiddlewareContextService(
        registry=registry,
        task_repository=resolved_task_repository,
        profile_repository=resolved_nacos_profile_repository,
        database_access_service=database_access_service,
        mcp_environment_defaults=resolved_mcp_environment_default_repository,
    )
    document_read_service = ContextDocumentReadService(
        registry,
        resolved_task_repository,
        resolved_read_repository,
        system_guide_service,
    )
    document_search_service = ContextDocumentSearchService(
        registry,
        resolved_task_repository,
        resolved_document_search_repository,
    )
    database_payload_service = DatabaseToolPayloadService(
        resolved_database_payload_repository,
        request_max_bytes=resolved_settings.database_payload_request_bytes,
        response_max_bytes=resolved_settings.database_payload_response_bytes,
        hard_max_bytes=resolved_settings.database_payload_hard_max_bytes,
        ttl_days=resolved_settings.database_payload_ttl_days,
        cleanup_interval_seconds=resolved_settings.database_payload_cleanup_interval_seconds,
    )
    mcp_trace_service = McpTraceService(
        tool_call_repository=resolved_mcp_tool_call_repository,
        task_repository=resolved_task_repository,
        document_read_repository=resolved_read_repository,
        database_call_repository=resolved_database_call_repository,
        registry=registry,
        database_payload_service=database_payload_service,
    )
    mcp_integration_service = McpIntegrationService(resolved_settings, registry)
    document_read_stats_service = DocumentReadStatsService(
        repository=resolved_document_read_stats_repository,
    )
    document_chain_analytics_service = DocumentChainAnalyticsService(
        repository=resolved_document_chain_analytics_repository,
    )
    table_relation_context_service = TableRelationContextService(
        registry=registry,
        task_repository=resolved_task_repository,
        reader=resolved_table_relation_repository,
    )
    mcp_server = create_context_router_mcp(
        context_service,
        document_read_service,
        database_catalog_service,
        database_query_service,
        trace_service=mcp_trace_service,
        database_payload_service=database_payload_service,
        document_search_service=document_search_service,
        workspace_runtime_service=workspace_runtime_orchestration_service,
        middleware_context_service=middleware_context_service,
        table_relation_context_service=table_relation_context_service,
        interface_forwarding_context_service=interface_forwarding_context_service,
        value_mapping_service=value_mapping_service,
        ai_data_visualization_service=ai_data_visualization_service,
        ai_log_visualization_service=ai_log_visualization_service,
    )
    mcp_app = mcp_server.streamable_http_app()

    try:
        registry.load_persisted_projects()
    except ProjectRegistryError as exc:
        logger.warning("Unable to restore persisted document projects: %s", exc)
    try:
        for workspace in resolved_workspace_repository.list_workspaces():
            mapped_workspace = local_workspace_mapping.map_record(workspace)
            if mapped_workspace is not None:
                registry.register_workspace(mapped_workspace)
    except (WorkspaceRepositoryError, ProjectRegistryError) as exc:
        logger.warning("Unable to restore persisted workspaces: %s", exc)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            mcp_trace_service.reconcile_interrupted_calls()
            runtime_execution_service.reconcile_interrupted()
            try:
                resolved_runtime_operation_repository.reconcile_expired()
            except RuntimeOperationRepositoryError:
                logger.warning("Unable to reconcile expired runtime operations", exc_info=True)
            database_payload_service.reconcile_startup()
            async with mcp_server.session_manager.run():
                yield
        finally:
            resolved_connector_manager.close_all()

    app = FastAPI(
        title="Agent Context Router",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def redact_request_validation_input(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = [
            {key: value for key, value in error.items() if key not in {"input", "ctx"}}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=jsonable_encoder({"detail": errors}),
        )

    app.state.project_registry = registry
    app.state.settings = resolved_settings
    app.state.context_preparation_service = context_service
    app.state.context_document_read_service = document_read_service
    app.state.context_document_search_service = document_search_service
    app.state.document_search_repository = resolved_document_search_repository
    app.state.task_repository = resolved_task_repository
    app.state.document_read_repository = resolved_read_repository
    app.state.project_repository = resolved_project_repository
    app.state.runtime_config_repository = resolved_runtime_config_repository
    app.state.runtime_materialization_service = runtime_materialization_service
    app.state.runtime_run_repository = resolved_runtime_run_repository
    app.state.runtime_execution_service = runtime_execution_service
    app.state.workspace_runtime_repository = resolved_workspace_runtime_repository
    app.state.runtime_operation_repository = resolved_runtime_operation_repository
    app.state.runtime_runner_repository = resolved_runtime_runner_repository
    app.state.workspace_runtime_orchestration_service = workspace_runtime_orchestration_service
    app.state.workspace_deploy_sync_service = workspace_deploy_sync_service
    app.state.workspace_container_service = workspace_container_service
    app.state.workspace_shared_files_service = workspace_shared_files_service
    app.state.workspace_shared_file_repository = resolved_workspace_shared_file_repository
    app.state.workspace_repository = resolved_workspace_repository
    app.state.workspace_management_service = workspace_management_service
    app.state.local_workspace_mapping = local_workspace_mapping
    app.state.mcp_integration_service = mcp_integration_service
    app.state.mcp_server = mcp_server
    app.state.data_source_repository = resolved_data_source_repository
    app.state.database_environment_repository = resolved_database_environment_repository
    app.state.table_relation_repository = resolved_table_relation_repository
    app.state.table_relation_context_service = table_relation_context_service
    app.state.nacos_profile_repository = resolved_nacos_profile_repository
    app.state.mcp_environment_default_repository = resolved_mcp_environment_default_repository
    app.state.middleware_context_service = middleware_context_service
    app.state.database_call_repository = resolved_database_call_repository
    app.state.connector_registry = resolved_connector_registry
    app.state.connector_manager = resolved_connector_manager
    app.state.database_access_service = database_access_service
    app.state.database_catalog_service = database_catalog_service
    app.state.database_query_service = database_query_service
    app.state.database_result_formatter = result_formatter
    app.state.mcp_tool_call_repository = resolved_mcp_tool_call_repository
    app.state.database_payload_repository = resolved_database_payload_repository
    app.state.database_payload_service = database_payload_service
    app.state.mcp_trace_service = mcp_trace_service
    app.state.system_guide_repository = resolved_system_guide_repository
    app.state.system_guide_service = system_guide_service
    app.state.shared_ai_config_service = shared_ai_config_service
    app.state.interface_forwarding_service = interface_forwarding_service
    app.state.interface_forwarding_context_service = interface_forwarding_context_service
    app.state.value_mapping_service = value_mapping_service
    app.state.ai_data_visualization_service = ai_data_visualization_service
    app.state.ai_interface_visualization_service = ai_interface_visualization_service
    app.state.ai_log_visualization_service = ai_log_visualization_service
    app.state.ai_log_investigation_repository = resolved_ai_log_investigation_repository
    app.state.document_read_stats_repository = resolved_document_read_stats_repository
    app.state.document_read_stats_service = document_read_stats_service
    app.state.document_chain_analytics_repository = resolved_document_chain_analytics_repository
    app.state.document_chain_analytics_service = document_chain_analytics_service
    frontend_origins = [
        "http://127.0.0.1:49175",
        "http://localhost:49175",
    ]
    app.add_middleware(
        BrowserReadOnlyMiddleware,
        api_prefix=resolved_settings.api_prefix,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=frontend_origins,
        allow_methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    app.include_router(projects_router, prefix=resolved_settings.api_prefix)
    app.include_router(runtime_configs_router, prefix=resolved_settings.api_prefix)
    app.include_router(runtime_runner_router, prefix=resolved_settings.api_prefix)
    app.include_router(workspaces_router, prefix=resolved_settings.api_prefix)
    app.include_router(workspace_runtime_router, prefix=resolved_settings.api_prefix)
    app.include_router(database_environments_router, prefix=resolved_settings.api_prefix)
    app.include_router(table_relations_router, prefix=resolved_settings.api_prefix)
    app.include_router(nacos_profiles_router, prefix=resolved_settings.api_prefix)
    app.include_router(tasks_router, prefix=resolved_settings.api_prefix)
    app.include_router(mcp_integration_router, prefix=resolved_settings.api_prefix)
    app.include_router(data_sources_router, prefix=resolved_settings.api_prefix)
    app.include_router(mcp_traces_router, prefix=resolved_settings.api_prefix)
    app.include_router(document_read_stats_router, prefix=resolved_settings.api_prefix)
    app.include_router(document_chain_analytics_router, prefix=resolved_settings.api_prefix)
    app.include_router(system_guides_router, prefix=resolved_settings.api_prefix)
    app.include_router(shared_config_router, prefix=resolved_settings.api_prefix)
    app.include_router(interface_forwarding_router, prefix=resolved_settings.api_prefix)
    app.include_router(value_mappings_router, prefix=resolved_settings.api_prefix)
    app.include_router(ai_data_visualization_router, prefix=resolved_settings.api_prefix)
    app.include_router(ai_interface_visualization_router, prefix=resolved_settings.api_prefix)
    app.include_router(ai_log_visualization_router, prefix=resolved_settings.api_prefix)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/mcp", mcp_app)

    return app


def _create_connector_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register("clickhouse", ClickHouseConnector, ClickHouseConnector.capabilities)
    registry.register("postgresql", PostgreSQLConnector, PostgreSQLConnector.capabilities)
    registry.register("mysql", MySQLConnector, MySQLConnector.capabilities)
    registry.register("mariadb", MySQLConnector, MySQLConnector.capabilities)
    registry.register("doris", MySQLConnector, MySQLConnector.capabilities)
    return registry
