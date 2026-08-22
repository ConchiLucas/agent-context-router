"use client";

import { useEffect, useRef, useState } from "react";

import { DataSourceDashboard } from "@/components/data-source-dashboard";
import { DocumentReadStats } from "@/components/document-read-stats";
import { TraceExplorer } from "@/components/trace-explorer";
import { SystemGuideManager } from "@/components/system-guide-manager";
import { TableRelationExplorer } from "@/components/table-relation-explorer";
import { RelationRecordExplorer } from "@/components/relation-record-explorer";
import { WorkspaceDashboard } from "@/components/workspace-dashboard";
import { InterfaceForwardingManager } from "@/components/interface-forwarding-manager";

type Section =
  | "workspaces"
  | "data-sources"
  | "table-relations"
  | "relation-records"
  | "interface-forwarding"
  | "interface-visualization"
  | "data-visualization"
  | "log-visualization"
  | "traces"
  | "system-guides"
  | "doc-stats";

type NavKind = Section | "ai-visualization";

const visualizationSections: Section[] = [
  "interface-visualization",
  "data-visualization",
  "log-visualization",
];

function NavIcon({ kind }: { kind: NavKind }) {
  if (kind === "workspaces") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 6.5h6l1.7 2H20v9.5H4z" />
        <path d="M4 6.5V5h6l1.7 2H20v1.5" />
      </svg>
    );
  }
  if (kind === "data-sources") {
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
  if (kind === "system-guides") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6 3.5h9l3 3V20.5H6z" />
        <path d="M15 3.5v3h3M9 10h6M9 14h6M9 18h4" />
      </svg>
    );
  }
  if (kind === "interface-forwarding") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 7h11M12 4l3 3-3 3M20 17H9M12 14l-3 3 3 3" />
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
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="6" cy="6" r="2" />
      <circle cx="18" cy="8" r="2" />
      <circle cx="9" cy="18" r="2" />
      <path d="m7.8 6.7 8.4.9M7 7.8l1.3 8.4M16.7 9.5l-6.2 7" />
    </svg>
  );
}

export function AppShell() {
  const [section, setSection] = useState<Section>("workspaces");
  const [visualizationOpen, setVisualizationOpen] = useState(false);
  const [visualizationMenuPosition, setVisualizationMenuPosition] = useState({
    left: 0,
    top: 0,
  });
  const visualizationMenuRef = useRef<HTMLDivElement>(null);
  const visualizationTriggerRef = useRef<HTMLButtonElement>(null);
  const firstVisualizationItemRef = useRef<HTMLButtonElement>(null);
  const visualizationActive = visualizationSections.includes(section);

  useEffect(() => {
    if (!visualizationOpen) {
      return;
    }

    firstVisualizationItemRef.current?.focus();

    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!visualizationMenuRef.current?.contains(event.target as Node)) {
        setVisualizationOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setVisualizationOpen(false);
        visualizationTriggerRef.current?.focus();
      }
    };
    const closeOnViewportChange = () => setVisualizationOpen(false);

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
  }, [visualizationOpen]);

  const toggleVisualizationMenu = () => {
    if (!visualizationOpen && visualizationTriggerRef.current) {
      const triggerRect = visualizationTriggerRef.current.getBoundingClientRect();
      const menuWidth = 176;
      setVisualizationMenuPosition({
        left: Math.max(12, Math.min(triggerRect.left, window.innerWidth - menuWidth - 12)),
        top: triggerRect.bottom + 8,
      });
    }
    setVisualizationOpen((current) => !current);
  };

  const selectVisualizationSection = (nextSection: Section) => {
    setSection(nextSection);
    setVisualizationOpen(false);
    visualizationTriggerRef.current?.focus();
  };

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
            aria-label="接口转发"
            data-active={section === "interface-forwarding"}
            onClick={() => setSection("interface-forwarding")}
          >
            <NavIcon kind="interface-forwarding" />
            <span>接口转发</span>
          </button>
          <button
            type="button"
            aria-label="工作空间"
            data-active={section === "workspaces"}
            onClick={() => setSection("workspaces")}
          >
            <NavIcon kind="workspaces" />
            <span>工作空间</span>
          </button>
          <button
            type="button"
            aria-label="数据源"
            data-active={section === "data-sources"}
            onClick={() => setSection("data-sources")}
          >
            <NavIcon kind="data-sources" />
            <span>数据源</span>
          </button>
          <button
            type="button"
            aria-label="表关联"
            data-active={section === "table-relations"}
            onClick={() => setSection("table-relations")}
          >
            <NavIcon kind="table-relations" />
            <span>表关联</span>
          </button>
          <button
            type="button"
            aria-label="关联数据"
            data-active={section === "relation-records"}
            onClick={() => setSection("relation-records")}
          >
            <NavIcon kind="relation-records" />
            <span>关联数据</span>
          </button>
          <button
            type="button"
            aria-label="调用链路"
            data-active={section === "traces"}
            onClick={() => setSection("traces")}
          >
            <NavIcon kind="traces" />
            <span>调用链路</span>
          </button>
          <div className="app-nav-dropdown" ref={visualizationMenuRef}>
            <button
              ref={visualizationTriggerRef}
              type="button"
              aria-label="AI可视化"
              aria-controls="ai-visualization-menu"
              aria-expanded={visualizationOpen}
              aria-haspopup="menu"
              data-active={visualizationActive}
              onClick={toggleVisualizationMenu}
            >
              <NavIcon kind="ai-visualization" />
              <span>AI可视化</span>
              <span className="app-nav-dropdown-chevron" aria-hidden="true">
                ▾
              </span>
            </button>
            {visualizationOpen ? (
              <div
                id="ai-visualization-menu"
                className="app-nav-dropdown-menu"
                role="menu"
                aria-label="AI可视化子菜单"
                style={visualizationMenuPosition}
              >
                <button
                  ref={firstVisualizationItemRef}
                  type="button"
                  role="menuitem"
                  data-active={section === "interface-visualization"}
                  onClick={() => selectVisualizationSection("interface-visualization")}
                >
                  接口可视化
                </button>
                <button
                  type="button"
                  role="menuitem"
                  data-active={section === "data-visualization"}
                  onClick={() => selectVisualizationSection("data-visualization")}
                >
                  数据可视化
                </button>
                <button
                  type="button"
                  role="menuitem"
                  data-active={section === "log-visualization"}
                  onClick={() => selectVisualizationSection("log-visualization")}
                >
                  日志可视化
                </button>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            aria-label="系统文档"
            data-active={section === "system-guides"}
            onClick={() => setSection("system-guides")}
          >
            <NavIcon kind="system-guides" />
            <span>系统文档</span>
          </button>
          <button
            type="button"
            aria-label="文档统计"
            data-active={section === "doc-stats"}
            onClick={() => setSection("doc-stats")}
          >
            <NavIcon kind="doc-stats" />
            <span>文档统计</span>
          </button>
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
        {section === "traces" ? <TraceExplorer /> : null}
        {section === "system-guides" ? <SystemGuideManager /> : null}
        {section === "doc-stats" ? <DocumentReadStats /> : null}
      </main>
    </div>
  );
}
