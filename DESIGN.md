---
version: "1.0"
name: Agent Context Local Console
description: A compact local developer console for browsing workspace context, database access, traces, and controlled document/deploy synchronization.
colors:
  primary: "#1F5F4A"
  primary-soft: "#E2EEE9"
  on-primary: "#FFFFFF"
  canvas: "#F5F5F2"
  surface: "#FFFFFF"
  surface-soft: "#FAFAF8"
  ink: "#20211F"
  muted: "#6D706B"
  hairline: "#D9DBD5"
  hairline-strong: "#B7BBB3"
  focus: "#1F5F4A"
  success: "#1F5F4A"
  warning: "#8A6418"
  error: "#A43A34"
  error-soft: "#F8E7E5"
typography:
  title-lg:
    fontFamily: "Inter, PingFang SC, Microsoft YaHei, system-ui, sans-serif"
    fontSize: 32px
    fontWeight: 700
    lineHeight: 40px
  title-md:
    fontFamily: "Inter, PingFang SC, Microsoft YaHei, system-ui, sans-serif"
    fontSize: 21px
    fontWeight: 650
    lineHeight: 28px
  body:
    fontFamily: "Inter, PingFang SC, Microsoft YaHei, system-ui, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 22px
  label:
    fontFamily: "Inter, PingFang SC, Microsoft YaHei, system-ui, sans-serif"
    fontSize: 14px
    fontWeight: 650
    lineHeight: 20px
  caption:
    fontFamily: "Inter, PingFang SC, Microsoft YaHei, system-ui, sans-serif"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 18px
  code:
    fontFamily: "SFMono-Regular, Consolas, monospace"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 20px
rounded:
  sm: 6px
  md: 9px
  lg: 13px
  card: 20px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  2xl: 32px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.card}"
    padding: "{spacing.xl}"
  dialog:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: "{spacing.xl}"
  code-path:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.muted}"
    typography: "{typography.code}"
    rounded: "{rounded.sm}"
    padding: "{spacing.sm}"
  interface-requested-badge:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: "2px 7px"
    behavior: "接口转发列表（包括全部接口视图）按最近请求时间倒序；有请求日志的接口显示‘已请求’，完整时间通过悬浮提示和无障碍标签提供；未请求接口按路径和请求方式稳定排序。"
  error-banner:
    backgroundColor: "{colors.error-soft}"
    textColor: "{colors.error}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
---

## Overview

Agent Context is a local developer console. Its primary users inspect workspace context, data-source authorization, MCP traces, and controlled runtime assets. The interface is information-dense but should remain calm: neutral surfaces carry hierarchy, the project green marks primary actions and focus, and destructive replacement is expressed with explicit Chinese copy rather than decorative status systems.

### Design principles

1. Keep the current console hierarchy: sticky top application header, compact horizontal primary navigation, two-column workspace cards, and focused detail views.
2. Prefer direct actions and short confirmations over multi-step state machines. Show only state required to recover from an error.
3. Treat local paths and file replacement as operational data: render paths in monospace, name the exact affected directories, and never rely on color alone.
4. Preserve keyboard access, visible focus, Chinese readability, and responsive single-column behavior.
5. Container-table project updates stay in the row action column: Fast and Full reuse the registered project runtime profiles, expose progress through the button label, and never rely on container-name mapping.

## Reference decision

Three references were compared against the existing React/CSS console.

| Candidate | Score | Decision |
|---|---:|---|
| Linear | 89/100 | Primary. Its compact developer-tool hierarchy, restrained accent usage, surface ladder, and hairline borders fit the existing cards and dialogs. |
| HashiCorp | 80/100 | Rejected as a full direction. Operational clarity fits, but its multi-product color identity would add noise and conflict with the project green. |
| Sentry | 68/100 | Rejected. Strong illustration, lime/pink accents, and marketing personality conflict with a quiet local control plane. |

```yaml
reference_decision:
  primary:
    source: "VoltAgent/awesome-design-md: linear.app"
    ref: "main; sha256 30bd30e72c48a16e4bdbd010f2d1c85fab657c6fae3cc85389399aab10f9cb5f"
    score: 89
    borrow:
      - compact technical hierarchy
      - restrained single accent
      - surface and hairline depth
      - monospace only for paths and code
    adapt:
      - retain the project-owned green accent
      - retain Chinese system font fallbacks
      - retain existing card dimensions and navigation
  adapt_for_chinese:
    - allow long workspace names to wrap without clipping controls
    - allow paths to wrap anywhere while retaining copyable full text
    - keep destructive confirmation copy literal and unambiguous
  avoid:
    - logos
    - proprietary fonts
    - lavender brand color
    - product screenshots and brand copy
    - Sentry illustrations and lime/pink identity
    - HashiCorp per-product color system
    - pixel-for-pixel replication
```

## Colors and depth

The CSS variables in `frontend/app/globals.css` are the implementation source. New components must reuse them. Cards and dialogs use surface changes, one-pixel borders, and the existing restrained shadow; no new gradients, glow, or accent palette is allowed. Green is reserved for selection, focus, and the primary action. Error red is reserved for destructive warnings and failures.

## Typography and paths

Use the existing legal system stack. Chinese UI copy must use natural phrases and may wrap between semantic units. Use monospace only for filesystem paths, IDs, SQL, JSON, and log/code output. Workspace names use the title scale; operational descriptions use body or caption sizes.

## Layout and responsive behavior

| Mode | Width | Required behavior |
|---|---:|---|
| Narrow mobile | 375px | Single-column cards; toolbar actions wrap; dialogs use the available viewport; buttons remain at least 40px tall. |
| Tablet | 768px | Single-column cards and stacked detail headers; no horizontal page overflow. |
| Desktop | 1440px | Sticky top application header with the brand at left and the complete primary navigation in one horizontal row; two-column workspace grid; dialogs remain bounded and centered. |

Six primary navigation groups live in the top application header on every page; do not restore a permanent left rail. Keep them in this fixed order: 工作空间、数据管理、接口管理、AI可视化、系统中心、配置管理. At narrow widths the brand occupies the first row and the labelled navigation occupies a second, horizontally scrollable row. Keep labels visible, preserve the DOM/menu order, and never allow the navigation to create page-level horizontal overflow.

Every primary destination uses the Document Statistics page as the outer-content gutter reference: 24px from each viewport edge on desktop, 16px on tablet and narrow mobile. This gutter belongs to the shared application content shell; page roots must not add a second horizontal outer padding. Internal card, panel, table, and dialog padding remains component-specific.

At 200% zoom the interface must collapse without hiding the primary or cancel action. Long paths wrap and never force horizontal page scrolling.

## Components and interaction states

| Component | Implementation | Required behavior |
|---|---|---|
| Workspace card | `.workspace-card` | Show the locally resolved primary path, shared-reader count, refresh action, and enter action. No status-badge matrix. |
| Workspace detail header | `.workspace-detail-header` | Show only the workspace name and root path, with a circular close action fixed at the header's top-right. Do not repeat the workspace label, type, or a textual back action. |
| Workspace container view | `WorkspaceContainersModal` | Open full-screen from each workspace card and list only containers carrying that workspace's runtime label. Use compact single-line rows and backend/frontend tabs with backend selected first. Show literal state, project, image, and ports with loading, empty, and recoverable error states. Each row offers a log action that opens one bounded live SSE terminal below the table; show literal connection state, preserve stdout/stderr labels, default to auto-scroll, and close the prior stream when selection, tab, or dialog changes. Footer batch actions restart or stop only the selected backend/frontend tab, require explicit confirmation, disable navigation while running, and report success and failure counts before refreshing the list. |
| Local mapping reload | workspace dashboard toolbar | One action reloads the project-local YAML; loading prevents duplicate submission; a persistent error explains how to recover. |
| Shared-file dialog | `WorkspaceSharedFiles` | Show primary root and the two fixed directories. Offer database-to-local and local-to-database full replacement with a single explicit confirmation step. |
| Confirmation dialog | existing management modal primitives | State which side is replaced and list `docs/` and `deploy/context-router/`; cancel is first, replacement is last. |
| Error banner | `.error-banner` | Use `role=alert`, preserve the error until the user retries or closes the containing dialog. |
| System guide manager | `.system-guide-*` | Use the existing sidebar and list/editor split. Render one fixed read-only menu item per tool from the live FastMCP `tools/list` registry; selecting an item shows only that tool definition in source/tree views and exposes no save action. Use concise project-owned Chinese descriptions in this human-facing view while leaving the MCP registry’s original English descriptions unchanged for AI clients. Persisted system-guide JSON remains editable in source mode with one “保存内容” action only—no browser create, delete, key, ordering, prepare policy, enabled, or publishing controls. |
| Workspace environment details | `/workspaces/[workspaceId]/mcp-environments` | Open from the Workspace card’s environment action. The Workspace owns a dynamic environment list and always starts with `local`; do not render globally hard-coded TEST/UAT options. Put one labelled environment select in the page header’s upper-right and use its value as the single view context for every section below. Show the selected environment’s Nacos mapping, generic environment content status, environment-aware MCP flow, and data-source summary. Data sources belong to physical connections and databases; the environment section only shows which existing project database links are associated with the selected environment. A one-environment Workspace keeps the select visible but disabled. Preserve loading, empty, recoverable error, long Chinese text, and 40px target states at narrow widths. |
| Relation record explorer | `.relation-record-*` | Use one full-width card per directly related table. Search only columns already present on published relation edges. Tables retain all columns inside a card-local horizontal scroller; 1:N and N:1 cards show three rows per server page with a compact first/previous/page/next/last pager, while 1:1 cards omit pagination and use a bounded vertical scroller when needed. Column comments must be available by hover and keyboard focus. Never allow the grid to create page-level horizontal overflow. |
| Interface forwarding manager | `.interface-forwarding-*` | Keep the service tree and interface list in one compact split panel, scoped by the selected Workspace. The interface table has three fixed-layout information columns—interface name, Controller name, and path with the HTTP method inline—plus one compact operation column containing test and detail actions. The interface-name column stays deliberately narrow so more width is available for paths. It must never create horizontal page or panel scrolling; truncate long values with hover text and keyboard access. Testing opens directly from the list in its own bounded dialog. Clicking the name or detail action opens a detail dialog with three tabs: request logs, the immutable imported interface contract, and read-only retrieval semantics. The contract tab contains method/path, Controller, Operation ID, original description, table effects, and request/response schemas. The retrieval-semantics tab renders the compact persisted semantic JSON used by hybrid search; schema paths, interface-family data, source/confidence, and version metadata remain inside one collapsed advanced-governance disclosure. Do not restore the legacy entity/action/scenario/example/CRUD editor or duplicate those fields in the contract tab. Empty, bootstrap, stale, and LLM-enriched semantic states use literal text. Table effects use compact bordered rows with a literal effect label, logical database/table identifier, evidence method, and bounded source path; the UI displays the persisted effects directly and does not infer visibility from a duplicate CRUD field. The forwarding configuration is one combined read-only detail view: environments are projections of the selected Workspace environment registry; each Workspace environment may contain multiple named forwarding addresses, including different names sharing the same base URL; every address binds to exactly one imported interface service and owns multiple request identities containing login account, a concise role label, and request header. In the environment detail, addresses are a read-only summary rather than a filter; group identities by login account plus role so the same account can appear as separate role cards, and list every mapped address, service, URL, and request header inside its identity card. Render the role beside the account as a compact accent badge. The browser provides no address or identity create, edit, or delete controls; those records are maintained through the validated AI/operations API. Interface testing only offers addresses bound to that interface's service. JSON and URLs use monospace. |
| Value mapping manager | `.value-mapping-*` | Keep “映射管理” as a Workspace-scoped read-only split view: a searchable mapping list on the left and structured mapping details on the right. A mapping shows one stable business value, its aliases, one database-alias/table/column resolver, and the interface parameters that consume it. The browser provides no create, edit, save, delete, bind, unbind, or preview controls; all writes and preview operations remain available only through the validated AI/operations API. Keep the keyword field and its non-wrapping search button in one horizontal row at every breakpoint. Do not expose raw SQL. Loading, empty, and recoverable error states remain explicit. At tablet and narrow widths the list and details stack, field grids collapse to one column, and code-like identifiers wrap without page-level overflow. |
| Grouped application navigation | `.app-nav-dropdown*` | Keep 工作空间 as the only direct destination. Group the remaining destinations in this fixed order: 数据管理（数据源、表关联、关联数据）, 接口管理（接口转发、映射管理）, AI可视化（任务可视化、数据可视化、接口可视化、日志可视化）, 系统中心（调用链路、系统文档、文档统计）, 配置管理（AI 配置）. Every group uses the same click, active-parent, outside-click, Escape, focus restoration, and arrow-key behavior. Use a viewport-positioned popup so narrow horizontally scrolling navigation cannot clip it. 四个 AI 可视化入口使用彼此独立的页面，并以内部 `task_id` 相互跳转。 |
| AI task visualization | `.task-visualization-*`, existing visualization split primitives | `AI可视化 / 任务可视化` 是 AI 工作结果的只读任务总览，不创建第二套任务或执行系统。列表按最近活动倒序聚合30天内真实 MCP 调用、数据条件、接口日志和容器错误记录；详情显示脱敏后的任务范围、统计、结构化 AI 结论以及最新在前的游标时间线。链路健康状态固定展示 MCP、数据、接口、日志和结论五项，状态只由当前任务真实记录推导；“未使用”不能表述为故障或系统不可用，日志无记录也不能表述为没有错误。AI 仅通过 MCP 更新同一 `task_id` 的结论，浏览器不编辑结论、不自动轮询。关联按钮只在对应记录存在时显示，并可带任务范围进入原有页面，再返回任务。 |
| AI interface visualization | `.interface-visualization-*`, `.interface-request-*` | `AI可视化 / 接口可视化` 只读取真实接口转发日志，不创建重复记录，也不提供执行或审批动作。页面使用不透明游标展示30天内的最新请求，允许按 Workspace、内部任务和成功状态筛选，并在双栏详情中展示脱敏后的最终请求、响应及参数证据。加载、无记录、工作空间失败及重试、详情错误、成功、失败和截断都使用文字明确表达。页面不自动轮询，不打断当前详情。 |
| AI data visualization | `.data-visualization-*` | `AI可视化 / 数据可视化` 按 Workspace、环境和可选内部任务读取最近保存的结构化关联查询条件。历史选择只回填，不自动查询；结果复用既有有界关联数据 API，并对敏感列脱敏。记录显示待查询、成功或失败执行摘要，但不持久化完整业务结果。历史弹窗锁定键盘焦点并在关闭后恢复触发按钮；页面不修改数据管理下的关联数据，也不自动轮询。 |
| AI log visualization | `.interface-visualization-*`, `.log-*` | `AI可视化 / 日志可视化` 只展示 AI 从当前任务 Workspace 已注册 Docker 容器中确认的有界错误快照。页面使用不透明游标展示30天内记录，列表只显示错误标题、级别、容器、来源、任务环境和时间；详情展示统一脱敏的错误上下文并支持复制脱敏内容。页面只读且不自动轮询；无匹配关键词错误、容器不可访问或未注册时不生成记录。 |
| Shared configuration | `.shared-ai-*` | 配置管理左侧按固定顺序展示六项：数据库配置、AI 配置、本地 CLI 配置、MinIO 配置、图片模型配置、Runtime Contract。每项使用独立语义图标和左对齐标签；选中态无四周边框和圆角，使用整块柔和背景及贴左贯穿高度的强调竖线。颜色、字体与焦点环继续使用本项目 token。右侧统一使用标题、计数、fieldset 和双列只读字段。数据库密码、AI/API Key、MinIO 凭据与 Runtime Contract 密钥默认遮罩，点击眼睛或显式按钮才显示，切换菜单或重新加载后恢复遮罩。只有 AI 默认项写入本地控制面；其余配置实时读取配置中心。AI Provider 被配置中心删除时自动回退并提示。 |

Buttons cover default, hover, focus, disabled, and loading. Critical replacement results use an inline persistent success or error message, not a transient toast. Dialogs trap focus, close on Escape only while idle, and restore focus to the trigger.

## Product rules for this change

- `workspaces.local.yaml` is edited outside the browser and controls local visibility and path mapping.
- Missing or hidden mappings do not fall back to database paths.
- The primary workspace directory owns `docs/` and `deploy/context-router/`.
- Additional reader paths can prepare and read the primary directory's documents but cannot use database or runtime tools.
- File synchronization is full replacement in either direction. No revisions, conflicts, automatic merge, or diff UI are introduced.
- System guides are central Context Router JSON documents. The browser only updates the selected document's JSON body; document creation, deletion and metadata remain outside the browser management surface.
- Each Workspace owns its environment keys; `local` is created as the default, while `test`, `uat`, or any other valid key only exists when configured for that Workspace. Environment-aware MCP tools inherit the task environment when their optional argument is omitted; a new task without an explicit environment starts in `local`, and an explicit argument wins.
- One environment maps to at most one Nacos profile. Database records are environment-neutral: an environment associates existing project database links with logical MCP aliases, and multiple environments may reuse the same link. The environment details page is a browser-readable projection of this relationship; configuration writes remain in the validated local AI/operations API.
- The Workspace detail no longer has a separate data-source-summary tab. Environment-filtered data sources live on the environment details page so the header select and displayed assignments cannot drift apart.
- Business-value mappings are Workspace-scoped and reference a stable read-only database `mcp_alias`, never an environment-specific physical address. AI/operations preview resolves that alias through an explicitly selected Workspace environment; the browser does not expose manual preview controls. The browser may maintain structured mapping records, aliases and interface-parameter bindings, but it cannot save arbitrary SQL or database credentials.

## Accessibility and localization

- Use semantic buttons and dialogs, accessible labels, visible focus, and a logical keyboard order.
- Normal text must meet WCAG AA contrast; color must be paired with literal success/error wording.
- Respect `prefers-reduced-motion`; this flow does not require animation.
- Test long Chinese workspace names, long unbroken paths, and mixed Chinese/Latin labels.
- System guide title content is edited as JSON source. Search and JSON text input must preserve Chinese IME composition; validation occurs after input changes or explicit save, never on individual composition keystrokes.

## Known gaps and decisions

- The project supports the existing theme only; no new theme switch is introduced.
- The local YAML remains intentionally outside browser editing scope.
- The UI references are principles only. No external assets or proprietary typefaces are included.
