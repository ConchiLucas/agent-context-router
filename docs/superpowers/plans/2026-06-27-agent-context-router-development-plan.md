# Agent Context Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first system that helps AI coding agents retrieve only the project documents needed for a task, while recording the retrieval and read chain so humans can optimize documentation routing.

**Architecture:** Use a Python backend as the source of truth for projects, documents, retrieval, and traces. Expose the same core capability through HTTP API, a `ctx` CLI, and later an MCP server. Use a TypeScript/Next.js frontend for project management, document inspection, and trace review.

**Tech Stack:** Python 3.12, FastAPI, Typer, PostgreSQL, SQLAlchemy 2.x, Alembic, pytest, Ruff, Next.js, TypeScript, Tailwind CSS, shadcn/ui-style primitives, Playwright.

---

## 1. Product Positioning

This is not a generic knowledge base. The product is an **AI context router** for software projects.

It should answer three questions:

1. Given a project and task, which documents should the AI read first?
2. Why were those documents selected?
3. Did the AI read useful documents, miss necessary documents, or read unnecessary documents?

The MVP should optimize for repeatable local use by one developer across multiple projects. Team collaboration, billing, SSO, cloud sync, and hosted deployment are out of scope for the first implementation.

## 2. Core Workflow

The intended flow for a new AI coding session:

1. The repo contains a short routing document such as `AI_CONTEXT_INDEX.md` or an `AGENTS.md` section.
2. The routing document tells the agent to call:

   ```bash
   ctx prepare --project <project-slug> --task "<user task>"
   ```

3. The CLI calls the backend API and prints a compact Markdown context package.
4. The package includes selected documents, reasons, confidence, trace ID, excerpts, and optional follow-up commands.
5. If the agent needs a full document later, it calls:

   ```bash
   ctx read <doc-id> --reason "<why this is needed>"
   ```

6. The backend records all retrieval and read events.
7. The user opens the frontend trace view to see what happened and tune the project routing/index documents.

## 3. MVP Scope

### Must Have

- Manage multiple projects by slug, name, root path, and description.
- Ingest Markdown documents and classify them by project, area, type, path, and tags.
- Store full Markdown documents for deterministic retrieval.
- Provide `ctx prepare` to return a task-specific context package.
- Provide `ctx read` to fetch a full document.
- Record trace events for prepare/read calls.
- Provide a frontend trace page showing selected docs, reasons, scores, and read history.
- Provide a project document inventory page.
- Provide a minimal routing document template for each project.

### Should Have

- Deterministic retrieval: keyword scoring plus metadata filtering.
- Document usefulness feedback: useful, unnecessary, missing, stale.
- Suggested changes to `AI_CONTEXT_INDEX.md` or `AGENTS.md` based on trace review.
- CLI output modes: Markdown for agents, JSON for debugging.

### Not In MVP

- Multi-user auth.
- Cloud-hosted sync.
- Browser extensions.
- IDE extensions.
- Automatic codebase crawling beyond explicitly configured docs.
- Fine-grained permissions per document.
- Fully automatic documentation rewriting.

## 4. Repository Layout

Create the project at:

```text
/Users/conchi/workforce/python_workforce/agent-context-router/
```

Initial structure:

```text
agent-context-router/
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── src/
│   │   └── context_router/
│   │       ├── __init__.py
│   │       ├── main.py
│   │       ├── config.py
│   │       ├── cli.py
│   │       ├── mcp_server.py
│   │       ├── api/
│   │       │   ├── __init__.py
│   │       │   ├── projects.py
│   │       │   ├── documents.py
│   │       │   ├── context.py
│   │       │   └── traces.py
│   │       ├── db/
│   │       │   ├── __init__.py
│   │       │   ├── session.py
│   │       │   └── models.py
│   │       ├── schemas/
│   │       │   ├── __init__.py
│   │       │   ├── projects.py
│   │       │   ├── documents.py
│   │       │   ├── context.py
│   │       │   └── traces.py
│   │       └── services/
│   │           ├── __init__.py
│   │           ├── document_store.py
│   │           ├── retrieval.py
│   │           ├── rendering.py
│   │           └── tracing.py
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_retrieval.py
│   │   ├── test_prepare_context.py
│   │   └── test_cli.py
│   └── alembic/
│       ├── env.py
│       └── versions/
├── frontend/
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── projects/
│   │   │   ├── page.tsx
│   │   │   └── [slug]/page.tsx
│   │   ├── documents/page.tsx
│   │   └── traces/
│   │       ├── page.tsx
│   │       └── [traceId]/page.tsx
│   ├── components/
│   │   ├── app-shell.tsx
│   │   ├── document-table.tsx
│   │   ├── trace-timeline.tsx
│   │   └── retrieval-hit-list.tsx
│   └── lib/
│       ├── api.ts
│       └── types.ts
├── docs/
│   ├── AI_CONTEXT_INDEX.template.md
│   └── superpowers/
│       └── plans/
│           └── 2026-06-27-agent-context-router-development-plan.md
├── docker-compose.yml
├── Makefile
└── README.md
```

## 5. Data Model

### Project

- `id`: UUID
- `slug`: unique text used by CLI
- `name`: display name
- `root_path`: optional local repository path
- `description`: short text
- `created_at`, `updated_at`

### Document

- `id`: stable text ID such as `payments-webhook-timeout-history`
- `project_id`: FK
- `title`
- `source_path`
- `doc_type`: one of `agent_index`, `architecture`, `debugging`, `bug_record`, `pitfall`, `test_command`, `runbook`, `api_contract`, `decision`
- `area`: optional domain such as `payments`, `frontend`, `build`, `auth`
- `tags`: text array
- `status`: `active`, `stale`, `archived`
- `content_markdown`
- `created_at`, `updated_at`

### Trace

- `id`: text ID returned to CLI, such as `ctx_20260627_001`
- `project_id`: FK
- `task`
- `cwd`
- `agent_name`: optional, for future Codex/Claude/Cursor detection
- `created_at`

### TraceEvent

- `id`: UUID
- `trace_id`: FK
- `event_type`: `prepare`, `read`, `feedback`, `error`
- `payload`: JSON object
- `created_at`

### RetrievalHit

- `id`: UUID
- `trace_id`: FK
- `document_id`: FK
- `rank`
- `score`
- `reason`
- `was_returned`: boolean
- `feedback`: nullable `useful`, `unnecessary`, `missing`, `stale`

## 6. API Contract

### `POST /api/projects`

Create a project.

Request:

```json
{
  "slug": "my-app",
  "name": "My App",
  "root_path": "/path/to/repo",
  "description": "Main product application"
}
```

Response:

```json
{
  "id": "uuid",
  "slug": "my-app",
  "name": "My App"
}
```

### `POST /api/projects/{slug}/documents`

Create or update a document.

Request:

```json
{
  "id": "payments-webhook-timeout-history",
  "title": "Payments webhook timeout history",
  "source_path": "docs/debugging/payments-webhook-timeout.md",
  "doc_type": "debugging",
  "area": "payments",
  "tags": ["webhook", "timeout", "payments"],
  "content_markdown": "# Payments webhook timeout history\n..."
}
```

Response:

```json
{
  "id": "payments-webhook-timeout-history",
  "status": "active"
}
```

### `POST /api/context/prepare`

Return the context package for a task.

Request:

```json
{
  "project": "my-app",
  "task": "修复支付 webhook timeout",
  "cwd": "/path/to/repo",
  "max_documents": 5,
  "output_format": "markdown"
}
```

Response:

```json
{
  "trace_id": "ctx_20260627_001",
  "project": "my-app",
  "task": "修复支付 webhook timeout",
  "documents": [
    {
      "document_id": "payments-webhook-timeout-history",
      "title": "Payments webhook timeout history",
      "reason": "The task mentions payments, webhook, and timeout, which match this debugging history.",
      "score": 0.91,
      "excerpt": "Past timeout fixes required checking retry headers..."
    }
  ],
  "markdown": "trace_id: ctx_20260627_001\n\n## Required Context\n..."
}
```

### `GET /api/documents/{document_id}`

Return a full document and record a read event when a `trace_id` query parameter is present.

### `GET /api/traces/{trace_id}`

Return trace details, retrieval hits, read events, and feedback.

### `POST /api/traces/{trace_id}/feedback`

Record human feedback on returned documents.

Request:

```json
{
  "document_id": "payments-webhook-timeout-history",
  "feedback": "useful",
  "note": "This was the exact historical issue."
}
```

## 7. CLI Contract

Install command name: `ctx`.

### `ctx project add`

Create a project from the terminal.

```bash
ctx project add --slug my-app --name "My App" --root-path /path/to/repo
```

### `ctx doc add`

Add or update a Markdown document.

```bash
ctx doc add --project my-app --id payments-webhook-timeout-history --type debugging --area payments docs/debugging/payments-webhook-timeout.md
```

### `ctx prepare`

Main command for AI agents.

```bash
ctx prepare --project my-app --task "修复支付 webhook timeout"
```

Default output is Markdown. It must include:

- `trace_id`
- selected documents
- reasons
- short excerpts
- read commands for follow-up
- trace URL

### `ctx read`

Read a specific document and record why it was read.

```bash
ctx read payments-webhook-timeout-history --trace ctx_20260627_001 --reason "Need full historical fix details"
```

### `ctx trace`

Show a trace summary.

```bash
ctx trace ctx_20260627_001
```

## 8. MCP Contract

MCP is a second-phase entry point, after the CLI flow is validated.

Expose two tools:

### `prepare_task_context`

Input:

```json
{
  "project": "my-app",
  "task": "修复支付 webhook timeout",
  "cwd": "/path/to/repo"
}
```

Output: same structured package as `/api/context/prepare`.

### `read_context_document`

Input:

```json
{
  "document_id": "payments-webhook-timeout-history",
  "trace_id": "ctx_20260627_001",
  "reason": "Need full historical fix details"
}
```

Output: document title, metadata, content, and trace event ID.

## 9. Frontend Screens

### Dashboard

Purpose: show projects, recent traces, and retrieval health.

Metrics:

- Projects count
- Active documents count
- Recent prepare calls
- Documents marked unnecessary
- Documents marked missing

### Project Detail

Purpose: inspect project setup and docs.

Sections:

- Project metadata
- Suggested `AI_CONTEXT_INDEX.md`
- Document inventory
- Area/type/tag filters

### Documents

Purpose: browse and maintain docs.

Table columns:

- ID
- Title
- Project
- Area
- Type
- Tags
- Status
- Updated time

### Trace Detail

Purpose: inspect one AI retrieval chain.

Sections:

- Task and trace metadata
- Documents returned by `ctx prepare`
- Reasons and scores
- `ctx read` calls
- Human feedback controls
- Suggested documentation/routing improvements

## 10. Routing Document Template

Every project should get a generated `AI_CONTEXT_INDEX.md`:

```md
# AI Context Index

This file is for AI coding agents. Keep it short. Do not put full project knowledge here.

## First step for any task

Run:

```bash
ctx prepare --project <project-slug> --task "<copy the user's task>"
```

Use the returned `trace_id` for any follow-up reads.

## Read a specific document only when needed

Run:

```bash
ctx read <doc-id> --trace <trace-id> --reason "<why this document is needed>"
```

## Rules

- Do not read large docs manually before running `ctx prepare`.
- Prefer the documents returned by `ctx prepare`.
- If a needed document is missing, mention that in the final response so the human can update the context router.
```

## 11. Implementation Tasks

### Task 1: Create Monorepo Skeleton

**Files:**

- Create: `backend/pyproject.toml`
- Create: `backend/src/context_router/__init__.py`
- Create: `backend/src/context_router/main.py`
- Create: `frontend/package.json`
- Create: `README.md`
- Create: `docker-compose.yml`
- Create: `Makefile`

- [ ] Create the directory structure.
- [ ] Add Python package metadata and dependencies.
- [ ] Add FastAPI health endpoint.
- [ ] Add frontend package metadata.
- [ ] Add Docker Compose with PostgreSQL.
- [ ] Add Make targets for backend test, backend lint, frontend dev, and all checks.

### Task 2: Add Database Models and Migrations

**Files:**

- Create: `backend/src/context_router/db/session.py`
- Create: `backend/src/context_router/db/models.py`
- Create: `backend/alembic/env.py`
- Create: first Alembic migration under `backend/alembic/versions/`
- Test: `backend/tests/test_models.py`

- [ ] Write database models for projects, documents, traces, events, and retrieval hits.
- [ ] Add Alembic migration.
- [ ] Add tests that create a project, document, trace, and retrieval hit.
- [ ] Run `pytest backend/tests/test_models.py -v`.

### Task 3: Implement Document Ingestion

**Files:**

- Create: `backend/src/context_router/services/document_store.py`
- Create: `backend/src/context_router/api/documents.py`
- Test: `backend/tests/test_document_ingestion.py`

- [ ] Store Markdown documents with source metadata.
- [ ] Add create/update document API.
- [ ] Replace document content when content changes.
- [ ] Add tests for create/update behavior.

### Task 4: Implement Prepare Context Retrieval

**Files:**

- Create: `backend/src/context_router/services/retrieval.py`
- Create: `backend/src/context_router/services/rendering.py`
- Create: `backend/src/context_router/api/context.py`
- Test: `backend/tests/test_retrieval.py`
- Test: `backend/tests/test_prepare_context.py`

- [ ] Implement metadata scoring for area, tags, doc type, and title matches.
- [ ] Implement keyword scoring for task text against full document content.
- [ ] Keep ranking local and deterministic so MVP works without external API keys.
- [ ] Combine scores into ranked document results.
- [ ] Render a compact Markdown context package.
- [ ] Add tests that prove unrelated documents are not returned when a better match exists.

### Task 5: Implement Trace Recording

**Files:**

- Create: `backend/src/context_router/services/tracing.py`
- Create: `backend/src/context_router/api/traces.py`
- Test: `backend/tests/test_tracing.py`

- [ ] Create trace rows for every prepare call.
- [ ] Record retrieval hits and reasons.
- [ ] Record read events with human or agent-supplied reasons.
- [ ] Add feedback endpoint for useful/unnecessary/missing/stale.
- [ ] Add tests for full prepare-read-feedback lifecycle.

### Task 6: Implement CLI

**Files:**

- Create: `backend/src/context_router/cli.py`
- Test: `backend/tests/test_cli.py`

- [ ] Add `ctx project add`.
- [ ] Add `ctx doc add`.
- [ ] Add `ctx prepare`.
- [ ] Add `ctx read`.
- [ ] Add `ctx trace`.
- [ ] Make Markdown output the default for `ctx prepare`.
- [ ] Add `--json` output for debugging and future automation.

### Task 7: Implement Frontend Shell

**Files:**

- Create: `frontend/app/layout.tsx`
- Create: `frontend/app/page.tsx`
- Create: `frontend/components/app-shell.tsx`
- Create: `frontend/lib/api.ts`
- Create: `frontend/lib/types.ts`

- [ ] Add a quiet operational layout with sidebar navigation.
- [ ] Add dashboard cards for projects, docs, traces, and feedback counts.
- [ ] Add API client functions.
- [ ] Add loading and empty states.

### Task 8: Implement Project and Document UI

**Files:**

- Create: `frontend/app/projects/page.tsx`
- Create: `frontend/app/projects/[slug]/page.tsx`
- Create: `frontend/app/documents/page.tsx`
- Create: `frontend/components/document-table.tsx`

- [ ] List projects.
- [ ] Show project detail and generated routing document template.
- [ ] List documents with filters for project, area, type, tag, and status.
- [ ] Show document metadata.

### Task 9: Implement Trace UI

**Files:**

- Create: `frontend/app/traces/page.tsx`
- Create: `frontend/app/traces/[traceId]/page.tsx`
- Create: `frontend/components/trace-timeline.tsx`
- Create: `frontend/components/retrieval-hit-list.tsx`

- [ ] List traces by recent activity.
- [ ] Show trace task, returned documents, reasons, scores, and read events.
- [ ] Add feedback controls for each retrieval hit.
- [ ] Add a section for suggested routing/documentation improvements.

### Task 10: Add MCP Server

**Files:**

- Create: `backend/src/context_router/mcp_server.py`
- Test: `backend/tests/test_mcp_server.py`

- [ ] Expose `prepare_task_context`.
- [ ] Expose `read_context_document`.
- [ ] Reuse the same backend services as the API and CLI.
- [ ] Document Codex MCP configuration in `README.md`.

### Task 11: Add Verification and Sample Project

**Files:**

- Create: `docs/AI_CONTEXT_INDEX.template.md`
- Create: `backend/tests/fixtures/sample_docs/`
- Modify: `README.md`

- [ ] Add sample docs for payments, build, frontend, and unrelated areas.
- [ ] Add an end-to-end test: ingest docs, prepare context, read doc, view trace.
- [ ] Add README quickstart.
- [ ] Add local verification commands.

## 12. Testing Strategy

Backend:

```bash
cd backend
pytest -v
ruff check .
ruff format --check .
```

Frontend:

```bash
cd frontend
npm run lint
npm run test
npm run build
```

End-to-end:

```bash
make test
make lint
make build
```

Retrieval quality checks:

- A payments task should return payments docs before frontend docs.
- A build failure task should return test/build command docs.
- A generic feature task should return architecture and routing docs, not historical bug docs.
- A direct `ctx read` must require a reason and record it in the trace.

## 13. Design Risks

### Risk: CLI-only flow becomes too shell-dependent

Mitigation: Keep core logic behind HTTP API. CLI is a wrapper, not the source of truth.

### Risk: AI reads too many documents anyway

Mitigation: Make `ctx prepare` return a compact package and explicit follow-up read commands. Record every `ctx read` reason.

### Risk: The index document becomes huge

Mitigation: Treat `AI_CONTEXT_INDEX.md` as a routing file only. Full knowledge lives in managed documents.

### Risk: Retrieval quality is hard to judge

Mitigation: Add human feedback and trace review from day one. Optimize against concrete traces, not abstract search quality.

### Risk: Ranking complexity blocks MVP

Mitigation: Use metadata and keyword ranking with clear scoring heuristics.

## 14. Recommended Build Order

1. Backend skeleton, models, and migrations.
2. Document ingestion.
3. `ctx prepare` with deterministic metadata + keyword retrieval.
4. Trace recording.
5. `ctx read`.
6. Frontend trace review page.
7. Project/document management UI.
8. Advanced local ranking heuristics.
9. MCP server.
10. Documentation improvement suggestions.

This order gets to the core proof quickly: can the system reduce AI context wandering and make the retrieval chain visible?
