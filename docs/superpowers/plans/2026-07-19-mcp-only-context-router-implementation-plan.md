# MCP-only Context Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every product-facing `ctx` workflow with two stateless MCP tools and a Tasks list/detail web experience while preserving the FastAPI document index and trace backend.

**Architecture:** The stdio MCP wrapper remains a thin HTTP client, but all task identity becomes explicit through `trace_id`; FastAPI resolves projects from cwd, owns depth/parent validation, and records objective timing. The frontend continues to consume trace APIs but presents them as MCP Tasks and removes CLI, Usage, and feedback surfaces.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pytest, Next.js 15, React 19, TypeScript, Docker Compose.

---

## File structure and responsibilities

- `backend/src/context_router/mcp_server.py`: define the two public MCP tools and translate tool calls to HTTP without process-global task state.
- `backend/src/context_router/api/context.py`: resolve a project, run retrieval, create the task trace, and record prepare timing.
- `backend/src/context_router/api/documents.py`: enforce explicit trace reads, validate parent reads, derive depth, and record read timing.
- `backend/src/context_router/api/traces.py`: expose objective MCP task summaries/details without feedback mutation.
- `backend/src/context_router/schemas/context.py`, `documents.py`, `traces.py`: define the revised contracts.
- `backend/src/context_router/services/project_resolution.py`: normalize cwd and resolve the most specific registered project.
- `frontend/components/task-list.tsx`: render the outer MCP task list.
- `frontend/components/task-detail.tsx`: render a task's MCP timeline and candidate read state.
- `frontend/app/tasks/*`: own the two-level task routes.
- `frontend/components/project-form.tsx`: replace `ctx project add` with a web form.
- `frontend/components/app-shell.tsx`, `frontend/app/page.tsx`: remove Usage/CLI/feedback surfaces and link Tasks.
- Current docs: describe only MCP, web sync, and short AGENTS guidance.
- Historical migrations and the original dated development plan remain unchanged.

### Task 1: Stateless MCP contract

**Files:**
- Modify: `backend/tests/test_mcp_server.py`
- Modify: `backend/src/context_router/mcp_server.py`

- [ ] **Step 1: Write failing tool-schema and request tests**

Replace global-state assertions with tests that require `task` and `cwd`, keep `project` optional, fix the candidate count at three, and require `trace_id` on read:

```python
def test_mcp_prepare_uses_minimal_task_contract(monkeypatch) -> None:
    requests = []
    monkeypatch.setattr(mcp_server, "_request_json", _fake_prepare(requests))

    response = mcp_server.handle_request(_tool_call("prepare_task_context", {
        "task": "fix login timeout",
        "cwd": "/repo/my-app",
        "agent_name": "codex",
    }))

    assert requests[0][2] == {
        "project": None,
        "task": "fix login timeout",
        "cwd": "/repo/my-app",
        "source": "mcp",
        "agent_name": "codex",
        "max_documents": 3,
        "output_format": "json",
    }
    assert json.loads(response["result"]["content"][0]["text"])["trace_id"] == "ctx_001"


def test_mcp_read_forwards_explicit_trace_and_parent(monkeypatch) -> None:
    requests = []
    monkeypatch.setattr(mcp_server, "_request_json", _fake_read(requests))

    mcp_server.handle_request(_tool_call("read_context_document", {
        "trace_id": "ctx_002",
        "document_id": "auth-debugging",
        "parent_document_id": "auth-guide",
    }))

    assert requests[0][3] == {
        "trace_id": "ctx_002",
        "parent_document_id": "auth-guide",
        "source": "mcp",
    }
```

- [ ] **Step 2: Run the MCP tests and verify RED**

Run:

```bash
docker compose run --rm backend uv run --extra dev pytest -q tests/test_mcp_server.py
```

Expected: failures show the old schema requires project, read lacks trace_id, and globals are still used.

- [ ] **Step 3: Implement the minimal stateless wrapper**

Set schemas to:

```python
{
    "name": "prepare_task_context",
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "minLength": 1},
            "cwd": {"type": "string", "minLength": 1},
            "project": {"type": "string"},
            "agent_name": {"type": "string"},
        },
        "required": ["task", "cwd"],
    },
}
```

and:

```python
{
    "name": "read_context_document",
    "inputSchema": {
        "type": "object",
        "properties": {
            "trace_id": {"type": "string", "minLength": 1},
            "document_id": {"type": "string", "minLength": 1},
            "parent_document_id": {"type": "string"},
        },
        "required": ["trace_id", "document_id"],
    },
}
```

Return compact JSON text from both tools and remove all `CURRENT_*` declarations and mutations.

- [ ] **Step 4: Run MCP tests and verify GREEN**

Run the same pytest command. Expected: all MCP tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/context_router/mcp_server.py backend/tests/test_mcp_server.py
git commit -m "feat: make MCP task tools stateless"
```

### Task 2: Project resolution and prepare contract

**Files:**
- Create: `backend/src/context_router/services/project_resolution.py`
- Create: `backend/tests/test_project_resolution.py`
- Modify: `backend/src/context_router/schemas/context.py`
- Modify: `backend/src/context_router/api/context.py`
- Modify: `backend/tests/test_prepare_context.py`

- [ ] **Step 1: Write failing project-resolution tests**

```python
def test_resolve_project_prefers_longest_root_path(session) -> None:
    workspace = Project(slug="workspace", name="Workspace", root_path="/repo")
    app = Project(slug="app", name="App", root_path="/repo/apps/app")
    session.add_all([workspace, app])
    session.commit()

    assert resolve_project(session, cwd="/repo/apps/app/src", project_slug=None).slug == "app"


def test_resolve_project_rejects_unknown_cwd(session) -> None:
    session.add(Project(slug="app", name="App", root_path="/repo/app"))
    session.commit()

    with pytest.raises(ProjectResolutionError, match="No registered project"):
        resolve_project(session, cwd="/other/repo", project_slug=None)
```

Add API tests asserting empty task is 422, cwd-only selection works, and returned documents never exceed three.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
docker compose run --rm backend uv run --extra dev pytest -q tests/test_project_resolution.py tests/test_prepare_context.py
```

Expected: resolver import fails and the current request still requires project/allows blank task.

- [ ] **Step 3: Implement resolver and schema**

Create:

```python
class ProjectResolutionError(ValueError):
    pass


def resolve_project(session: Session, *, cwd: str, project_slug: str | None) -> Project:
    if project_slug:
        project = session.scalar(select(Project).where(Project.slug == project_slug))
        if project is None:
            raise ProjectResolutionError(f"Project not found: {project_slug}")
        return project

    normalized_cwd = _normalized_path(cwd)
    projects = session.scalars(select(Project).where(Project.root_path.is_not(None))).all()
    matches = [project for project in projects if _is_within(normalized_cwd, project.root_path)]
    if not matches:
        raise ProjectResolutionError(f"No registered project matches cwd: {cwd}")
    return max(matches, key=lambda project: len(_normalized_path(project.root_path or "")))
```

Make `task` and `cwd` non-empty required fields, `project` optional, and clamp the internal candidate limit to three in the API.

- [ ] **Step 4: Record prepare processing time**

Use `time.perf_counter()` around retrieval and include `duration_ms` in the prepare event payload. Do not ask the Agent for timing data.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the same focused pytest command. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/context_router/services/project_resolution.py backend/src/context_router/schemas/context.py backend/src/context_router/api/context.py backend/tests/test_project_resolution.py backend/tests/test_prepare_context.py
git commit -m "feat: resolve MCP projects from cwd"
```

### Task 3: Explicit trace document reads

**Files:**
- Modify: `backend/src/context_router/api/documents.py`
- Modify: `backend/src/context_router/schemas/documents.py`
- Modify: `backend/tests/test_document_read.py`
- Modify: `backend/tests/test_e2e_flow.py`

- [ ] **Step 1: Write failing read validation tests**

Add tests for:

```python
def test_mcp_read_requires_existing_trace(client) -> None:
    response = client.get("/api/documents/auth-guide", params={"source": "mcp"})
    assert response.status_code == 422


def test_read_derives_depth_from_explicit_parent(client, prepared_trace) -> None:
    trace_id = prepared_trace
    client.get("/api/documents/root", params={"trace_id": trace_id, "source": "mcp"})
    response = client.get("/api/documents/child", params={
        "trace_id": trace_id,
        "parent_document_id": "root",
        "source": "mcp",
    })
    assert response.status_code == 200
    detail = client.get(f"/api/traces/{trace_id}").json()
    assert detail["events"][-1]["payload"]["depth"] == 2


def test_read_rejects_parent_not_read_in_same_trace(client, prepared_trace) -> None:
    response = client.get("/api/documents/child", params={
        "trace_id": prepared_trace,
        "parent_document_id": "root",
        "source": "mcp",
    })
    assert response.status_code == 422
```

- [ ] **Step 2: Run document tests and verify RED**

```bash
docker compose run --rm backend uv run --extra dev pytest -q tests/test_document_read.py tests/test_e2e_flow.py
```

Expected: MCP reads still create direct traces and accept caller-supplied depth/invalid parents.

- [ ] **Step 3: Implement explicit trace reads**

- Require `trace_id` when `source=mcp`.
- Keep `untracked=true` for frontend document previews.
- Resolve the Trace or return 404; never auto-create a Trace for MCP.
- When parent is absent, set depth 1.
- When parent is present, locate its latest read event in the same Trace and set depth to `parent_depth + 1`; return 422 if missing.
- Measure local read and event persistence time and store `duration_ms`.
- Remove public `depth` and `reason` query parameters.

- [ ] **Step 4: Run document tests and verify GREEN**

Run the same focused command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/context_router/api/documents.py backend/src/context_router/schemas/documents.py backend/tests/test_document_read.py backend/tests/test_e2e_flow.py
git commit -m "feat: bind document reads to explicit traces"
```

### Task 4: Objective Tasks API and remove feedback runtime

**Files:**
- Modify: `backend/src/context_router/api/traces.py`
- Modify: `backend/src/context_router/schemas/traces.py`
- Modify: `backend/tests/test_tracing.py`
- Modify: `backend/src/context_router/main.py`
- Delete: `backend/src/context_router/api/usage.py`
- Delete: `backend/src/context_router/schemas/usage.py`
- Delete: `backend/tests/test_usage_cards.py`

- [ ] **Step 1: Write failing task summary/detail tests**

Change trace lifecycle tests to `source="mcp"`, remove feedback calls, and assert:

```python
assert task["agent_name"] == "codex"
assert task["mcp_duration_ms"] >= 0
assert "feedback_count" not in task
assert "feedback" not in detail["retrieval_hits"][0]
assert [event["event_type"] for event in detail["events"]] == ["prepare", "read"]
```

Add a test that `POST /api/traces/{trace_id}/feedback` returns 405 or 404 and `/api/usage/cards` returns 404.

- [ ] **Step 2: Run trace and usage tests and verify RED**

```bash
docker compose run --rm backend uv run --extra dev pytest -q tests/test_tracing.py tests/test_usage_cards.py
```

Expected: old feedback and Usage endpoints still exist; summary lacks agent/timing.

- [ ] **Step 3: Implement objective trace responses**

- Remove the feedback POST endpoint and feedback request/response schemas.
- Remove feedback from retrieval-hit response objects.
- Add `agent_name` and `mcp_duration_ms` to summaries.
- Compute `mcp_duration_ms` by summing numeric `duration_ms` values from prepare/read events.
- Stop registering Usage router and remove Usage runtime files/tests.
- Keep historical model columns and migrations untouched.

- [ ] **Step 4: Run backend suite and verify GREEN**

```bash
docker compose run --rm backend uv run --extra dev pytest -q
```

Expected: all retained backend tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/context_router backend/tests
git commit -m "feat: expose objective MCP task traces"
```

### Task 5: Two-level Tasks frontend

**Files:**
- Create: `frontend/components/task-list.tsx`
- Create: `frontend/components/task-detail.tsx`
- Create: `frontend/app/tasks/page.tsx`
- Create: `frontend/app/tasks/[traceId]/page.tsx`
- Modify: `frontend/components/app-shell.tsx`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/globals.css`
- Delete: `frontend/app/traces/page.tsx`
- Delete: `frontend/app/traces/[traceId]/page.tsx`
- Delete: `frontend/components/traces-view.tsx`
- Delete: `frontend/components/trace-timeline.tsx`
- Delete: `frontend/components/trace-flow.tsx`
- Delete: `frontend/components/feedback-controls.tsx`
- Delete: `frontend/app/usage/page.tsx`
- Delete: `frontend/components/usage-cards-view.tsx`
- Delete: `frontend/app/api/usage/cards/route.ts`
- Delete: `frontend/app/api/usage/cards/[slug]/route.ts`
- Delete: `frontend/components/cli-terminal.tsx`

- [ ] **Step 1: Add frontend component tests or pure derivation tests**

If no test runner exists, extract and test the objective derivation as TypeScript used by the components:

```typescript
export function readDocumentIds(trace: TraceDetail) {
  return new Set(
    trace.events
      .filter((event) => event.event_type === "read")
      .map((event) => String(event.payload.document_id))
  );
}
```

Add `frontend/lib/task-trace.test.ts` using Node's test runner and configure `npm test` if necessary. Assert returned-only and read states for a fixture trace.

- [ ] **Step 2: Run the frontend test and verify RED**

```bash
docker compose run --rm frontend sh -c "npm install && npm test"
```

Expected: missing task-trace module or test script.

- [ ] **Step 3: Implement list and detail routes**

- `/tasks` calls `getTraces({ source: "mcp" })` and renders task, project, Agent, candidates, reads, MCP duration, and time.
- Each row links to `/tasks/{traceId}`.
- Detail page renders a vertical timeline for prepare, returned candidates, and each read event.
- Candidate table derives read/unread from read events.
- Navigation label is Tasks; Usage is absent.
- Dashboard removes Feedback and CLI Entry and links recent tasks to `/tasks`.
- Remove old Traces/Usage components and routes.

- [ ] **Step 4: Run frontend tests, lint, and build**

```bash
docker compose run --rm frontend sh -c "npm install && npm test && npm run lint && npm run build"
```

Expected: test, lint, type checking, and build pass; generated routes include `/tasks` and `/tasks/[traceId]`, not `/traces` or `/usage`.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: add two-level MCP tasks UI"
```

### Task 6: Replace remaining CLI management surfaces

**Files:**
- Create: `frontend/components/project-form.tsx`
- Create: `frontend/app/api/projects/route.ts`
- Modify: `frontend/app/projects/page.tsx`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/components/document-detail-content.tsx`
- Modify: `frontend/components/document-graph.tsx`
- Modify: `backend/pyproject.toml`
- Delete: `backend/src/context_router/cli.py`
- Delete: `backend/tests/test_cli.py`
- Delete: `bin/ctx`

- [ ] **Step 1: Write failing project API test**

Extend project tests to assert the existing POST API accepts the fields the web form will send and returns the project. Add a frontend test for the project draft validator:

```typescript
assert.deepEqual(validateProjectDraft({ slug: "", name: "", root_path: "" }), {
  slug: "Project slug is required",
  name: "Project name is required",
  root_path: "Root path is required",
});
```

- [ ] **Step 2: Run focused tests and verify RED**

Run backend project tests and frontend tests. Expected: frontend validator/form module is missing.

- [ ] **Step 3: Implement web project creation and remove CLI**

- Add a project form with slug, name, root path, description, and optional parent slug.
- Proxy POST through the Next route to the internal FastAPI project endpoint.
- Refresh the Projects page after creation.
- Rename `Reload Links` to `Sync Documents` while retaining the existing API.
- Remove command blocks from document detail and graph cards; show document IDs and links instead.
- Delete CLI files/tests and remove only the `ctx` script/dependency (`typer`) from pyproject; retain `context-router-mcp`.

- [ ] **Step 4: Run focused and full tests**

Run backend pytest plus frontend test/lint/build. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend frontend bin
git commit -m "refactor: remove ctx product entry points"
```

### Task 7: Rewrite current documentation and final verification

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/DEVELOPMENT_OUTLINE.md`
- Modify: `docs/BUSINESS_FEATURES.md`
- Modify: `docs/FRONTEND_BACKEND_FLOW.md`
- Modify: `docs/AI_CONTEXT_INDEX.template.md`
- Modify: `docs/STARTUP_GUIDE.md`
- Modify: `docs/managed/*.md`
- Modify: `docs/development-details/CODE_CHANGE_LOG.md`

- [ ] **Step 1: Write the current MCP-only operating docs**

README must contain:

```markdown
## Agent workflow

Context Router exposes two MCP tools:

- `prepare_task_context(task, cwd, project?, agent_name?)`
- `read_context_document(trace_id, document_id, parent_document_id?)`

Agents may skip Context Router when stable project context is unnecessary.
No CLI session, shell variable, or finish call is required.
```

Add the approved short Context Router rule to this repository's AGENTS.md and rewrite managed documents to refer to MCP tool names and Markdown links instead of shell commands.

- [ ] **Step 2: Scan current runtime/docs for removed protocol**

```bash
rg -n 'ctx (prepare|read|reset|trace|doc|project)|CTX_SESSION_ID|CTX_STATE_|SESSION_ID|CLI Entry|/usage|FeedbackControls' \
  README.md AGENTS.md backend frontend docs \
  -g '!docs/superpowers/plans/2026-06-27-agent-context-router-development-plan.md' \
  -g '!docs/superpowers/specs/2026-07-19-mcp-only-context-router-design.md' \
  -g '!docs/superpowers/plans/2026-07-19-mcp-only-context-router-implementation-plan.md'
```

Expected: no matches in current runtime or current operating docs. Historical dated plan/spec references are intentionally excluded.

- [ ] **Step 3: Run complete verification**

```bash
docker compose run --rm backend uv run --extra dev pytest -q
docker compose run --rm backend uv run --extra dev ruff check .
docker compose run --rm backend uv run --extra dev ruff format --check .
docker compose run --rm frontend sh -c "npm install && npm test && npm run lint && npm run build"
```

Expected: every command exits 0.

- [ ] **Step 4: Inspect final diff and behavior coverage**

```bash
git diff --check
git status --short
git log --oneline --decorate -8
```

Confirm the implementation satisfies every acceptance criterion in `docs/superpowers/specs/2026-07-19-mcp-only-context-router-design.md` and does not include local planning/prototype artifacts.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md AGENTS.md docs
git commit -m "docs: document MCP-only context workflow"
```
