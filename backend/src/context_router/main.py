from fastapi import FastAPI

from context_router.api.context import router as context_router
from context_router.api.document_mappings import router as document_mappings_router
from context_router.api.documents import read_router as document_read_router
from context_router.api.documents import router as documents_router
from context_router.api.projects import router as projects_router
from context_router.api.traces import router as traces_router
from context_router.db.session import ensure_sqlite_schema


def create_app() -> FastAPI:
    ensure_sqlite_schema()
    app = FastAPI(title="Agent Context Router")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "service": "agent-context-router",
            "status": "ok",
        }

    app.include_router(projects_router)
    app.include_router(document_mappings_router)
    app.include_router(context_router)
    app.include_router(documents_router)
    app.include_router(document_read_router)
    app.include_router(traces_router)
    return app


app = create_app()
