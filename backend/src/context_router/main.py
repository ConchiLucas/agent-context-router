import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from context_router.api.projects import router as projects_router
from context_router.config import Settings
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    registry = ProjectRegistry(resolved_settings)

    if resolved_settings.default_project_name and resolved_settings.default_agents_path:
        try:
            registry.add_project(
                name=resolved_settings.default_project_name,
                agents_path=resolved_settings.default_agents_path,
            )
        except ProjectRegistryError as exc:
            logger.warning("Unable to load default document project: %s", exc)

    app = FastAPI(
        title="Document Tree",
        version="0.1.0",
    )
    app.state.project_registry = registry
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects_router, prefix=resolved_settings.api_prefix)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
