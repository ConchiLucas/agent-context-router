import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from context_router.api.projects import router as projects_router
from context_router.api.tasks import router as tasks_router
from context_router.config import Settings
from context_router.mcp_server import create_context_router_mcp
from context_router.repositories.document_read_repository import (
    DocumentReadStore,
    PostgresDocumentReadRepository,
)
from context_router.repositories.task_repository import PostgresTaskRepository, TaskStore
from context_router.services.context_document_read import ContextDocumentReadService
from context_router.services.context_preparation import ContextPreparationService
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    task_repository: TaskStore | None = None,
    document_read_repository: DocumentReadStore | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    registry = ProjectRegistry(resolved_settings)
    resolved_task_repository = task_repository or PostgresTaskRepository(
        resolved_settings.database_url
    )
    resolved_read_repository = document_read_repository or PostgresDocumentReadRepository(
        resolved_settings.database_url
    )
    context_service = ContextPreparationService(registry, resolved_task_repository)
    document_read_service = ContextDocumentReadService(
        registry,
        resolved_task_repository,
        resolved_read_repository,
    )
    mcp_server = create_context_router_mcp(context_service, document_read_service)
    mcp_app = mcp_server.streamable_http_app()

    if resolved_settings.default_project_name and resolved_settings.default_agents_path:
        try:
            registry.add_project(
                name=resolved_settings.default_project_name,
                agents_path=resolved_settings.default_agents_path,
            )
        except ProjectRegistryError as exc:
            logger.warning("Unable to load default document project: %s", exc)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(
        title="Document Tree",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.project_registry = registry
    app.state.context_preparation_service = context_service
    app.state.context_document_read_service = document_read_service
    app.state.task_repository = resolved_task_repository
    app.state.document_read_repository = resolved_read_repository
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects_router, prefix=resolved_settings.api_prefix)
    app.include_router(tasks_router, prefix=resolved_settings.api_prefix)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/mcp", mcp_app)

    return app
