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
| Desktop | 1440px | Existing sidebar and two-column workspace grid; dialogs remain bounded and centered. |

At 200% zoom the interface must collapse without hiding the primary or cancel action. Long paths wrap and never force horizontal page scrolling.

## Components and interaction states

| Component | Implementation | Required behavior |
|---|---|---|
| Workspace card | `.workspace-card` | Show the locally resolved primary path, shared-reader count, refresh action, and enter action. No status-badge matrix. |
| Local mapping reload | workspace dashboard toolbar | One action reloads the project-local YAML; loading prevents duplicate submission; a persistent error explains how to recover. |
| Shared-file dialog | `WorkspaceSharedFiles` | Show primary root and the two fixed directories. Offer database-to-local and local-to-database full replacement with a single explicit confirmation step. |
| Confirmation dialog | existing management modal primitives | State which side is replaced and list `docs/` and `deploy/context-router/`; cancel is first, replacement is last. |
| Error banner | `.error-banner` | Use `role=alert`, preserve the error until the user retries or closes the containing dialog. |
| System guide manager | `.system-guide-*` | Use the existing sidebar and a list/editor split. JSON source is editable; tree mode is a formatted read-only preview. The browser exposes one “保存内容” action only—no create, delete, key, ordering, prepare policy, enabled, or publishing controls. |

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
- The local YAML remains intentionally outside browser editing scope.
- The UI references are principles only. No external assets or proprietary typefaces are included.
