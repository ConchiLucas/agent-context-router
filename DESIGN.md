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

1. Keep the current console hierarchy: sidebar, compact toolbar, two-column workspace cards, and focused detail views.
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
  secondary:
    source: "OpenMetadata lineage explorer"
    scope: "table relation graph interaction only"
    borrow:
      - select one root entity before drawing the graph
      - keep evidence available from the selected relation
      - label empirical relation semantics explicitly
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
| Desktop | 1440px | Existing sidebar and two-column workspace grid; dialogs remain bounded and centered. |

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
| Table relation explorer | `.table-relation-*` | Use a workspace selector, exact-table search, a central undirected graph, and a full-width evidence panel below the graph. Do not expose TEST/UAT switching: this derived view always uses the one table-relation default database selected for each eligible backend project and shows the configured/eligible count literally. LOCAL/TEST/UAT remain relevant to database query, middleware, and deployment tools, not this page. Every edge is labelled “SQL 等值关联”; selecting an edge reveals source SQL path, equality expression, and bounded statement evidence. Template-derived evidence adds one compact warning-colored text line naming its workspace Profile and ordered rules; native SQL evidence has no extra badge. Never imply foreign keys, upstream/downstream, ownership, or lineage. Rebuild uses one project selector that defaults to the first “全部项目” option and one primary action: selecting a configured backend project updates only that project, while selecting “全部项目” rebuilds every configured default-database target. Each project option appends its literal current build state; when one or more projects fail, show only those failures in a compact list below the aggregate status, including a concise reason and a control that selects the project for retry. Do not add a second full-rebuild button, automatic changed-file detection, or multi-project `project_ids` submission. A secondary “SQL 白名单” action is available for “全部项目” or one selected project and opens one bounded dialog with the same project chips. Two outer kind buttons split system rules: “没有分析价值” (DDL, single-or-zero-table query, write-only, non-relational initialization, missing table/column, invalid SQL) still skips whole files; “解析器暂不支持” (complex SQL, CTE/derived, OR, non-equality, correlated subquery) is view-only and does not skip scan. Inner tabs reuse the existing rule-card pattern, and each SQL file is assigned to exactly one tab. After a project update, those assignments are stored with the current generation; opening a tab reads the snapshot instead of rescanning every `.sql` file, and opening a file reads that path on demand. Project-relative exact `.sql` paths stay per project, “全部项目” shows grouped read-only path lists, and current attention files may be merged into the draft only after a project is selected and before one explicit “保存并更新当前项目” action. The dialog must state that an excluded file's valid relations are also ignored. Desktop presents each kind's tabs in rows of three; at mobile and 200% zoom they stack without horizontal overflow. Both scopes share explicit building, empty, ready, partial, warning, stale/default-missing, and failed states and are disabled until every eligible backend project has a default database. Always show ready/total target counts. The status bar emphasizes only diagnostics that require attention; expected exclusions remain available in the inline diagnostics panel under a neutral “正常忽略” filter. The panel retains disposition chips, project-count chips, reason chips, source-path/expression search, occurrence counts, bounded records, and literal “源码错误 / 预处理边界 / 元数据未确认 / 安全跳过” classification text; project and reason filters reuse the same compact pill pattern, and warning color must be paired with literal text. |

Buttons cover default, hover, focus, disabled, and loading. Critical replacement results use an inline persistent success or error message, not a transient toast. Dialogs trap focus, close on Escape only while idle, and restore focus to the trigger.

## Product rules for this change

- `workspaces.local.yaml` is edited outside the browser and controls local visibility and path mapping.
- Missing or hidden mappings do not fall back to database paths.
- The primary workspace directory owns `docs/` and `deploy/context-router/`.
- Additional reader paths can prepare and read the primary directory's documents but cannot use database or runtime tools.
- File synchronization is full replacement in either direction. No revisions, conflicts, automatic merge, or diff UI are introduced.
- System guides are central Context Router JSON documents. The browser only updates the selected document's JSON body; document creation, deletion and metadata remain outside the browser management surface.

## Accessibility and localization

- Use semantic buttons and dialogs, accessible labels, visible focus, and a logical keyboard order.
- Normal text must meet WCAG AA contrast; color must be paired with literal success/error wording.
- Respect `prefers-reduced-motion`; this flow does not require animation.
- Test long Chinese workspace names, long unbroken paths, and mixed Chinese/Latin labels.
- System guide title content is edited as JSON source. Search and JSON text input must preserve Chinese IME composition; validation occurs after input changes or explicit save, never on individual composition keystrokes.

## Known gaps and decisions

- The project supports the existing theme only; no new theme switch is introduced.
- The table-relation SQL whitelist intentionally uses a full-screen inspection dialog at the user's request. It retains the existing surface, border, typography, focus and responsive rules; system-rule cards are interactive filters that reveal file paths and source SQL without changing scan state.
- The local YAML remains intentionally outside browser editing scope.
- The UI references are principles only. No external assets or proprietary typefaces are included.
