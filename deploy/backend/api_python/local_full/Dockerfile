FROM ghcr.io/astral-sh/uv:python3.12-bookworm

WORKDIR /app/backend

COPY README.md /app/README.md
COPY backend/ /app/backend/

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["/bin/sh", "-c", "uv run --no-sync alembic upgrade head && exec uv run --no-sync uvicorn context_router.main:create_app --factory --host 0.0.0.0 --port 8000"]
