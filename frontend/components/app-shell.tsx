"use client";

import {
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { DataSourceDashboard } from "@/components/data-source-dashboard";
import { DocumentReadStats } from "@/components/document-read-stats";
import { TraceExplorer } from "@/components/trace-explorer";
import { SystemGuideManager } from "@/components/system-guide-manager";
import { TableRelationExplorer } from "@/components/table-relation-explorer";
import { RelationRecordExplorer } from "@/components/relation-record-explorer";
import { WorkspaceDashboard } from "@/components/workspace-dashboard";
import { InterfaceForwardingManager } from "@/components/interface-forwarding-manager";
import { ValueMappingManager } from "@/components/value-mapping-manager";
import { SharedAiConfigManager } from "@/components/shared-ai-config-manager";

type Section =
  | "workspaces"
  | "data-sources"
  | "table-relations"
  | "relation-records"
  | "interface-forwarding"
  | "value-mappings"
  | "shared-ai-config"
  | "interface-visualization"
  | "data-visualization"
  | "log-visualization"
  | "traces"
  | "system-guides"
  | "doc-stats";

type NavKind =
  | Section
  | "data-management"
  | "interface-management"
  | "configuration-management"
  | "ai-visualization"
  | "system-center";

interface NavMenuItem {
  section: Section;
  label: string;
}

const dataManagementItems: NavMenuItem[] = [
  { section: "data-sources", label: "数据源" },
  { section: "table-relations", label: "表关联" },
  { section: "relation-records", label: "关联数据" },
];

const interfaceManagementItems: NavMenuItem[] = [
  { section: "interface-forwarding", label: "接口转发" },
  { section: "value-mappings", label: "映射管理" },
];

const configurationManagementItems: NavMenuItem[] = [
  { section: "shared-ai-config", label: "AI 配置" },
];

const visualizationItems: NavMenuItem[] = [
  { section: "interface-visualization", label: "接口可视化" },
  { section: "data-visualization", label: "数据可视化" },
  { section: "log-visualization", label: "日志可视化" },
];

const systemCenterItems: NavMenuItem[] = [
  { section: "traces", label: "调用链路" },
  { section: "system-guides", label: "系统文档" },
  { section: "doc-stats", label: "文档统计" },
];

const visualizationSections = visualizationItems.map((item) => item.section);

function NavIcon({ kind }: { kind: NavKind }) {
  if (kind === "workspaces") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 6.5h6l1.7 2H20v9.5H4z" />
        <path d="M4 6.5V5h6l1.7 2H20v1.5" />
      </svg>
    );
  }
  if (kind === "data-sources" || kind === "data-management") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <ellipse cx="12" cy="5.5" rx="7.5" ry="3" />
        <path d="M4.5 5.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6" />
        <path d="M4.5 11.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6" />
      </svg>
    );
  }
  if (kind === "table-relations") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="3" y="4" width="7" height="5" rx="1" />
        <rect x="14" y="15" width="7" height="5" rx="1" />
        <path d="M6.5 9v5.5a2 2 0 0 0 2 2H14" />
        <path d="M11.5 14.5 14 17l-2.5 2.5" />
      </svg>
    );
  }
  if (kind === "relation-records") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="3" y="4" width="7" height="5" rx="1" />
        <rect x="14" y="15" width="7" height="5" rx="1" />
        <path d="M6.5 9v5.5a2 2 0 0 0 2 2H14" />
        <path d="M14 6h6M17 3v6M4 20h7" />
      </svg>
    );
  }
  if (kind === "system-guides" || kind === "system-center") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6 3.5h9l3 3V20.5H6z" />
        <path d="M15 3.5v3h3M9 10h6M9 14h6M9 18h4" />
      </svg>
    );
  }
  if (kind === "interface-forwarding" || kind === "interface-management") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 7h11M12 4l3 3-3 3M20 17H9M12 14l-3 3 3 3" />
      </svg>
    );
  }
  if (kind === "value-mappings") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M8 7h8M8 17h8" />
        <circle cx="5" cy="7" r="2" />
        <circle cx="19" cy="17" r="2" />
        <path d="M7 8.5 17 15.5" />
      </svg>
    );
  }
  if (kind === "doc-stats") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 19.5h16M6 16v-4M10 16V9M14 16v-7M18 16V5" />
      </svg>
    );
  }
  if (kind === "ai-visualization") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 19.5h16M6.5 16v-4M11 16V7.5M15.5 16v-6M20 6.5v-2M19 5.5h2" />
      </svg>
    );
  }
  if (kind === "configuration-management" || kind === "shared-ai-config") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="4" y="4" width="16" height="16" rx="3" />
        <path d="M8 9h8M8 13h8M8 17h5" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="6" cy="6" r="2" />
      <circle cx="18" cy="8" r="2" />
      <circle cx="9" cy="18" r="2" />
      <path d="m7.8 6.7 8.4.9M7 7.8l1.3 8.4M16.7 9.5l-6.2 7" />
    </svg>
  );
}

function NavDropdown({
  kind,
  label,
  menuId,
  items,
  section,
  onSelect,
}: {
  kind: NavKind;
  label: string;
  menuId: string;
  items: NavMenuItem[];
  section: Section;
  onSelect: (section: Section) => void;
}) {
  const [open, setOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState({ left: 0, top: 0 });
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const firstItemRef = useRef<HTMLButtonElement>(null);
  const active = items.some((item) => item.section === section);

  useEffect(() => {
    if (!open) return;
    firstItemRef.current?.focus();

    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        window.requestAnimationFrame(() => triggerRef.current?.focus());
      }
    };
    const closeOnViewportChange = () => setOpen(false);

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeOnViewportChange);
    window.addEventListener("scroll", closeOnViewportChange, true);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeOnViewportChange);
      window.removeEventListener("scroll", closeOnViewportChange, true);
    };
  }, [open]);

  const openMenu = () => {
    const triggerRect = triggerRef.current?.getBoundingClientRect();
    if (triggerRect) {
      const menuWidth = 176;
      setMenuPosition({
        left: Math.max(12, Math.min(triggerRect.left, window.innerWidth - menuWidth - 12)),
        top: triggerRect.bottom + 8,
      });
    }
    setOpen(true);
  };

  const handleMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const buttons = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]'),
    );
    if (!buttons.length) return;
    event.preventDefault();
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Home") buttons[0]?.focus();
    else if (event.key === "End") buttons.at(-1)?.focus();
    else if (event.key === "ArrowDown") buttons[(current + 1 + buttons.length) % buttons.length]?.focus();
    else buttons[(current - 1 + buttons.length) % buttons.length]?.focus();
  };

  return (
    <div className="app-nav-dropdown" ref={menuRef}>
      <button
        ref={triggerRef}
        type="button"
        aria-label={label}
        aria-controls={menuId}
        aria-expanded={open}
        aria-haspopup="menu"
        data-active={active}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            openMenu();
          }
        }}
      >
        <NavIcon kind={kind} />
        <span>{label}</span>
        <span className="app-nav-dropdown-chevron" aria-hidden="true">▾</span>
      </button>
      {open ? (
        <div
          id={menuId}
          className="app-nav-dropdown-menu"
          role="menu"
          aria-label={`${label}子菜单`}
          style={menuPosition}
          onKeyDown={handleMenuKeyDown}
        >
          {items.map((item, index) => (
            <button
              ref={index === 0 ? firstItemRef : undefined}
              key={item.section}
              type="button"
              role="menuitem"
              data-active={section === item.section}
              onClick={() => {
                onSelect(item.section);
                setOpen(false);
                window.requestAnimationFrame(() => triggerRef.current?.focus());
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function AppShell() {
  const [section, setSection] = useState<Section>("workspaces");
  const visualizationActive = visualizationSections.includes(section);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand">
          <span className="app-brand-mark">AC</span>
          <div>
            <strong>Agent Context</strong>
            <span>本地 MCP 查看台</span>
          </div>
        </div>
        <nav aria-label="主菜单">
          <button
            type="button"
            aria-label="工作空间"
            data-active={section === "workspaces"}
            onClick={() => setSection("workspaces")}
          >
            <NavIcon kind="workspaces" />
            <span>工作空间</span>
          </button>
          <NavDropdown
            kind="data-management"
            label="数据管理"
            menuId="data-management-menu"
            items={dataManagementItems}
            section={section}
            onSelect={setSection}
          />
          <NavDropdown
            kind="interface-management"
            label="接口管理"
            menuId="interface-management-menu"
            items={interfaceManagementItems}
            section={section}
            onSelect={setSection}
          />
          <NavDropdown
            kind="ai-visualization"
            label="AI可视化"
            menuId="ai-visualization-menu"
            items={visualizationItems}
            section={section}
            onSelect={setSection}
          />
          <NavDropdown
            kind="system-center"
            label="系统中心"
            menuId="system-center-menu"
            items={systemCenterItems}
            section={section}
            onSelect={setSection}
          />
          <NavDropdown
            kind="configuration-management"
            label="配置管理"
            menuId="configuration-management-menu"
            items={configurationManagementItems}
            section={section}
            onSelect={setSection}
          />
        </nav>
      </header>
      <main
        className={
          section === "traces" ||
          section === "system-guides" ||
          section === "doc-stats" ||
          section === "table-relations" ||
          section === "relation-records" ||
          section === "interface-forwarding" ||
          section === "value-mappings" ||
          section === "shared-ai-config" ||
          visualizationActive
            ? "app-content app-content--traces"
            : "app-content"
        }
      >
        {section === "workspaces" ? <WorkspaceDashboard /> : null}
        {section === "data-sources" ? <DataSourceDashboard /> : null}
        {section === "table-relations" ? <TableRelationExplorer /> : null}
        {section === "relation-records" ? <RelationRecordExplorer /> : null}
        {section === "interface-forwarding" ? <InterfaceForwardingManager /> : null}
        {section === "value-mappings" ? <ValueMappingManager /> : null}
        {section === "shared-ai-config" ? <SharedAiConfigManager /> : null}
        {section === "traces" ? <TraceExplorer /> : null}
        {section === "system-guides" ? <SystemGuideManager /> : null}
        {section === "doc-stats" ? <DocumentReadStats /> : null}
      </main>
    </div>
  );
}
