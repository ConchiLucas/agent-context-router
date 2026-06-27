# Agent Context Router

Agent Context Router helps AI coding agents retrieve project-specific context through a
small CLI/API surface while recording which documents were selected, read, and reviewed.

## Planned MVP

- Python FastAPI backend for projects, documents, retrieval, and traces.
- `ctx` CLI for AI agents and humans.
- PostgreSQL storage with deterministic metadata and keyword retrieval.
- Next.js dashboard for trace review and document inventory.

## Local Development

The backend defaults to the local PostgreSQL convention used by the other
workforce projects:

```text
host: 127.0.0.1
port: 5432
database: context_router
user: conchi
password: conchi123456
```

Create and migrate the database before starting the API:

```bash
cd backend
uv run alembic upgrade head
```

Run the API:

```bash
cd backend
uv run uvicorn context_router.main:create_app --factory --host 127.0.0.1 --port 8000
```

Run the dashboard:

```bash
cd frontend
npm install
npm run dev
```

## CLI Flow

```bash
cd backend
uv run ctx project add --slug my-app --name "My App" --root-path /path/to/repo
uv run ctx doc add --project my-app --id payments-runbook --type runbook docs/payments.md
uv run ctx prepare --project my-app --task "fix payments webhook timeout"
uv run ctx read payments-runbook --trace <trace-id> --reason "Need full runbook"
uv run ctx trace <trace-id>
```

Set `CTX_API_URL` when the API is not on `http://127.0.0.1:8000`.

Override `CONTEXT_ROUTER_DATABASE_URL` only when using another PostgreSQL
database, such as the optional docker-compose database on port `54329`:

```bash
export CONTEXT_ROUTER_DATABASE_URL=postgresql+psycopg://context_router:context_router@127.0.0.1:54329/context_router
```

## Codex MCP Configuration

The MCP server is a lightweight stdio wrapper over the same HTTP API used by the CLI.
Start the backend first, then register this command with Codex:

```json
{
  "mcpServers": {
    "agent-context-router": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/Users/conchi/workforce/python_workforce/agent-context-router/backend",
        "context-router-mcp"
      ],
      "env": {
        "CTX_API_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

Exposed tools:

- `prepare_task_context`: returns the same context package as `ctx prepare`.
- `read_context_document`: reads a document and records the read reason on the trace.

## Verification

```bash
make backend-test
make backend-lint
cd frontend && npm run lint && npm run build
```
