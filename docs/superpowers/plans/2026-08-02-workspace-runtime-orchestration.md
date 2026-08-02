# Workspace Runtime Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Workspace-level MCP orchestration and a manually started macOS Host Runner so Codex can update changed Projects or start every service in a registered Workspace while target `.env.local` values remain outside Context Router.

**Architecture:** Context Router remains the control plane: it validates task scope and changed paths, materializes registered Runtime files, creates a parent operation with ordered steps, and exposes lease/heartbeat/completion APIs. A stdlib-only Host Runner polls those APIs over loopback, validates immutable manifests, executes only snapshot `deploy.sh`, and writes bounded logs into the existing shared runtime directory. Existing project tools remain compatibility adapters over the new orchestration service.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, psycopg/PostgreSQL, Alembic, FastMCP, Docker Compose, stdlib Host Runner, pytest, Ruff, mypy, Next.js read-only views.

---

## File map

- Create `backend/migrations/versions/20260802_0023_add_workspace_runtime_orchestration.py`: Workspace runtime configuration, policies, parent operations, steps, and Runner instances.
- Create `backend/src/context_router/repositories/workspace_runtime_repository.py`: in-memory/PostgreSQL stores for Workspace runtime files and policies.
- Create `backend/src/context_router/repositories/runtime_operation_repository.py`: atomic operation, step, lease, heartbeat, and completion persistence.
- Create `backend/src/context_router/schemas/workspace_runtime.py`: management API, MCP payload, Runner protocol, and operation response models.
- Create `backend/src/context_router/services/workspace_runtime_orchestration.py`: changed-path routing, mode selection, snapshot planning, concurrency, and aggregate status.
- Modify `backend/src/context_router/services/runtime_materialization.py`: generalize immutable snapshots to Project and Workspace owners.
- Create `backend/src/context_router/api/workspace_runtime.py`: local AI/ops runtime configuration and read-only operation endpoints.
- Create `backend/src/context_router/api/runtime_runner.py`: token-authenticated register/heartbeat/lease/start/complete endpoints.
- Create `scripts/context_router_host_runner.py`: stdlib-only Host Runner.
- Create `scripts/start-local-stack.sh`, `scripts/stop-local-stack.sh`, `scripts/status-local-stack.sh`: manual lifecycle entrypoints.
- Modify `backend/src/context_router/mcp_server.py`, `mcp_contract.py`, trace repositories/services and integration metadata: expose and trace the three Workspace tools while adapting old project tools.
- Modify `backend/src/context_router/main.py`, `config.py`, and `docker-compose.yml`: wire repositories/services/API and shared Runner settings.
- Modify target Workspace `AGENTS.md` and `docs/shared/runtime-deployment-map.md`: declare the final Agent workflow.
- Add focused tests under `backend/tests/` and shell/Runner tests under `backend/tests/test_host_runtime_runner.py`.

### Task 1: Persist Workspace runtime configuration and operations

**Files:**
- Create: `backend/migrations/versions/20260802_0023_add_workspace_runtime_orchestration.py`
- Create: `backend/src/context_router/repositories/workspace_runtime_repository.py`
- Create: `backend/src/context_router/repositories/runtime_operation_repository.py`
- Create: `backend/src/context_router/schemas/workspace_runtime.py`
- Test: `backend/tests/test_workspace_runtime_repository.py`
- Test: `backend/tests/test_runtime_operation_repository.py`
- Modify: `docs/DATABASE_INFO.md`

- [ ] **Step 1: Write failing repository and migration tests**

Cover replacement of `start` files, policy validation, atomic parent/step creation, single active Workspace operation, single active Project step, lease with `SKIP LOCKED`, heartbeat, terminal completion, and lease-expiry reconciliation. Use fixed IDs and assert no secret/config content appears in operation summaries.

```python
def test_operation_repository_leases_one_operation_once(repository):
    operation = repository.create_operation(operation_draft())
    first = repository.lease_next(runner_id="runner-a", lease_seconds=30)
    second = repository.lease_next(runner_id="runner-b", lease_seconds=30)
    assert first is not None and first.id == operation.id
    assert second is None
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```bash
docker compose exec backend uv run pytest \
  tests/test_workspace_runtime_repository.py \
  tests/test_runtime_operation_repository.py -q
```

Expected: collection/import failures for the new repository modules.

- [ ] **Step 3: Add migration `0023`**

Create `workspace_runtime_files`, `workspace_runtime_policies`, `runtime_operations`, `runtime_operation_steps`, and `runtime_runner_instances` exactly as specified. Add partial unique indexes for active Workspace operations and active Project steps, checks for enums, JSONB defaults, foreign keys with explicit cascade behavior, and downgrade in reverse dependency order.

- [ ] **Step 4: Implement typed records and in-memory/PostgreSQL stores**

Expose protocols with these stable methods:

```python
class WorkspaceRuntimeStore(Protocol):
    def list_files(self, workspace_id: str, profile: str) -> list[WorkspaceRuntimeFileRecord]: ...
    def replace_files(self, workspace_id: str, profile: str, files: list[WorkspaceRuntimeFileDraft]) -> list[WorkspaceRuntimeFileRecord]: ...
    def get_policy(self, workspace_id: str) -> WorkspaceRuntimePolicyRecord | None: ...
    def save_policy(self, workspace_id: str, policy: WorkspaceRuntimePolicyDraft) -> WorkspaceRuntimePolicyRecord: ...

class RuntimeOperationStore(Protocol):
    def create_operation(self, draft: RuntimeOperationDraft) -> RuntimeOperationRecord: ...
    def get_operation(self, operation_id: str) -> RuntimeOperationRecord | None: ...
    def list_steps(self, operation_id: str) -> list[RuntimeOperationStepRecord]: ...
    def lease_next(self, runner_id: str, lease_seconds: int) -> RuntimeOperationLease | None: ...
    def mark_started(self, operation_id: str, lease_token: str) -> RuntimeOperationRecord: ...
    def heartbeat(self, operation_id: str, lease_token: str, lease_seconds: int) -> RuntimeOperationRecord: ...
    def complete_step(self, operation_id: str, step_id: str, lease_token: str, result: RuntimeStepResult) -> RuntimeOperationRecord: ...
    def reconcile_expired(self) -> int: ...
```

- [ ] **Step 5: Run tests, migration upgrade/current, and commit**

Run:

```bash
docker compose restart backend
docker compose exec backend uv run pytest tests/test_workspace_runtime_repository.py tests/test_runtime_operation_repository.py -q
docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run alembic current
```

Expected: tests pass and current revision is `20260802_0023`.

Commit:

```bash
git add backend/migrations backend/src/context_router/repositories backend/src/context_router/schemas/workspace_runtime.py backend/tests docs/DATABASE_INFO.md
git commit -m "feat: persist workspace runtime operations"
```

### Task 2: Generalize materialization and route Workspace changes

**Files:**
- Modify: `backend/src/context_router/services/runtime_materialization.py`
- Create: `backend/src/context_router/services/workspace_runtime_orchestration.py`
- Modify: `backend/src/context_router/services/project_registry.py`
- Test: `backend/tests/test_workspace_runtime_orchestration.py`
- Test: `backend/tests/test_runtime_materialization.py`

- [ ] **Step 1: Write failing routing and materialization tests**

Test safe POSIX normalization, duplicate removal, absolute/`..`/symlink rejection, deepest Project match, root Project fallback, unmapped files, Workspace-level path routing, fast/full classification, deterministic backend-before-frontend ordering, immutable Workspace snapshots, and active-operation conflicts.

```python
def test_routes_nested_project_by_longest_source_prefix(service):
    plan = service.plan_changes(
        task_id=7,
        changed_files=["apps/admin/src/page.tsx", "services/api/main.py"],
    )
    assert [(step.owner_id, step.mode) for step in plan.steps] == [
        ("api", "fast"),
        ("admin", "fast"),
    ]
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
docker compose exec backend uv run pytest tests/test_workspace_runtime_orchestration.py tests/test_runtime_materialization.py -q
```

- [ ] **Step 3: Generalize snapshot ownership**

Replace Project-only `MaterializedRuntimeConfig` fields with `owner_type`, `owner_id`, and `profile`, while preserving a compatibility wrapper for `materialize(project_id, mode, files)`. Materialize Workspace snapshots under `/runtime/workspaces/{id}/start/{snapshot}` and Project snapshots under the existing path.

- [ ] **Step 4: Implement orchestration service**

Provide:

```python
class WorkspaceRuntimeOrchestrationService:
    def apply_changes(self, *, task_id: int, changed_files: list[str]) -> RuntimeOperationView: ...
    def start_workspace(self, *, task_id: int) -> RuntimeOperationView: ...
    def get_operation(self, operation_id: str, log_characters: int = 10_000) -> RuntimeOperationView: ...
    def apply_project_compat(self, *, project_id: str, changed_files: list[str]) -> RuntimeOperationView: ...
```

Resolve task scope through `TaskStore`, validate the current Workspace through `ProjectRegistry`, classify files centrally, materialize every step before creating the operation, and never read `.env.local`.

- [ ] **Step 5: Run focused tests and commit**

```bash
docker compose restart backend
docker compose exec backend uv run pytest tests/test_workspace_runtime_orchestration.py tests/test_runtime_materialization.py -q
git add backend/src/context_router/services backend/tests
git commit -m "feat: orchestrate workspace runtime changes"
```

### Task 3: Add authenticated Host Runner protocol

**Files:**
- Create: `backend/src/context_router/api/runtime_runner.py`
- Modify: `backend/src/context_router/config.py`
- Modify: `backend/src/context_router/main.py`
- Modify: `backend/src/context_router/middleware/browser_read_only.py`
- Modify: `docker-compose.yml`
- Test: `backend/tests/test_runtime_runner_api.py`

- [ ] **Step 1: Write failing API security and lifecycle tests**

Assert missing/wrong bearer token is `401`, browser Origin is rejected, register persists capabilities without environment, stale Runner causes `host_runner_unavailable`, lease returns relative paths and one-time lease token, wrong lease token cannot heartbeat/complete, and completion advances or terminates the parent operation.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
docker compose exec backend uv run pytest tests/test_runtime_runner_api.py -q
```

- [ ] **Step 3: Add settings and token loader**

Add bounded settings for `/runtime/runner.token`, Runner heartbeat TTL, lease TTL, and API enablement. Read the token at request time, require a regular non-symlink file with mode no broader than `0600`, and compare bearer values with `hmac.compare_digest`.

- [ ] **Step 4: Implement register/heartbeat/lease/result API**

Expose the versioned endpoints from the design. Never return command arrays or runtime file content. Return `409 host_runner_unavailable` from orchestration before operation creation if no compatible Runner heartbeat exists.

- [ ] **Step 5: Wire app state/router, verify, and commit**

```bash
docker compose restart backend
docker compose exec backend uv run pytest tests/test_runtime_runner_api.py -q
git add backend/src/context_router/api backend/src/context_router/config.py backend/src/context_router/main.py backend/src/context_router/middleware docker-compose.yml backend/tests/test_runtime_runner_api.py
git commit -m "feat: add host runtime runner protocol"
```

### Task 4: Implement the stdlib Host Runner and manual lifecycle scripts

**Files:**
- Create: `scripts/context_router_host_runner.py`
- Create: `scripts/start-local-stack.sh`
- Create: `scripts/stop-local-stack.sh`
- Create: `scripts/status-local-stack.sh`
- Test: `backend/tests/test_host_runtime_runner.py`
- Test: `backend/tests/test_local_stack_scripts.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing Runner tests**

Use a fake HTTP server and temporary Workspace/runtime roots. Test token permissions, registration, lease polling, manifest verification, fixed `deploy.sh`, symlink/path escape rejection, stdout/stderr log merge, environment allowlist, heartbeat, success, nonzero exit, process-group timeout, and no automatic cleanup.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
docker compose exec backend uv run pytest tests/test_host_runtime_runner.py tests/test_local_stack_scripts.py -q
```

- [ ] **Step 3: Implement Host Runner**

The script must use only `argparse`, `hashlib`, `hmac`, `http.client`/`urllib`, `json`, `os`, `pathlib`, `signal`, `socket`, `subprocess`, `threading`, and `time`. It accepts only control-plane URL, allowed Workspace root, shared runtime root, token path, and poll interval. Execute exactly:

```python
process = subprocess.Popen(
    ["/bin/sh", str(validated_entry)],
    cwd=str(snapshot_root),
    env=controlled_environment,
    stdout=log_stream,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
```

- [ ] **Step 4: Implement manual lifecycle scripts**

`start-local-stack.sh` creates the shared directory/token before Compose, starts backend/frontend, waits for `/health`, validates or replaces only a marker-matching Runner PID, starts the Runner, and waits for heartbeat. `stop` validates PID command/cwd before TERM/KILL. `status` reports Docker health and Runner status without printing token.

- [ ] **Step 5: Verify shell and Runner tests, then commit**

```bash
zsh -n scripts/start-local-stack.sh scripts/stop-local-stack.sh scripts/status-local-stack.sh
docker compose exec backend uv run pytest tests/test_host_runtime_runner.py tests/test_local_stack_scripts.py -q
git add scripts .gitignore backend/tests/test_host_runtime_runner.py backend/tests/test_local_stack_scripts.py
git commit -m "feat: add manual host runtime runner"
```

### Task 5: Expose Workspace MCP tools and trace them

**Files:**
- Modify: `backend/src/context_router/mcp_server.py`
- Modify: `backend/src/context_router/mcp_contract.py`
- Modify: `backend/src/context_router/repositories/mcp_tool_call_repository.py`
- Modify: `backend/src/context_router/services/mcp_trace.py`
- Modify: `backend/src/context_router/services/mcp_integration.py`
- Modify: `backend/src/context_router/schemas/mcp_integration.py`
- Modify: `backend/src/context_router/main.py`
- Test: `backend/tests/test_mcp_server.py`
- Test: `backend/tests/test_mcp_traces.py`
- Test: `backend/tests/test_mcp_integration_api.py`

- [ ] **Step 1: Write failing MCP contract and trace tests**

Assert stable `tools/list` ordering, exact schemas, destructive annotations, orchestration forwarding, ToolError codes, compatibility adapters, `get_workspace_operation` reverse task trace association, and integration metadata listing all runtime tools.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
docker compose exec backend uv run pytest tests/test_mcp_server.py tests/test_mcp_traces.py tests/test_mcp_integration_api.py -q
```

- [ ] **Step 3: Add the three tools and compatibility routing**

Register `apply_workspace_changes(task_id, changed_files)`, `start_workspace(task_id)`, and `get_workspace_operation(operation_id, log_characters=10000)`. Update Server instructions to make “start” always Workspace-wide and require polling to terminal state. Keep old tools but route them through orchestration.

- [ ] **Step 4: Extend trace whitelist and task resolution**

For operation queries, resolve `task_id` from the operation before `start_call`. Trace only counts, modes, status, and operation ID. Do not capture Runtime logs or config files as database payload snapshots.

- [ ] **Step 5: Run tests and commit**

```bash
docker compose restart backend
docker compose exec backend uv run pytest tests/test_mcp_server.py tests/test_mcp_traces.py tests/test_mcp_integration_api.py -q
git add backend/src/context_router backend/tests/test_mcp_server.py backend/tests/test_mcp_traces.py backend/tests/test_mcp_integration_api.py
git commit -m "feat: expose workspace runtime mcp tools"
```

### Task 6: Add Workspace runtime management/read APIs

**Files:**
- Create: `backend/src/context_router/api/workspace_runtime.py`
- Modify: `backend/src/context_router/main.py`
- Modify: `backend/src/context_router/middleware/browser_read_only.py`
- Test: `backend/tests/test_workspace_runtime_api.py`

- [ ] **Step 1: Write failing API tests**

Test GET configuration/policy/history, AI/ops PUT replacement, browser PUT rejection, fixed `start/deploy.sh` requirement, Project-order membership validation, bounded operation/log retrieval, and no `.env.local` content in responses.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
docker compose exec backend uv run pytest tests/test_workspace_runtime_api.py -q
```

- [ ] **Step 3: Implement and wire API**

Use existing Repository/Schema patterns. Browser requests remain GET-only; no page execution endpoint is introduced. Return `404` for cross-Workspace operation lookup and `503` for unavailable control-plane storage.

- [ ] **Step 4: Run tests and commit**

```bash
docker compose restart backend
docker compose exec backend uv run pytest tests/test_workspace_runtime_api.py -q
git add backend/src/context_router/api/workspace_runtime.py backend/src/context_router/main.py backend/src/context_router/middleware/browser_read_only.py backend/tests/test_workspace_runtime_api.py
git commit -m "feat: manage workspace runtime configuration"
```

### Task 7: Configure the English Workspace and Agent workflow

**Files:**
- Modify: `/Users/conchi/workforce/rob_english_word_workforce/AGENTS.md`
- Modify: `/Users/conchi/workforce/rob_english_word_workforce/docs/shared/runtime-deployment-map.md`
- Create or update through API: English Workspace `start` Runtime files and policy
- Test: `backend/tests/test_english_workspace_runtime_contract.py`

- [ ] **Step 1: Write a failing cross-repository contract test**

Assert the target root has tracked `.env.example`, ignored `.env.local`, executable `deploy-compose-full.sh`, root AGENTS rules naming the three tools, and Workspace config wrapper that executes only `"$WORKSPACE_HOST_ROOT/deploy-compose-full.sh"`.

- [ ] **Step 2: Run contract test and confirm RED**

```bash
docker compose exec backend uv run pytest tests/test_english_workspace_runtime_contract.py -q
```

- [ ] **Step 3: Update root Agent/runtime documentation**

Add the approved rules once at Workspace root. Do not duplicate them into six Project AGENTS files. State that explicit “start” always means all registered Workspace projects and that operations must be polled to a terminal state.

- [ ] **Step 4: Save Workspace start config and policy through API**

Use the registered English Workspace ID discovered through the management API. Save a `start/deploy.sh` wrapper, Workspace-level paths (`deploy-compose-full.sh`, `.env.example`, relevant root scripts), and deterministic Project order. Never send `.env.local` content.

- [ ] **Step 5: Verify contract and commit target/document changes**

```bash
docker compose exec backend uv run pytest tests/test_english_workspace_runtime_contract.py -q
git add backend/tests/test_english_workspace_runtime_contract.py
git commit -m "test: cover english workspace runtime contract"
```

In the target repository:

```bash
git add AGENTS.md docs/shared/runtime-deployment-map.md
git commit -m "docs: adopt context router runtime workflow"
```

### Task 8: Full verification and real operation acceptance

**Files:**
- Modify: `docs/BUSINESS_FEATURES.md`
- Modify: `docs/STARTUP_GUIDE.md`
- Modify: `docs/FRONTEND_BACKEND_FLOW.md`
- Modify: `docs/DEVELOPMENT_OUTLINE.md`
- Modify: `AGENTS.md` only if the root index needs a new explicit rule

- [ ] **Step 1: Update durable documentation**

Document five context/database tools, three Workspace Runtime tools, and two compatibility Runtime tools accurately, together with manual stack lifecycle, Host Runner security, operation states, `.env.local` exclusion, API routes, migration `0023`, and troubleshooting errors.

- [ ] **Step 2: Run the complete repository verification through Compose**

```bash
docker compose restart backend
docker compose exec backend uv run pytest -q
docker compose exec backend uv run ruff check .
docker compose exec backend uv run mypy src
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
docker compose exec backend uv run alembic current
```

Expected: all commands exit 0 and migration is `20260802_0023`.

- [ ] **Step 3: Run manual stack and MCP protocol acceptance**

```bash
./scripts/start-local-stack.sh
./scripts/status-local-stack.sh
```

Call real MCP `tools/list`, `prepare_task_context`, and `start_workspace`; poll `get_workspace_operation` until terminal. Verify the English Workspace six containers, CLI Runner, backend health endpoints, and three frontend URLs without printing `.env.local`.

- [ ] **Step 4: Verify incremental routing and controlled failure**

Use a harmless source-file test change or isolated test fixture to verify Project fast routing, a dependency filename to verify full routing, multi-Project ordering, and a deliberate fake deploy failure to verify `failed/skipped` without cleanup.

- [ ] **Step 5: Final security/static checks and commit**

```bash
git diff --check
rg -n "\.env\.local|runner\.token" backend/src scripts docs --glob '!**/*test*'
git status --short
```

Review every match to ensure only paths/policy are present, never values. Commit:

```bash
git add docs backend scripts docker-compose.yml .gitignore
git commit -m "docs: document workspace runtime orchestration"
```
