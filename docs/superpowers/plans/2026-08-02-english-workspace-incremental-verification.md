# English Workspace Incremental Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject invalid runtime YAML at save time, repair the English Workspace fast configurations, document the MCP workflow, and prove all six Projects can apply and roll back real incremental updates.

**Architecture:** Runtime YAML syntax validation belongs in the Pydantic request boundary, while stored configuration repair continues through the existing local management API. Real acceptance uses Streamable HTTP MCP calls against the running Context Router and the manually started Host Runtime Runner; each Project gets an isolated fast operation before and after its temporary source comment is removed.

**Tech Stack:** Python 3.12, Pydantic 2, PyYAML, FastAPI, pytest, MCP Streamable HTTP, Docker Compose, Go, Java, Vue, React, zsh.

---

### Task 1: Reject invalid runtime YAML before persistence

**Files:**
- Create: `backend/tests/test_runtime_config_validation.py`
- Modify: `backend/src/context_router/schemas/runtime_configs.py`

- [ ] **Step 1: Write the failing Schema tests**

```python
import pytest
from pydantic import ValidationError

from context_router.schemas.runtime_configs import RuntimeConfigModeUpdate


def test_runtime_config_rejects_invalid_yaml_with_file_and_line() -> None:
    with pytest.raises(ValidationError, match=r"compose\.yml.*第 5 行"):
        RuntimeConfigModeUpdate.model_validate(
            {"files": [{"relative_path": "compose.yml", "content": "services:\n  app:\n    command: |-\n    echo broken\nnext: value\n"}]}
        )


def test_runtime_config_accepts_valid_yaml_literal_block_and_non_yaml() -> None:
    update = RuntimeConfigModeUpdate.model_validate(
        {"files": [
            {"relative_path": "compose.yml", "content": "services:\n  app:\n    command: |-\n      echo valid\n"},
            {"relative_path": "deploy.sh", "content": "not: [required to be yaml\n", "executable": True},
        ]}
    )
    assert [item.relative_path for item in update.files] == ["compose.yml", "deploy.sh"]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run `docker compose exec backend uv run --extra dev pytest -q tests/test_runtime_config_validation.py`.

Expected: the invalid-YAML test fails because `RuntimeConfigModeUpdate` currently accepts the payload.

- [ ] **Step 3: Add minimal YAML syntax validation**

In `backend/src/context_router/schemas/runtime_configs.py`, import `yaml`, then extend `validate_unique_paths` after duplicate checking:

```python
        for item in self.files:
            suffix = PurePosixPath(item.relative_path).suffix.lower()
            if suffix not in {".yml", ".yaml"} or not item.content.strip():
                continue
            try:
                yaml.safe_load(item.content)
            except yaml.YAMLError as exc:
                mark = getattr(exc, "problem_mark", None)
                location = (
                    f"第 {mark.line + 1} 行，第 {mark.column + 1} 列"
                    if mark is not None
                    else "位置未知"
                )
                raise ValueError(
                    f"运行配置 YAML 语法错误：{item.relative_path}（{location}）"
                ) from exc
```

The error omits YAML content so credentials cannot enter validation responses.

- [ ] **Step 4: Run focused and Schema/API regression tests**

Run:

```bash
docker compose restart backend
docker compose exec backend uv run --extra dev pytest -q tests/test_runtime_config_validation.py tests/test_workspace_runtime_api.py tests/test_workspace_runtime_orchestration.py
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the validation change**

```bash
git add backend/src/context_router/schemas/runtime_configs.py backend/tests/test_runtime_config_validation.py
git commit -m "fix: validate runtime yaml configuration"
```

### Task 2: Repair stored fast configurations and clarify target AGENTS rules

**Files:**
- Modify: `/Users/conchi/workforce/rob_english_word_workforce/AGENTS.md`
- Modify through API: Project fast runtime records for IDs `e65daaf764ad4e05b5fdbf43d3073b1f`, `d237e4d34d3948ca82ad3feba5e7059a`, `0a32b2bc345f4e0e821c768c0e13efc2`

- [ ] **Step 1: Update each stored fast configuration through the management API**

For each affected Project, GET `/api/projects/{project_id}/runtime-config`, preserve every fast file and executable flag, and change only `compose.yml` so every shell line following `- |` has eight spaces of indentation. PUT the complete file list to `/api/projects/{project_id}/runtime-config/fast`.

The corrected main-frontend block must be:

```yaml
    command:
      - sh
      - -c
      - |
        socat TCP-LISTEN:8019,fork,reuseaddr TCP:host.docker.internal:6012 &
        socat TCP-LISTEN:9091,fork,reuseaddr TCP:host.docker.internal:6013 &
        exec npm run dev -- --host 0.0.0.0
```

The management and cloze blocks use the same indentation with their existing single `socat` command.

- [ ] **Step 2: Verify all six fast YAML files parse**

GET all six Project runtime configurations and pass each fast `.yml/.yaml` content through `RuntimeConfigModeUpdate.model_validate`. Expected: all six validate, and the corrected modes retain their original file path sets.

- [ ] **Step 3: Optimize the root AGENTS workflow**

In `/Users/conchi/workforce/rob_english_word_workforce/AGENTS.md`, make these rules explicit:

```markdown
- 用户说“启动”“启动项目”或“启动服务”时，统一调用 `start_workspace(task_id)`；它始终启动本工作空间登记的全部项目。
- 完成代码或受版本控制配置修改后，收集本轮所有真实 Workspace 相对路径，一次调用 `apply_workspace_changes(task_id, changed_files)`；不要传未修改路径，也不要按 Project 拆成多次调用。
- 单 Project 普通源码改动应只生成该 Project 的一个 `fast` 步骤；依赖、构建、Compose、Workspace 级文件或跨 Project 改动可升级为 `full` 或 Workspace 启动步骤，以返回的 `decision_reason` 为准。
- `apply_workspace_changes` 与 `start_workspace` 返回 `operation_id` 后，调用 `get_workspace_operation(task_id, operation_id)` 轮询到终态。
- 终态为 `failed`、`cancelled` 或 `interrupted` 时，保留已启动容器和日志并客观报告；除非用户明确要求，不自动修复目标配置、清理容器、镜像、Volume 或业务数据。
```

- [ ] **Step 4: Commit the target documentation**

```bash
git -C /Users/conchi/workforce/rob_english_word_workforce add AGENTS.md
git -C /Users/conchi/workforce/rob_english_word_workforce commit -m "docs: clarify workspace incremental workflow"
```

### Task 3: First real incremental pass for six Projects

**Files:**
- Temporarily modify: the six source files listed in the design specification
- No permanent source change from this task

- [ ] **Step 1: Prepare a real MCP task**

Use `mcp.client.streamable_http.streamable_http_client` and `mcp.ClientSession` against `http://127.0.0.1:8000/mcp` from the backend container. Call `prepare_task_context` with task `验证英语 Workspace 六个 Project 增量更新`, cwd `/Users/conchi/workforce/rob_english_word_workforce`, and agent name `codex-incremental-verification`. Persist only the returned integer `task_id` in the verification log; do not print `environment_config`.

- [ ] **Step 2: Add unique temporary comments with apply_patch**

Add exactly one language-valid comment containing `context-router-incremental-verification-20260802` to:

```text
word_select_dashboard/server/main.go
word_select_dashboard/word-agent/src/word_agent/main.py
rob_english_word_back/src/main/java/com/robword/RobEnglishWordApplication.java
word_select_dashboard/web-react/src/App.tsx
rob_english_word_front/src/router/index.ts
rob_english_word_cloze_web/src/App.tsx
```

Use `//` for Go/Java/TypeScript, `#` for Python, and an ordinary `//` script comment for Vue TypeScript. Do not alter executable behavior.

- [ ] **Step 3: Execute and poll each Project independently**

For each changed path, call `apply_workspace_changes` with a one-item `changed_files` list. Assert the response has one step for the expected Project and profile `fast`. Poll `get_workspace_operation` with both `task_id` and `operation_id` every two seconds until terminal. Require `status == "succeeded"`, step exit code 0, and record operation ID, Project ID, profile and bounded final log tail.

- [ ] **Step 4: Confirm the six target containers remain running**

```bash
docker inspect --format '{{.Name}} {{.State.Running}} {{.State.Restarting}}' word-select-dashboard word-agent rob-english-word word-select-dashboard-web-react rob-english-word-front-web rob-english-word-cloze-web
```

Expected: every row reports `true false`.

### Task 4: Roll back temporary source comments and apply the rollback incrementally

**Files:**
- Restore: the six temporary source files from Task 3

- [ ] **Step 1: Remove only the unique verification comments with apply_patch**

Remove the six exact marker comment lines. Verify `rg` finds no marker and `git diff` contains no changes in those six files beyond pre-existing user work.

- [ ] **Step 2: Execute the second six-Project MCP pass**

Using the same `task_id`, call `apply_workspace_changes` once per restored path and poll each operation exactly as in Task 3. Require all six operations to choose one `fast` step and finish `succeeded` with exit code 0.

- [ ] **Step 3: Confirm restored runtime and repository state**

Re-run the six-container `docker inspect`. Confirm the target repository contains only the intended `AGENTS.md` commit and no verification marker or uncommitted test-source change.

### Task 5: Full regression, durable docs and completion

**Files:**
- Modify: `docs/STARTUP_GUIDE.md`
- Modify: `docs/BUSINESS_FEATURES.md`
- Update: `task_plan.md`, `findings.md`, `progress.md` (working records only)

- [ ] **Step 1: Document YAML save validation**

Document that `.yml/.yaml` files are syntactically parsed before persistence; errors return file, line and column without echoing content, while Docker Compose semantic validation remains an execution/preflight responsibility.

- [ ] **Step 2: Run complete Context Router verification**

```bash
docker compose restart backend
docker compose exec backend uv run --extra dev pytest -q
docker compose exec backend uv run --extra dev ruff check .
docker compose exec backend uv run --extra dev ruff format --check .
docker compose exec frontend npm run lint
docker compose exec frontend npm test
docker compose exec frontend npm run build
docker compose exec backend uv run alembic current
```

Expected: tests, lint, format and build pass; Alembic reports `20260802_0023 (head)`.

- [ ] **Step 3: Run final boundary checks**

```bash
git diff --check
git status --short
git -C /Users/conchi/workforce/rob_english_word_workforce diff --check
git -C /Users/conchi/workforce/rob_english_word_workforce status --short
./scripts/status-local-stack.sh
```

Confirm `.env.local` was never read, staged or printed, and no verification marker remains.

- [ ] **Step 4: Commit final Context Router changes**

```bash
git add backend/src/context_router/schemas/runtime_configs.py backend/tests/test_runtime_config_validation.py docs/STARTUP_GUIDE.md docs/BUSINESS_FEATURES.md
git commit -m "fix: validate incremental runtime configuration"
```

Keep both current branches as-is; do not push, merge, delete or clean target containers.
