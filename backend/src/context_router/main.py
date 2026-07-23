import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from context_router.api.data_sources import router as data_sources_router
from context_router.api.mcp_integration import router as mcp_integration_router
from context_router.api.projects import router as projects_router
from context_router.api.tasks import router as tasks_router
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
from context_router.repositories.document_read_repository import (
    DocumentReadStore,
    PostgresDocumentReadRepository,
)
from context_router.repositories.project_repository import (
    InMemoryProjectRepository,
    PostgresProjectRepository,
    ProjectStore,
)
from context_router.repositories.task_repository import PostgresTaskRepository, TaskStore
from context_router.services.context_document_read import ContextDocumentReadService
from context_router.services.context_preparation import ContextPreparationService
from context_router.services.database_access import DatabaseAccessService
from context_router.services.database_catalog import DatabaseCatalogService
from context_router.services.database_query import DatabaseQueryService
from context_router.services.mcp_integration import McpIntegrationService
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    task_repository: TaskStore | None = None,
    document_read_repository: DocumentReadStore | None = None,
    project_repository: ProjectStore | None = None,
    data_source_repository: DataSourceStore | None = None,
    database_call_repository: DatabaseCallStore | None = None,
    connector_registry: ConnectorRegistry | None = None,
    connector_manager: ConnectorManager | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    resolved_project_repository = project_repository or (
        PostgresProjectRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryProjectRepository()
    )
    registry = ProjectRegistry(resolved_settings, resolved_project_repository)
    resolved_data_source_repository = data_source_repository or (
        PostgresDataSourceRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryDataSourceRepository()
    )
    resolved_task_repository = task_repository or PostgresTaskRepository(
        resolved_settings.database_url
    )
    resolved_read_repository = document_read_repository or PostgresDocumentReadRepository(
        resolved_settings.database_url
    )
    resolved_database_call_repository = database_call_repository or (
        PostgresDatabaseCallRepository(resolved_settings.database_url)
        if resolved_settings.database_url
        else InMemoryDatabaseCallRepository()
    )
    resolved_connector_registry = connector_registry or _create_connector_registry()
    resolved_connector_manager = connector_manager or ConnectorManager(
        resolved_connector_registry,
        max_cached_connectors=resolved_settings.database_max_cached_connectors,
        max_concurrency_per_source=resolved_settings.database_max_concurrency_per_source,
    )
    database_access_service = DatabaseAccessService(
        settings=resolved_settings,
        registry=registry,
        task_repository=resolved_task_repository,
        data_source_repository=resolved_data_source_repository,
        connector_registry=resolved_connector_registry,
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
    context_service = ContextPreparationService(
        registry,
        resolved_task_repository,
        database_access_service,
    )
    document_read_service = ContextDocumentReadService(
        registry,
        resolved_task_repository,
        resolved_read_repository,
    )
    mcp_integration_service = McpIntegrationService(resolved_settings, registry)
    mcp_server = create_context_router_mcp(
        context_service,
        document_read_service,
        database_catalog_service,
        database_query_service,
    )
    mcp_app = mcp_server.streamable_http_app()

    try:
        registry.load_persisted_projects()
    except ProjectRegistryError as exc:
        logger.warning("Unable to restore persisted document projects: %s", exc)

    if (
        resolved_settings.default_project_name
        and resolved_settings.default_agents_path
        and not registry.has_agents_path(resolved_settings.default_agents_path)
    ):
        try:
            registry.add_project(
                name=resolved_settings.default_project_name,
                agents_path=resolved_settings.default_agents_path,
            )
        except ProjectRegistryError as exc:
            logger.warning("Unable to persist default document project: %s", exc)
            try:
                registry.add_project(
                    name=resolved_settings.default_project_name,
                    agents_path=resolved_settings.default_agents_path,
                    persist=False,
                )
            except ProjectRegistryError as fallback_exc:
                logger.warning("Unable to load default document project: %s", fallback_exc)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            async with mcp_server.session_manager.run():
                yield
        finally:
            resolved_connector_manager.close_all()

    app = FastAPI(
        title="Agent Context Router",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.project_registry = registry
    app.state.context_preparation_service = context_service
    app.state.context_document_read_service = document_read_service
    app.state.task_repository = resolved_task_repository
    app.state.document_read_repository = resolved_read_repository
    app.state.project_repository = resolved_project_repository
    app.state.mcp_integration_service = mcp_integration_service
    app.state.data_source_repository = resolved_data_source_repository
    app.state.database_call_repository = resolved_database_call_repository
    app.state.connector_registry = resolved_connector_registry
    app.state.connector_manager = resolved_connector_manager
    app.state.database_access_service = database_access_service
    app.state.database_catalog_service = database_catalog_service
    app.state.database_query_service = database_query_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:49174", "http://localhost:49174"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects_router, prefix=resolved_settings.api_prefix)
    app.include_router(tasks_router, prefix=resolved_settings.api_prefix)
    app.include_router(mcp_integration_router, prefix=resolved_settings.api_prefix)
    app.include_router(data_sources_router, prefix=resolved_settings.api_prefix)

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
    return registry
