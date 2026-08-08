"use client";

import { useState } from "react";

import { DataSourceDashboard } from "@/components/data-source-dashboard";
import { DocumentReadStats } from "@/components/document-read-stats";
import { TraceExplorer } from "@/components/trace-explorer";
import { SystemGuideManager } from "@/components/system-guide-manager";
import { WorkspaceDashboard } from "@/components/workspace-dashboard";

type Section = "workspaces" | "data-sources" | "traces" | "system-guides" | "doc-stats";

function NavIcon({ kind }: { kind: Section }) {
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
  if (kind === "system-guides") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6 3.5h9l3 3V20.5H6z" />
        <path d="M15 3.5v3h3M9 10h6M9 14h6M9 18h4" />
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

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
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
            data-active={section === "workspaces"}
            onClick={() => setSection("workspaces")}
          >
            <NavIcon kind="workspaces" />
            <span>工作空间</span>
          </button>
          <button
            type="button"
            data-active={section === "data-sources"}
            onClick={() => setSection("data-sources")}
          >
            <NavIcon kind="data-sources" />
            <span>数据源</span>
          </button>
          <button
            type="button"
            data-active={section === "traces"}
            onClick={() => setSection("traces")}
          >
            <NavIcon kind="traces" />
            <span>调用链路</span>
          </button>
          <button
            type="button"
            data-active={section === "system-guides"}
            onClick={() => setSection("system-guides")}
          >
            <NavIcon kind="system-guides" />
            <span>系统文档</span>
          </button>
          <button
            type="button"
            data-active={section === "doc-stats"}
            onClick={() => setSection("doc-stats")}
          >
            <NavIcon kind="doc-stats" />
            <span>文档统计</span>
          </button>
        </nav>
        <p className="app-sidebar-note">工作空间只读 · 系统文档可维护</p>
      </aside>
      <main
        className={
          section === "traces" || section === "system-guides" || section === "doc-stats"
            ? "app-content app-content--traces"
            : "app-content"
        }
      >
        {section === "workspaces" ? <WorkspaceDashboard /> : null}
        {section === "data-sources" ? <DataSourceDashboard /> : null}
        {section === "traces" ? <TraceExplorer /> : null}
        {section === "system-guides" ? <SystemGuideManager /> : null}
        {section === "doc-stats" ? <DocumentReadStats /> : null}
      </main>
    </div>
  );
}
