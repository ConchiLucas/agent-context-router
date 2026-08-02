# Workspace Deploy Config Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Workspace-level preview-and-commit workflow that atomically imports canonical runtime configuration from repository `deploy/context-router/` files into PostgreSQL.

**Architecture:** A focused scanner service resolves the fixed repository convention into a typed bundle and digest. A bundle repository method writes Workspace start files, policy, and every Project fast/full profile in one transaction. Two fixed POST endpoints expose preview and digest-guarded commit, and the Workspace page adds a confirmation dialog.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, psycopg/PostgreSQL, PyYAML, Next.js/React/TypeScript, Vitest, pytest, Docker Compose.

---

## File map

- Create `backend/src/context_router/services/workspace_deploy_sync.py`: fixed-path scan, validation, digest, diff and orchestration.
- Create `backend/src/context_router/schemas/workspace_deploy_sync.py`: manifest and API request/response models.
- Modify `backend/src/context_router/repositories/workspace_runtime_repository.py`: atomic bundle draft/store contract and PostgreSQL transaction.
- Modify `backend/src/context_router/repositories/runtime_config_repository.py`: expose database URL only if required by the shared transaction implementation; prefer keeping all SQL in the bundle repository.
- Modify `backend/src/context_router/api/workspace_runtime.py`: preview and commit endpoints.
- Modify `backend/src/context_router/main.py`: construct and expose the sync service.
- Modify `backend/src/context_router/middleware/browser_read_only.py`: exact POST allowlist entries.
- Create `backend/tests/test_workspace_deploy_sync.py`: scanner, validation, digest and stale-preview behavior.
- Modify `backend/tests/test_workspace_runtime_repository.py`: atomic replacement and rollback contract.
- Modify `backend/tests/test_workspace_runtime_api.py`: API and browser behavior.
- Modify `frontend/lib/runtime-api.ts`: sync models and calls.
- Modify `frontend/lib/browser-api-policy.ts`: matching browser allowlist.
- Modify `frontend/lib/browser-api-policy.test.ts`: allowlist regression tests.
- Create `frontend/components/workspace-runtime-sync.tsx`: button, preview dialog and commit state.
- Create `frontend/components/workspace-runtime-sync.test.tsx`: interaction tests.
- Modify `frontend/components/workspace-detail.tsx`: mount the Workspace action.
- Modify frontend CSS colocated with existing Workspace styles: dialog and summary layout.
- Modify `docs/BUSINESS_FEATURES.md`, `docs/STARTUP_GUIDE.md`, and `docs/FRONTEND_BACKEND_FLOW.md`: canonical directory and sync flow.

### Task 1: Scanner contract and validation

**Files:**
- Create: `backend/tests/test_workspace_deploy_sync.py`
- Create: `backend/src/context_router/schemas/workspace_deploy_sync.py`
- Create: `backend/src/context_router/services/workspace_deploy_sync.py`

- [ ] **Step 1: Write failing tests for a valid fixed-layout bundle**

Create a temporary Workspace with `deploy/context-router/manifest.yaml`, Workspace `start`, and one Project `fast/full`; assert `scan()` returns Workspace-relative project mapping, sorted files, executable `deploy.sh`, and a stable 64-character digest.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `docker compose run --rm backend pytest tests/test_workspace_deploy_sync.py -q`

Expected: FAIL because `workspace_deploy_sync` does not exist.

- [ ] **Step 3: Implement the minimal typed scanner**

Define `WorkspaceDeployBundle`, `ProjectDeployBundle`, `RuntimeProfileBundle`, preview/diff models, `WorkspaceDeploySyncError(code, message)`, and `WorkspaceDeploySyncService.scan(workspace, projects)`. Read only fixed directories, normalize text files, preserve executable bits, sort paths, and hash normalized manifest plus file metadata/content.

- [ ] **Step 4: Add one failing validation test at a time**

Cover missing manifest/profile/entry, schema version, duplicate/unknown/missing Project paths, non-executable `deploy.sh`, invalid YAML, non-UTF-8 file, symlink, secret filenames, file count and size limits. Run the same focused command after each test to observe RED before implementing its validator.

- [ ] **Step 5: Make validation tests GREEN and refactor shared path checks**

Reuse `normalize_project_relative_path`, Pydantic runtime file validation, and a single `Path.resolve()` containment check. Do not accept a source path from callers.

### Task 2: Atomic bundle persistence

**Files:**
- Modify: `backend/tests/test_workspace_runtime_repository.py`
- Modify: `backend/src/context_router/repositories/workspace_runtime_repository.py`

- [ ] **Step 1: Write failing in-memory atomic replacement tests**

Seed old Workspace and Project profiles; replace them with a complete bundle and assert all four data classes change together. Inject an invalid profile and assert every old value remains.

- [ ] **Step 2: Run repository tests and verify RED**

Run: `docker compose run --rm backend pytest tests/test_workspace_runtime_repository.py -q`

Expected: FAIL because `replace_workspace_bundle` is missing.

- [ ] **Step 3: Add the bundle persistence contract**

Add typed Project profile drafts and `replace_workspace_bundle(workspace_id, start_files, policy, project_profiles)` to `WorkspaceRuntimeStore`. The in-memory implementation validates first, builds copies, and swaps state under one lock.

- [ ] **Step 4: Add PostgreSQL rollback integration coverage**

Exercise one successful replacement and a deliberately invalid/failed replacement against the test database; assert the old rows remain after failure.

- [ ] **Step 5: Implement one PostgreSQL transaction**

Within one `psycopg.connect()` context, delete/insert Workspace start rows, upsert policy, delete runtime rows for all Workspace Project IDs, and insert every fast/full row. Return only after commit; map `psycopg.Error` to `WorkspaceRuntimeRepositoryError`.

### Task 3: Preview and digest-guarded commit API

**Files:**
- Modify: `backend/tests/test_workspace_deploy_sync.py`
- Modify: `backend/tests/test_workspace_runtime_api.py`
- Modify: `backend/src/context_router/api/workspace_runtime.py`
- Modify: `backend/src/context_router/main.py`

- [ ] **Step 1: Write failing preview API test**

Build the canonical temporary tree, POST preview, and assert source root, digest, profile counts, additions/updates/deletions, and `valid=true`.

- [ ] **Step 2: Write failing commit/stale digest tests**

POST commit with the preview digest and assert DB profiles/policy update. Modify one source file, reuse the old digest, and assert HTTP 409 with no DB mutation.

- [ ] **Step 3: Run focused API tests and verify RED**

Run: `docker compose run --rm backend pytest tests/test_workspace_runtime_api.py tests/test_workspace_deploy_sync.py -q`

- [ ] **Step 4: Implement service diff, preview and commit methods**

Compare normalized bundle data with current stores. `commit(expected_digest)` rescans, rejects mismatches with `deploy_sync_stale_preview`, and calls the single bundle repository method.

- [ ] **Step 5: Wire FastAPI and application state**

Add fixed POST routes with no path/body override except `expected_digest`; translate validation to 422, stale preview to 409, missing Workspace to 404, and repository unavailability to 503.

### Task 4: Browser write-policy exception

**Files:**
- Modify: `backend/tests/test_browser_read_only.py`
- Modify: `backend/tests/test_workspace_runtime_api.py`
- Modify: `backend/src/context_router/middleware/browser_read_only.py`
- Modify: `frontend/lib/browser-api-policy.test.ts`
- Modify: `frontend/lib/browser-api-policy.ts`

- [ ] **Step 1: Write failing backend and frontend policy tests**

Assert browser POST is allowed only for exact `/runtime-config/sync-preview` and `/runtime-config/sync` paths. Assert arbitrary suffixes, PUT runtime config, and all other management writes remain blocked.

- [ ] **Step 2: Run tests and verify RED**

Run backend: `docker compose run --rm backend pytest tests/test_browser_read_only.py tests/test_workspace_runtime_api.py -q`

Run frontend: `docker compose run --rm frontend npm test -- --run lib/browser-api-policy.test.ts`

- [ ] **Step 3: Add exact allowlist patterns**

Add only the two Workspace POST regexes to Python and TypeScript policies and rerun both focused suites to GREEN.

### Task 5: Workspace sync UI

**Files:**
- Modify: `frontend/lib/runtime-api.ts`
- Create: `frontend/components/workspace-runtime-sync.tsx`
- Create: `frontend/components/workspace-runtime-sync.test.tsx`
- Modify: `frontend/components/workspace-detail.tsx`
- Modify: the existing Workspace stylesheet that owns `.workspace-context-actions`

- [ ] **Step 1: Write failing interaction tests**

Mock preview/commit APIs. Assert button opens loading state, valid preview lists profile/diff counts, invalid preview disables confirm, success closes or updates the dialog, and API error stays visible without claiming DB deletion.

- [ ] **Step 2: Run the component test and verify RED**

Run: `docker compose run --rm frontend npm test -- --run components/workspace-runtime-sync.test.tsx`

- [ ] **Step 3: Add typed API calls**

Expose `previewWorkspaceDeploySync(workspaceId)` and `commitWorkspaceDeploySync(workspaceId, expectedDigest)` with request types matching backend JSON.

- [ ] **Step 4: Implement the component and mount it**

Add “同步 deploy 配置” to Workspace actions. Use an accessible dialog with explicit preview, confirm, cancel, loading, stale-preview and success states. Never accept or display editable source paths.

- [ ] **Step 5: Run focused frontend tests to GREEN**

Run the component and browser policy tests together.

### Task 6: Documentation and target-repository example

**Files:**
- Modify: `docs/BUSINESS_FEATURES.md`
- Modify: `docs/STARTUP_GUIDE.md`
- Modify: `docs/FRONTEND_BACKEND_FLOW.md`
- Create in the target Workspace during adoption: `deploy/context-router/manifest.yaml`, `deploy/context-router/README.md`, and profile wrappers.
- Modify in the target Workspace during adoption: `AGENTS.md` and Project `AGENTS.md` files.

- [ ] **Step 1: Document the canonical contract and transactional behavior**

Record fixed paths, manifest schema, validation limits, preview/commit flow, browser exception and standalone execution requirement. Do not record credentials or `.env.local` content.

- [ ] **Step 2: Add a contract fixture/test for the English Workspace**

Create or extend a read-only contract test that verifies all registered English Projects have the required fast/full wrappers and the root `AGENTS.md` links the fallback command.

- [ ] **Step 3: Run the contract test before and after adding wrappers**

Observe RED against the missing canonical tree, add wrappers that delegate to existing startup scripts, then rerun to GREEN.

### Task 7: Full verification

**Files:**
- No production changes unless a verification failure exposes a defect; every defect starts with a failing regression test.

- [ ] **Step 1: Run backend tests**

Run: `docker compose run --rm backend pytest -q`

- [ ] **Step 2: Run frontend tests and lint**

Run: `docker compose run --rm frontend npm test -- --run`

Run: `docker compose run --rm frontend npm run lint`

- [ ] **Step 3: Build the frontend and backend images**

Run: `docker compose build backend frontend`

- [ ] **Step 4: Inspect the final diff and requirement checklist**

Run: `git diff --check` and `git status --short`. Confirm fixed-directory scanning, full Workspace validation, digest conflict handling, one-transaction persistence, exact browser allowlist, accessible UI, docs, and no secret/private configuration additions.
