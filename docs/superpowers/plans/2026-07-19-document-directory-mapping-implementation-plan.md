# Document Directory Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Context Router 通过 `cwd → root_path → docs_path` 识别映射文档项目，并让 MCP 从唯一的 `AGENTS.md` 入口沿已同步 Markdown 链接安全地逐层读取。

**Architecture:** 代码项目识别继续使用现有 `root_path`；新增独立的文档根解析、目录映射、图同步和图访问策略。数据库只保存索引、关系、同步健康信息和历史链路，全文读取始终从只读挂载的映射目录完成；Web 负责选择映射、触发同步和展示健康状态。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL/SQLite tests、MCP stdio、Next.js 15、React 19、TypeScript、Docker Compose。

---

## 实施前约束

- 工作目录：`/Users/conchi/.config/superpowers/worktrees/agent-context-router/mcp-only-context-router`
- 功能分支：`codex/mcp-only-context-router`
- 设计依据：`docs/superpowers/specs/2026-07-19-document-directory-mapping-design.md`
- 所有测试、lint、build 和 migration 都通过当前 worktree 的 Docker Compose 执行。
- 每一项先写失败测试，再写最小实现，不在同一提交混入无关重构。
- 不删除旧 `retrieval.py`；新的 MCP prepare 停止调用它，清理工作留给后续独立变更。

## 文件职责图

### 后端新增

- `backend/alembic/versions/20260719_0008_add_document_mappings.py`：Project 映射/同步状态和 Document 图状态迁移。
- `backend/src/context_router/services/document_mapping.py`：统一文档根、候选目录、映射保存和安全路径解析。
- `backend/src/context_router/services/document_graph.py`：入口选择、reachable/depth 计算和 MCP direct-link 访问判断。
- `backend/src/context_router/api/document_mappings.py`：提供独立的合法候选目录查询 API。
- `backend/tests/test_document_mapping.py`：路径 containment、候选发现、唯一映射和 API 测试。
- `backend/tests/test_document_graph.py`：图层级、环、孤立文档和访问策略测试。

### 后端修改

- `backend/src/context_router/config.py`：增加 documents host/container root 配置。
- `backend/src/context_router/db/models.py`：增加 Project 映射字段和 Document 图字段。
- `backend/src/context_router/schemas/projects.py`：映射候选、映射请求和 Project 健康字段。
- `backend/src/context_router/schemas/documents.py`：同步统计、reachable/depth 和 broken link 输出。
- `backend/src/context_router/api/projects.py`：保存映射并返回 Project 状态。
- `backend/src/context_router/api/documents.py`：固定映射同步、列表健康信息和 MCP read 校验。
- `backend/src/context_router/services/markdown_sync.py`：严格扫描映射目录、原子更新链接图和 tombstone。
- `backend/src/context_router/services/local_document_reader.py`：只从映射目录实时读取，不回退代码根或缓存正文。
- `backend/src/context_router/api/context.py`：prepare 只返回已同步的 `AGENTS.md`。
- `backend/src/context_router/main.py`：注册文档映射候选 API router。

### 前端新增

- `frontend/app/api/document-mappings/candidates/route.ts`：候选目录 BFF 代理。
- `frontend/app/api/projects/[slug]/document-mapping/route.ts`：保存映射 BFF 代理。
- `frontend/components/project-document-controls.tsx`：映射选择器、保存和同步交互。
- `frontend/lib/document-health.ts`：纯函数生成 mapping/status/graph 展示模型。
- `frontend/lib/document-health.test.ts`：前端状态和分层逻辑测试。

### 前端修改

- `frontend/lib/types.ts`、`frontend/lib/api.ts`：映射、同步和文档图类型。
- `frontend/app/projects/page.tsx`、`frontend/app/projects/[slug]/page.tsx`：Code root、Document mapping 和健康统计。
- `frontend/components/project-link-reload-button.tsx`：同步不再发送任意路径，并显示完整统计。
- `frontend/components/document-graph.tsx`、`frontend/components/document-table.tsx`、`frontend/components/documents-view.tsx`：展示 reachable、orphan、depth 和 broken links。
- `frontend/app/globals.css`：映射选择器和健康状态样式。

### 部署与文档

- `docker-compose.yml`：只读挂载 documents root。
- `.env.example`：服务器文档根配置示例。
- `.gitignore`、`document-sources/.gitkeep`：提供可启动但无业务文档的本地默认挂载点。
- `README.md`、`AGENTS.md`、`docs/BUSINESS_FEATURES.md`、`docs/FRONTEND_BACKEND_FLOW.md`、`docs/STARTUP_GUIDE.md`、`docs/DATABASE_INFO.md`：同步新链路和运维说明。

## Task 1：数据库和配置基础

**Files:**
- Create: `backend/alembic/versions/20260719_0008_add_document_mappings.py`
- Modify: `backend/src/context_router/config.py`
- Modify: `backend/src/context_router/db/models.py`
- Modify: `backend/tests/test_config.py`
- Modify: `backend/tests/test_models.py`
- Modify: `backend/tests/test_sqlite_bootstrap.py`

- [ ] **Step 1: 写 Settings 和 ORM 字段的失败测试**

在 `backend/tests/test_config.py` 增加：

```python
def test_settings_reads_documents_roots(monkeypatch) -> None:
    monkeypatch.setenv("CONTEXT_ROUTER_DOCUMENTS_HOST_ROOT", "/srv/ai-docs")
    monkeypatch.setenv("CONTEXT_ROUTER_DOCUMENTS_CONTAINER_ROOT", "/documents")

    loaded = Settings(_env_file=None)

    assert loaded.documents_host_root == "/srv/ai-docs"
    assert loaded.documents_container_root == "/documents"
```

在 `backend/tests/test_models.py` 增加一个 Project/Document 持久化断言：

```python
project = Project(
    slug="orders",
    name="Orders",
    root_path="/srv/projects/orders",
    docs_path="order-docs",
    last_sync_status="success",
    last_sync_summary={"indexed": 3, "reachable": 2, "orphan": 1, "broken_links": 0, "pruned": 0},
)
document = Document(
    id="orders-entry",
    project=project,
    title="Orders entry",
    source_path="AGENTS.md",
    doc_type="agent_index",
    tags=[],
    status="active",
    content_markdown="# Orders",
    is_reachable=True,
    graph_depth=1,
)
session.add_all([project, document])
session.commit()
assert document.is_reachable is True
assert document.graph_depth == 1
assert project.docs_path == "order-docs"
```

- [ ] **Step 2: 运行测试并确认字段不存在**

Run:

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_config.py tests/test_models.py tests/test_sqlite_bootstrap.py
```

Expected: FAIL，错误包含 `Settings has no attribute documents_host_root` 或 Project 不接受 `docs_path`。

- [ ] **Step 3: 增加配置和模型字段**

在 `config.py` 的 `Settings` 增加：

```python
documents_host_root: str | None = None
documents_container_root: str = "/documents"
```

在 `Project` 增加：

```python
docs_path: Mapped[str | None] = mapped_column(String(1024), unique=True, index=True)
last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
last_sync_status: Mapped[str] = mapped_column(String(40), default="never", nullable=False)
last_sync_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
```

在 `Document` 增加：

```python
is_reachable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
graph_depth: Mapped[int | None] = mapped_column(Integer, index=True)
```

- [ ] **Step 4: 写 Alembic migration**

`20260719_0008_add_document_mappings.py` 的 upgrade 必须完成：

```python
op.add_column("projects", sa.Column("docs_path", sa.String(length=1024), nullable=True))
op.add_column("projects", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))
op.add_column(
    "projects",
    sa.Column("last_sync_status", sa.String(length=40), server_default="never", nullable=False),
)
op.add_column(
    "projects",
    sa.Column("last_sync_summary", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
)
op.create_index("ix_projects_docs_path", "projects", ["docs_path"], unique=True)
op.add_column(
    "documents",
    sa.Column("is_reachable", sa.Boolean(), server_default=sa.false(), nullable=False),
)
op.add_column("documents", sa.Column("graph_depth", sa.Integer(), nullable=True))
op.create_index("ix_documents_is_reachable", "documents", ["is_reachable"], unique=False)
op.create_index("ix_documents_graph_depth", "documents", ["graph_depth"], unique=False)
```

Downgrade 按相反顺序删除索引和列。迁移末尾移除仅用于迁移的 server default，避免数据库默认与 ORM 默认分叉。

- [ ] **Step 5: 验证单元测试和 migration**

Run:

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_config.py tests/test_models.py tests/test_sqlite_bootstrap.py
docker compose exec backend uv run alembic upgrade head
```

Expected: 所有测试 PASS；Alembic 输出升级到 `20260719_0008`。

- [ ] **Step 6: 提交基础字段**

```bash
git add backend/src/context_router/config.py backend/src/context_router/db/models.py backend/alembic/versions/20260719_0008_add_document_mappings.py backend/tests/test_config.py backend/tests/test_models.py backend/tests/test_sqlite_bootstrap.py
git commit -m "feat: add document mapping persistence"
```

## Task 2：安全文档根和唯一映射 API

**Files:**
- Create: `backend/src/context_router/services/document_mapping.py`
- Create: `backend/src/context_router/api/document_mappings.py`
- Create: `backend/tests/test_document_mapping.py`
- Modify: `backend/src/context_router/schemas/projects.py`
- Modify: `backend/src/context_router/api/projects.py`
- Modify: `backend/src/context_router/main.py`

- [ ] **Step 1: 写路径和候选发现失败测试**

`test_document_mapping.py` 使用 `tmp_path` 创建 `documents/order-docs/{AGENTS.md,docs/}`，并覆盖 settings：

```python
def test_list_candidates_only_returns_valid_direct_children(tmp_path, monkeypatch) -> None:
    root = tmp_path / "documents"
    valid = root / "order-docs"
    (valid / "docs").mkdir(parents=True)
    (valid / "AGENTS.md").write_text("# entry", encoding="utf-8")
    (root / "missing-agents" / "docs").mkdir(parents=True)
    nested = root / "team" / "nested-docs"
    (nested / "docs").mkdir(parents=True)
    (nested / "AGENTS.md").write_text("# nested", encoding="utf-8")
    monkeypatch.setattr(settings, "documents_container_root", str(root))

    assert [item.docs_path for item in list_document_candidates(session)] == ["order-docs"]
```

另写参数化测试拒绝 `/absolute`、`../escape`、目标软链接、realpath 逃逸和已被其他 Project 占用的 `docs_path`。

- [ ] **Step 2: 运行测试并确认服务不存在**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_document_mapping.py
```

Expected: FAIL，无法导入 `context_router.services.document_mapping`。

- [ ] **Step 3: 实现路径解析和候选模型**

`document_mapping.py` 使用以下完整边界逻辑（唯一性错误文案可由 API 转为 409）：

```python
class DocumentMappingError(ValueError):
    pass


@dataclass(frozen=True)
class DocumentMappingCandidate:
    docs_path: str
    markdown_count: int
    mapped_project_slug: str | None


def documents_root() -> Path:
    root = Path(settings.documents_container_root).expanduser()
    try:
        resolved = root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise DocumentMappingError(f"Documents root not found: {root}") from exc
    if not resolved.is_dir():
        raise DocumentMappingError(f"Documents root is not a directory: {root}")
    return resolved


def _resolve_docs_path(docs_path: str) -> Path:
    relative = Path(docs_path.strip())
    if relative.is_absolute() or ".." in relative.parts:
        raise DocumentMappingError(f"Invalid relative docs path: {docs_path}")
    root = documents_root()
    candidate = root / relative
    if candidate.is_symlink():
        raise DocumentMappingError(f"Mapped document directory cannot be a symlink: {docs_path}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise DocumentMappingError(f"Mapped document directory is unavailable: {docs_path}") from exc
    agents = resolved / "AGENTS.md"
    docs = resolved / "docs"
    if not agents.is_file() or agents.is_symlink() or not docs.is_dir() or docs.is_symlink():
        raise DocumentMappingError(f"Mapped directory requires AGENTS.md and docs/: {docs_path}")
    return resolved


def resolve_document_root(project: Project) -> Path:
    if not project.docs_path:
        raise DocumentMappingError(f"Project has no document mapping: {project.slug}")
    return _resolve_docs_path(project.docs_path)


def list_document_candidates(session: Session) -> list[DocumentMappingCandidate]:
    root = documents_root()
    occupied = dict(session.execute(select(Project.docs_path, Project.slug)).all())
    candidates: list[DocumentMappingCandidate] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.is_symlink():
            continue
        try:
            resolved = _resolve_docs_path(child.name)
        except DocumentMappingError:
            continue
        docs = resolved / "docs"
        markdown_count = 1 + sum(
            1 for path in docs.rglob("*.md") if path.is_file() and not path.is_symlink()
        )
        candidates.append(
            DocumentMappingCandidate(child.name, markdown_count, occupied.get(child.name))
        )
    return candidates


def assign_document_mapping(
    session: Session, *, project: Project, docs_path: str
) -> Project:
    resolved = _resolve_docs_path(docs_path)
    normalized = resolved.relative_to(documents_root()).as_posix()
    occupied = session.scalar(
        select(Project).where(Project.docs_path == normalized, Project.id != project.id)
    )
    if occupied is not None:
        raise DocumentMappingError(
            f"Document directory {normalized} is already mapped to {occupied.slug}"
        )
    project.docs_path = normalized
    project.last_synced_at = None
    project.last_sync_status = "never"
    project.last_sync_summary = {}
    return project
```

`resolve_document_root` 使用 `Path.resolve(strict=True)` 后做 `relative_to(root.resolve(strict=True))`，拒绝绝对路径、任意 `..`、映射目标软链接、缺少 `AGENTS.md` 或 `docs/`。`list_document_candidates` 只迭代 `root.iterdir()` 的非软链接直接子目录，`markdown_count` 为 `1 + len(docs.rglob("*.md"))`，扫描时排除软链接。

`assign_document_mapping` 保存规范化 POSIX 相对路径，并执行：

```python
project.docs_path = normalized_docs_path
project.last_synced_at = None
project.last_sync_status = "never"
project.last_sync_summary = {}
```

- [ ] **Step 4: 写映射 API 失败测试**

在同一测试文件增加：

```python
candidates = client.get("/api/document-mappings/candidates")
assert candidates.status_code == 200
assert candidates.json()["candidates"][0]["docs_path"] == "order-docs"

saved = client.put(
    "/api/projects/orders/document-mapping",
    json={"docs_path": "order-docs"},
)
assert saved.status_code == 200
assert saved.json()["docs_path"] == "order-docs"
assert saved.json()["last_sync_status"] == "never"
```

- [ ] **Step 5: 增加 schema 和路由**

在 `schemas/projects.py` 增加：

```python
class DocumentMappingRequest(BaseModel):
    docs_path: NonBlankString

class DocumentMappingCandidateResponse(BaseModel):
    docs_path: str
    markdown_count: int
    mapped_project_slug: str | None

class DocumentMappingCandidateListResponse(BaseModel):
    candidates: list[DocumentMappingCandidateResponse]
```

在 `api/document_mappings.py` 增加 `GET /api/document-mappings/candidates`，并在 `main.py` 注册该 router。在 `api/projects.py` 增加 Project 映射 PUT endpoint。映射错误返回 HTTP 400，Project 不存在返回 404，数据库唯一冲突返回 409。

- [ ] **Step 6: 运行并提交映射 API**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_document_mapping.py tests/test_projects.py
git add backend/src/context_router/services/document_mapping.py backend/src/context_router/api/document_mappings.py backend/src/context_router/schemas/projects.py backend/src/context_router/api/projects.py backend/src/context_router/main.py backend/tests/test_document_mapping.py
git commit -m "feat: add safe document directory mappings"
```

Expected: 两个测试文件全部 PASS。

## Task 3：严格扫描、文档图和原子同步

**Files:**
- Create: `backend/src/context_router/services/document_graph.py`
- Create: `backend/tests/test_document_graph.py`
- Modify: `backend/src/context_router/services/markdown_sync.py`
- Modify: `backend/src/context_router/services/document_store.py`
- Modify: `backend/src/context_router/schemas/documents.py`
- Modify: `backend/src/context_router/api/documents.py`
- Replace focused tests in: `backend/tests/test_document_ingestion.py`

- [ ] **Step 1: 写严格扫描和 front matter 失败测试**

把旧的任意 `docs_dir` 同步测试替换为映射目录 fixture。测试目录包含根 `AGENTS.md`、`docs/second.md`、`docs/deep/third.md`、根 `README.md`、`other/ignored.md` 和软链接，断言只索引前三份。

每份有效文档使用：

```markdown
---
doc_id: orders-entry
title: Orders entry
---

# Orders

[Business](./docs/business.md)
```

再增加缺少 `doc_id` 和跨项目重复 `doc_id` 用例，断言同步返回 400、数据库仍保留同步前的完整索引。

- [ ] **Step 2: 写图计算失败测试**

`test_document_graph.py` 直接测试纯函数：

```python
depths = shortest_reachable_depths(
    root_id="entry",
    outgoing={
        "entry": ["business", "shared"],
        "business": ["database", "shared"],
        "database": ["business"],
        "orphan": [],
    },
)
assert depths == {"entry": 1, "business": 2, "shared": 2, "database": 3}
assert "orphan" not in depths
```

链接解析测试覆盖 URL decode、fragment、HTTP、图片、纯锚点、目标不存在和逃逸 `../../outside.md`。

- [ ] **Step 3: 运行失败测试**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_document_graph.py tests/test_document_ingestion.py
```

Expected: FAIL，旧同步仍接受任意 `docs_dir`，且不存在图计算接口。

- [ ] **Step 4: 实现独立图算法**

`document_graph.py` 提供：

```python
def shortest_reachable_depths(
    *, root_id: str, outgoing: dict[str, list[str]]
) -> dict[str, int]:
    depths = {root_id: 1}
    pending = deque([root_id])
    while pending:
        source = pending.popleft()
        for target in outgoing.get(source, []):
            if target in depths:
                continue
            depths[target] = depths[source] + 1
            pending.append(target)
    return depths
```

同时提供：

```python
def project_entry_document(session: Session, project: Project) -> Document:
    document = session.scalar(
        select(Document).where(
            Document.project_id == project.id,
            Document.source_path == "AGENTS.md",
            Document.doc_type == "agent_index",
            Document.status == "active",
            Document.is_reachable.is_(True),
            Document.graph_depth == 1,
        )
    )
    if document is None:
        raise DocumentGraphError(f"Mapped AGENTS.md is not indexed for {project.slug}")
    return document


def is_direct_document_link(
    session: Session, *, source_document_id: str, target_document_id: str
) -> bool:
    link_id = session.scalar(
        select(DocumentLink.id)
        .where(
            DocumentLink.source_document_id == source_document_id,
            DocumentLink.target_document_id == target_document_id,
        )
        .limit(1)
    )
    return link_id is not None
```

入口必须是 Project 自己的 active、reachable、`source_path == "AGENTS.md"` 文档。

- [ ] **Step 5: 重写映射同步接口**

把入口改为：

```python
def sync_mapped_documents(session: Session, *, project: Project) -> DocumentSyncResult:
    document_root = resolve_document_root(project)
    markdown_paths = [document_root / "AGENTS.md", *_safe_docs_markdown_paths(document_root)]
    parsed = [_parse_required_document(path, document_root=document_root) for path in markdown_paths]
    _validate_unique_document_ids(session, project=project, documents=parsed)
    # upsert documents, rebuild links, compute depths, prune stale documents
```

实现要求：

- `source_path` 始终存相对文档项目根的 POSIX 路径，例如 `AGENTS.md`、`docs/database.md`。
- AGENTS 强制 `doc_type="agent_index"`。
- 缺 front matter 或 `doc_id` 抛出包含相对文件名的 `MarkdownSyncError`，不静默跳过。
- 链接只解析允许范围内普通 `.md` 文件；无效目标保存为 `target_document_id=None` 的 broken link。
- 根据 shortest depth 设置 `is_reachable` 和 `graph_depth`。
- stale 文档先删除相关 links；被 RetrievalHit 引用时设为 `status="removed"`、`is_reachable=False`、`graph_depth=None`，否则删除。
- 同步结果包含 `indexed_count`、`reachable_count`、`orphan_count`、`broken_link_count`、`pruned_count`。

- [ ] **Step 6: 修改 HTTP 同步为无路径请求**

`POST /api/projects/{slug}/documents/sync-local` 不再读取 `docs_dir` 或 `prune`。成功事务内写入：

```python
project.last_synced_at = datetime.now(UTC)
project.last_sync_status = "success"
project.last_sync_summary = result.summary
session.commit()
```

失败时：

```python
session.rollback()
project = session.scalar(select(Project).where(Project.slug == project_slug))
project.last_sync_status = "failed"
session.commit()
raise HTTPException(status_code=400, detail=str(exc))
```

失败不能清空同一映射已有的 `last_synced_at` 和旧完整索引。

- [ ] **Step 7: 验证同步、图和 tombstone**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_document_graph.py tests/test_document_ingestion.py tests/test_tracing.py
```

Expected: PASS；旧 Task 的 RetrievalHit 在文档被 prune 后仍能返回标题。

- [ ] **Step 8: 提交同步图**

```bash
git add backend/src/context_router/services/document_graph.py backend/src/context_router/services/markdown_sync.py backend/src/context_router/services/document_store.py backend/src/context_router/schemas/documents.py backend/src/context_router/api/documents.py backend/tests/test_document_graph.py backend/tests/test_document_ingestion.py backend/tests/test_tracing.py
git commit -m "feat: sync mapped document graphs"
```

## Task 4：映射文件实时读取

**Files:**
- Modify: `backend/src/context_router/services/local_document_reader.py`
- Modify focused tests in: `backend/tests/test_document_read.py`

- [ ] **Step 1: 写映射读取失败测试**

用已映射并已同步的 Project 测试：

```python
first = client.get("/api/documents/orders-entry", params={"untracked": True})
(document_root / "AGENTS.md").write_text(updated_markdown, encoding="utf-8")
second = client.get("/api/documents/orders-entry", params={"untracked": True})
assert first.json()["content_markdown"] != second.json()["content_markdown"]
assert "updated body" in second.json()["content_markdown"]
```

再测试删除文件后返回 404，即使 `Document.content_markdown` 仍有旧正文；无映射 Project、软链接文件和越界 source path 返回 400/404，不能回退 `root_path`。

- [ ] **Step 2: 运行测试并确认旧 reader 回退代码根或缓存**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_document_read.py -k "local or mapped or missing"
```

Expected: 至少一个测试 FAIL，因为旧 reader 使用 Project `root_path` 且允许缓存回退。

- [ ] **Step 3: 替换 source path 解析**

`resolve_document_source_path` 改为：

```python
def resolve_document_source_path(document: Document) -> Path:
    document_root = resolve_document_root(document.project)
    source = Path(document.source_path)
    if source.is_absolute() or ".." in source.parts:
        raise LocalDocumentAccessError(
            f"Mapped document source path is invalid: {document.source_path}"
        )
    candidate = document_root / source
    if candidate.is_symlink():
        raise LocalDocumentAccessError(f"Mapped document is a symlink: {document.source_path}")
    resolved = candidate.resolve(strict=False)
    _require_inside(resolved, document_root)
    return resolved
```

`read_document_content` 不再返回 `document.content_markdown`；没有映射、文件缺失或读取失败必须抛出明确异常。保留 front matter 去除逻辑。

- [ ] **Step 4: 运行完整 reader 测试并提交**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_document_read.py tests/test_document_ingestion.py
git add backend/src/context_router/services/local_document_reader.py backend/tests/test_document_read.py
git commit -m "feat: read mapped documents from live files"
```

Expected: 全部 PASS；文件删除用例不产生成功 read event。

## Task 5：prepare 固定返回 AGENTS 入口

**Files:**
- Modify: `backend/src/context_router/api/context.py`
- Modify: `backend/src/context_router/services/rendering.py`
- Replace focused tests in: `backend/tests/test_prepare_context.py`
- Modify: `backend/tests/test_e2e_flow.py`
- Modify: `backend/tests/test_mcp_server.py`

- [ ] **Step 1: 写 prepare 入口和错误失败测试**

准备一个有 AGENTS、第二层和孤立文档的已同步 Project，断言：

```python
response = client.post(
    "/api/context/prepare",
    json={"task": "修复订单超时", "cwd": "/srv/projects/orders", "source": "mcp"},
)
assert response.status_code == 200
assert [item["document_id"] for item in response.json()["documents"]] == ["orders-entry"]
```

分别测试未映射、映射后未同步、入口 tombstone、映射目录或 AGENTS 已删除；断言返回 409/404 且数据库没有新 Trace。

- [ ] **Step 2: 运行失败测试**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_prepare_context.py tests/test_mcp_server.py
```

Expected: 旧 prepare 返回检索排序结果，入口断言 FAIL。

- [ ] **Step 3: 用入口读取替换 retrieve_documents**

在 `prepare_context` 中先完成所有可用性检查，再创建 Trace：

```python
if project.last_synced_at is None:
    raise HTTPException(status_code=409, detail=f"Project has no synced document mapping: {project.slug}")
try:
    entry = project_entry_document(session, project)
    content = read_document_content(entry)
except (DocumentGraphError, LocalDocumentReadError) as exc:
    raise HTTPException(status_code=409, detail=str(exc)) from exc

result = ContextDocument(
    document_id=entry.id,
    title=entry.title,
    reason="Mapped AGENTS.md entry point",
    score=1.0,
    excerpt=content.strip().replace("\n", " ")[:180],
    rank=1,
)
```

只写一个 RetrievalHit。prepare event 的 `max_documents` 改为 `1` 并增加 `entry_document_id`。同一映射最近同步失败但 `last_synced_at` 仍存在时，允许使用上次完整索引；文件实时不可读仍报错。

- [ ] **Step 4: 更新 MCP/E2E 断言**

MCP 工具输入契约保持不变，但测试断言后端响应只包含 AGENTS。E2E 流程改成：映射 → sync → prepare → read AGENTS → read direct child → 查看 Task。

- [ ] **Step 5: 运行并提交 prepare**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_prepare_context.py tests/test_mcp_server.py tests/test_e2e_flow.py
git add backend/src/context_router/api/context.py backend/src/context_router/services/rendering.py backend/tests/test_prepare_context.py backend/tests/test_mcp_server.py backend/tests/test_e2e_flow.py
git commit -m "feat: route MCP prepare through mapped AGENTS"
```

Expected: 所有测试 PASS，prepare 不调用 `retrieve_documents`。

## Task 6：强制 MCP 沿实际链接逐层读取

**Files:**
- Modify: `backend/src/context_router/services/document_graph.py`
- Modify: `backend/src/context_router/api/documents.py`
- Modify: `backend/tests/test_document_read.py`
- Modify: `backend/tests/test_e2e_flow.py`

- [ ] **Step 1: 写访问策略失败测试**

覆盖以下矩阵：

```text
首次 read AGENTS + parent null                    -> 200 depth 1
首次 read 深层文档 + parent null                  -> 422
首次 read AGENTS + parent 非空                    -> 422
第二次 read direct child + 已读 parent            -> 200 depth parent+1
第二次 read direct child + parent null            -> 422
第二次 read 非 direct child                       -> 422
parent 属于另一 Trace                             -> 422
document 属于另一 Project                         -> 422
orphan / removed / broken target                  -> 422/404
Web untracked 预览 orphan                         -> 200 且无 read event
```

- [ ] **Step 2: 运行失败测试**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_document_read.py
```

Expected: 旧实现只检查 parent 是否读过，不检查 direct link，多个用例 FAIL。

- [ ] **Step 3: 实现明确的 MCP read 决策对象**

在 `document_graph.py` 增加：

```python
@dataclass(frozen=True)
class ReadDecision:
    depth: int
    read_mode: str

def authorize_mcp_read(
    session: Session,
    *,
    trace: Trace,
    document: Document,
    parent_document_id: str | None,
) -> ReadDecision:
    if document.project_id != trace.project_id:
        raise DocumentGraphError("Document does not belong to this task project")
    if document.status != "active" or not document.is_reachable:
        raise DocumentGraphError("Document is not reachable from mapped AGENTS.md")

    read_events = session.scalars(
        select(TraceEvent)
        .where(TraceEvent.trace_id == trace.id, TraceEvent.event_type == "read")
        .order_by(TraceEvent.created_at)
    ).all()
    if not read_events:
        if parent_document_id is not None:
            raise DocumentGraphError("The first document read cannot have a parent")
        entry_hit = session.scalar(
            select(RetrievalHit.id).where(
                RetrievalHit.trace_id == trace.id,
                RetrievalHit.document_id == document.id,
            )
        )
        if entry_hit is None or document.source_path != "AGENTS.md":
            raise DocumentGraphError("The first document read must be mapped AGENTS.md")
        return ReadDecision(depth=1, read_mode="entry_read")

    if parent_document_id is None:
        raise DocumentGraphError("A parent document is required after the entry read")
    parent_event = next(
        (
            event
            for event in reversed(read_events)
            if event.payload.get("document_id") == parent_document_id
        ),
        None,
    )
    if parent_event is None:
        raise DocumentGraphError("Parent document was not read in this task")
    if not is_direct_document_link(
        session,
        source_document_id=parent_document_id,
        target_document_id=document.id,
    ):
        raise DocumentGraphError("Requested document is not a direct link from its parent")
    return ReadDecision(
        depth=int(parent_event.payload.get("depth") or 1) + 1,
        read_mode="tree_read",
    )
```

实现顺序必须是：验证 Trace Project → 验证 active/reachable → 查询该 Trace 已有 read events → 首次读取对照 RetrievalHit 中唯一入口 → 后续要求 parent 已读且存在 direct `DocumentLink` → 返回实际 `depth`。所有失败在读取文件和写事件之前发生。

- [ ] **Step 4: 只返回有效下一层链接**

`_document_links(document, for_mcp=True)` 只返回：

```python
link.target_document_id is not None
and link.target_document is not None
and link.target_document.project_id == document.project_id
and link.target_document.status == "active"
and link.target_document.is_reachable
```

Web list/detail 使用 `for_mcp=False`，继续看到 broken link。

- [ ] **Step 5: 运行链路回归并提交**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_document_read.py tests/test_e2e_flow.py tests/test_tracing.py
git add backend/src/context_router/services/document_graph.py backend/src/context_router/api/documents.py backend/tests/test_document_read.py backend/tests/test_e2e_flow.py
git commit -m "feat: enforce linked MCP document reads"
```

Expected: 全部 PASS；Task 事件中的 parent/depth 与 AI 实际调用完全一致。

## Task 7：Project 和 Document API 健康状态

**Files:**
- Modify: `backend/src/context_router/schemas/projects.py`
- Modify: `backend/src/context_router/schemas/documents.py`
- Modify: `backend/src/context_router/api/projects.py`
- Modify: `backend/src/context_router/api/documents.py`
- Modify: `backend/tests/test_projects.py`
- Modify: `backend/tests/test_document_ingestion.py`

- [ ] **Step 1: 写响应字段失败测试**

Project summary 断言：

```python
assert body["docs_path"] == "order-docs"
assert body["mapping_status"] == "ready"
assert body["last_sync_status"] == "success"
assert body["sync_summary"] == {
    "indexed": 4,
    "reachable": 3,
    "orphan": 1,
    "broken_links": 2,
    "pruned": 0,
}
```

Document list 断言每项包含：

```python
{
    "is_reachable": True,
    "graph_depth": 2,
    "broken_link_count": 1,
    "links": [
        {
            "target_document_id": "orders-database",
            "target_path": "docs/database.md",
            "label": "Database",
            "relation_type": "markdown_link",
            "sort_order": 0,
            "is_broken": False,
        }
    ],
}
```

默认列表排除 `status="removed"`，显式 `status=removed` 可用于历史排查 API，但不出现在普通 Web Documents 视图。

- [ ] **Step 2: 运行失败测试**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_projects.py tests/test_document_ingestion.py
```

Expected: schema 缺少 mapping/graph 字段。

- [ ] **Step 3: 增加稳定的响应模型**

在 `schemas/projects.py` 定义：

```python
class SyncSummary(BaseModel):
    indexed: int = 0
    reachable: int = 0
    orphan: int = 0
    broken_links: int = 0
    pruned: int = 0
```

`ProjectResponse` 增加 `docs_path`、`mapping_status`、`last_synced_at`、`last_sync_status`、`sync_summary`。`mapping_status` 由服务端计算为 `not_mapped`、`not_synced`、`ready`、`invalid` 或 `sync_failed`，不在数据库重复保存。

`DocumentSummary` 增加 `is_reachable`、`graph_depth`、`broken_link_count`。`DocumentLinkSummary` 增加 `is_broken: bool`。

- [ ] **Step 4: 运行 API 回归并提交**

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_projects.py tests/test_document_ingestion.py tests/test_tracing.py
git add backend/src/context_router/schemas/projects.py backend/src/context_router/schemas/documents.py backend/src/context_router/api/projects.py backend/src/context_router/api/documents.py backend/tests/test_projects.py backend/tests/test_document_ingestion.py
git commit -m "feat: expose document mapping health"
```

Expected: 全部 PASS，Project 父子汇总只统计 active 当前索引，不包含 tombstone。

## Task 8：Projects 映射选择器和同步交互

**Files:**
- Create: `frontend/app/api/document-mappings/candidates/route.ts`
- Create: `frontend/app/api/projects/[slug]/document-mapping/route.ts`
- Create: `frontend/components/project-document-controls.tsx`
- Create: `frontend/lib/document-health.ts`
- Create: `frontend/lib/document-health.test.ts`
- Modify: `frontend/app/api/projects/[slug]/documents/sync-local/route.ts`
- Modify: `frontend/components/project-link-reload-button.tsx`
- Modify: `frontend/app/projects/page.tsx`
- Modify: `frontend/app/projects/[slug]/page.tsx`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: 写前端状态纯函数失败测试**

`document-health.test.ts`：

```typescript
test("mappingStatusLabel exposes actionable project states", () => {
  assert.equal(mappingStatusLabel("not_mapped"), "Not mapped");
  assert.equal(mappingStatusLabel("not_synced"), "Sync required");
  assert.equal(mappingStatusLabel("ready"), "Ready");
  assert.equal(mappingStatusLabel("sync_failed"), "Sync failed");
});

test("syncSummaryText includes reachable orphan and broken counts", () => {
  assert.equal(
    syncSummaryText({ indexed: 8, reachable: 6, orphan: 2, broken_links: 1, pruned: 0 }),
    "8 indexed · 6 reachable · 2 orphan · 1 broken",
  );
});
```

- [ ] **Step 2: 运行测试并确认模块不存在**

```bash
docker compose exec frontend npm test
```

Expected: FAIL，无法导入 `document-health`。

- [ ] **Step 3: 增加前端类型和纯函数**

`types.ts` 增加：

```typescript
export type SyncSummary = {
  indexed: number;
  reachable: number;
  orphan: number;
  broken_links: number;
  pruned: number;
};

export type DocumentMappingCandidate = {
  docs_path: string;
  markdown_count: number;
  mapped_project_slug: string | null;
};
```

Project 类型增加 `docs_path`、`mapping_status`、`last_synced_at`、`last_sync_status`、`sync_summary`。Document 类型增加图字段和 broken link 字段。

- [ ] **Step 4: 增加 BFF 代理**

候选 GET 代理到 `${API_BASE_URL}/api/document-mappings/candidates`；映射 PUT 原样代理到 `${API_BASE_URL}/api/projects/${slug}/document-mapping`。两者沿用现有 no-store、保留 status/content-type 和 502 JSON 错误模式。

同步 BFF 不再转发任意 request body，而是向后端 POST `{}`。

- [ ] **Step 5: 实现映射和同步控件**

`ProjectDocumentControls` 的公开 props：

```typescript
type ProjectDocumentControlsProps = Readonly<{
  project: ProjectSummary;
}>;
```

交互状态：

```typescript
type MappingState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "saving"; docsPath: string }
  | { status: "error"; message: string };
```

点击 `Map Documents` / `Change Mapping` 后获取候选。已被其他 Project 占用的 option disabled；保存 PUT `{docs_path}`，成功后关闭选择器、显示 `Mapping saved. Sync required.` 并 `router.refresh()`。Sync 只有 `docs_path` 存在且 mapping status 不是 invalid 时启用。

- [ ] **Step 6: 更新 Project 卡片和详情**

Project 卡片必须以这些标签展示：

```text
Code root
Document mapping
Status
Documents: indexed / reachable / orphan
Broken links
Last synced
```

保留 Documents、Tasks 按钮；使用新 controls 替换卡片中的旧单一同步按钮。详情页使用相同数据，不再把 root path 当文档同步目录。

- [ ] **Step 7: 运行前端测试、lint、build 并提交**

```bash
docker compose exec frontend npm test
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
git add frontend/app/api/document-mappings/candidates/route.ts frontend/app/api/projects/[slug]/document-mapping/route.ts frontend/app/api/projects/[slug]/documents/sync-local/route.ts frontend/components/project-document-controls.tsx frontend/components/project-link-reload-button.tsx frontend/app/projects/page.tsx frontend/app/projects/[slug]/page.tsx frontend/lib/document-health.ts frontend/lib/document-health.test.ts frontend/lib/types.ts frontend/lib/api.ts frontend/app/globals.css
git commit -m "feat: add project document mapping controls"
```

Expected: test、lint、isolated build 全部成功；正在运行的 dev CSS 不被 build 覆盖。

## Task 9：Documents 健康图和 Tasks 链路回归

**Files:**
- Modify: `frontend/lib/document-health.ts`
- Modify: `frontend/lib/document-health.test.ts`
- Modify: `frontend/components/document-graph.tsx`
- Modify: `frontend/components/document-table.tsx`
- Modify: `frontend/components/documents-view.tsx`
- Modify: `frontend/components/task-detail.tsx`
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: 写任意深度分组失败测试**

`document-health.test.ts` 增加：

```typescript
const grouped = groupDocumentsByDepth([
  document("entry", true, 1),
  document("business", true, 2),
  document("schema", true, 3),
  document("orphan", false, null),
]);
assert.deepEqual(grouped.levels.map((level) => level.depth), [1, 2, 3]);
assert.deepEqual(grouped.orphans.map((item) => item.id), ["orphan"]);
```

再断言 broken links 从所有文档链接中稳定排序输出 source、label、target_path。

- [ ] **Step 2: 运行测试并确认旧图只支持固定三层**

```bash
docker compose exec frontend npm test
```

Expected: FAIL，缺少 `groupDocumentsByDepth`。

- [ ] **Step 3: 重构图展示为同步深度层**

`DocumentGraph` 不再用 `pickRootDocument` 和固定 branch/leaves。它使用：

```typescript
const { levels, orphans, brokenLinks } = groupDocumentsByDepth(documents);
```

依次渲染 `Level 1`、`Level 2`、`Level N`，节点仍链接到现有预览；独立区域展示 Orphan documents 和 Broken links。图只表达同步得到的最短展示深度，不伪装成某个 Task 的实际 parent。

Document table 增加 `Reachability`、`Depth`、`Broken links` 三列。Documents toolbar 文案改为“从 AGENTS.md 查看可达层级、孤立文档和断链”。

- [ ] **Step 4: 确认 Tasks 只显示真实调用链**

Task detail 保留 prepare/read 顺序，但 prepare 候选文案改为 `Entry returned` / `Entry read`，不再暗示检索评分质量。read 节点继续显示服务端记录的 `parent_document_id` 和 `depth`，不能引用 Document 的 `graph_depth`。

- [ ] **Step 5: 验证并提交健康图**

```bash
docker compose exec frontend npm test
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
git add frontend/lib/document-health.ts frontend/lib/document-health.test.ts frontend/components/document-graph.tsx frontend/components/document-table.tsx frontend/components/documents-view.tsx frontend/components/task-detail.tsx frontend/app/globals.css
git commit -m "feat: visualize mapped document health"
```

Expected: 前端验证全部成功，任意图深度不会被截断为三层。

## Task 10：Docker 部署、产品文档和全量验证

**Files:**
- Create: `.env.example`
- Create: `document-sources/.gitkeep`
- Modify: `.gitignore`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/BUSINESS_FEATURES.md`
- Modify: `docs/FRONTEND_BACKEND_FLOW.md`
- Modify: `docs/STARTUP_GUIDE.md`
- Modify: `docs/DATABASE_INFO.md`

- [ ] **Step 1: 写 compose 配置验证预期**

本地默认配置：

```text
CONTEXT_ROUTER_DOCUMENTS_HOST_ROOT=./document-sources
CONTEXT_ROUTER_DOCUMENTS_CONTAINER_ROOT=/documents
```

`.gitignore` 忽略 `document-sources/*`，但保留 `!document-sources/.gitkeep`。服务器通过 `.env` 把 host root 改为 `/srv/ai-docs`，不用改代码或 compose。

- [ ] **Step 2: 增加只读 bind mount**

`docker-compose.yml` backend：

```yaml
environment:
  CONTEXT_ROUTER_DOCUMENTS_HOST_ROOT: ${CONTEXT_ROUTER_DOCUMENTS_HOST_ROOT:-./document-sources}
  CONTEXT_ROUTER_DOCUMENTS_CONTAINER_ROOT: ${CONTEXT_ROUTER_DOCUMENTS_CONTAINER_ROOT:-/documents}
volumes:
  - .:/app
  - /Users/conchi/workforce:/workspace:ro
  - ${CONTEXT_ROUTER_DOCUMENTS_HOST_ROOT:-./document-sources}:${CONTEXT_ROUTER_DOCUMENTS_CONTAINER_ROOT:-/documents}:ro
```

后端业务只使用 container root。Projects 页面显示相对 `docs_path`，不暴露或允许编辑任意容器绝对路径。

- [ ] **Step 3: 更新产品和开发文档**

所有文档统一写成：

```text
Codex cwd
  -> Project.root_path 识别代码项目
  -> Project.docs_path 定位 /documents 下的文档项目
  -> prepare 只返回 AGENTS.md
  -> read 沿同步链接逐层读取
  -> Tasks 展示实际 parent/depth
```

删除“文档仍在各自代码项目目录”“prepare 最多返回三份候选”和“Sync 接收 docs_dir”的旧描述。`DATABASE_INFO.md` 记录 migration 字段和 tombstone 状态；`STARTUP_GUIDE.md` 记录服务器只需配置 host root 并用 Compose 重建 backend。

- [ ] **Step 4: 重建并验证只读挂载**

```bash
docker compose up -d --force-recreate backend frontend
docker compose exec backend test -d /documents
docker compose exec backend sh -c 'test ! -w /documents'
docker compose exec backend uv run alembic upgrade head
```

Expected: `/documents` 存在且不可写；migration 成功。

- [ ] **Step 5: 运行后端全量验证**

```bash
docker compose exec backend uv run --extra dev pytest -q
docker compose exec backend uv run --extra dev ruff check .
docker compose exec backend uv run --extra dev ruff format --check .
```

Expected: pytest 全部 PASS；ruff check/format exit 0。

- [ ] **Step 6: 运行前端全量验证**

```bash
docker compose exec frontend npm test
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

Expected: test 全部 PASS；lint/build exit 0。

- [ ] **Step 7: 运行浏览器验收**

在 `http://localhost:49174/projects` 完成：

```text
创建或选择 Project
→ 打开 Map Documents
→ 选择未占用候选
→ 保存后看到 Sync required
→ 点击 Sync Documents
→ 卡片显示 indexed/reachable/orphan/broken
→ Documents 图显示 AGENTS、层级、orphan、broken links
```

随后通过 MCP 执行 prepare → read AGENTS → read child，确认 `/tasks` 外层显示任务、详情显示真实 parent/depth。

- [ ] **Step 8: 提交部署和文档**

```bash
git add .env.example .gitignore document-sources/.gitkeep docker-compose.yml README.md AGENTS.md docs/BUSINESS_FEATURES.md docs/FRONTEND_BACKEND_FLOW.md docs/STARTUP_GUIDE.md docs/DATABASE_INFO.md
git commit -m "docs: document mapped MCP workflow"
```

- [ ] **Step 9: 最终变更检查**

```bash
git status --short
git log --oneline --decorate -12
```

Expected: worktree clean；本功能形成按数据库、映射、同步、读取、prepare、read policy、API、前端、部署拆分的可审查提交序列。

## 完成定义

- Project 通过 `root_path` 识别代码目录，通过唯一 `docs_path` 找到文档目录。
- 服务器文档目录以只读方式挂载，Web 不能提交任意绝对路径。
- 同步范围严格为根 `AGENTS.md` 和 `docs/**/*.md`，所有文件强制稳定 `doc_id`。
- Web 能看到映射、同步时间、reachable、orphan、broken links 和 pruned。
- prepare 只返回 AGENTS；MCP read 只能沿同一 Trace 已读 parent 的直接链接继续。
- 文件正文更新可实时读取；新增、删除、元数据和链接变更需要手动同步。
- 删除文档不会破坏旧 Task 候选和 read event 展示。
- Tasks 不记录反馈、成功率、不读原因或停止原因。
- 后端全量 pytest/ruff、Alembic、前端 test/lint/build 和浏览器验收全部通过。
