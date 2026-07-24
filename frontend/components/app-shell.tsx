"use client";

import { useState } from "react";

import { DataSourceDashboard } from "@/components/data-source-dashboard";
import { ProjectDashboard } from "@/components/project-dashboard";
import { TraceExplorer } from "@/components/trace-explorer";

type Section = "projects" | "data-sources" | "traces";

function NavIcon({ kind }: { kind: Section }) {
  if (kind === "projects") {
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
  const [section, setSection] = useState<Section>("projects");
  const [traceProjectId, setTraceProjectId] = useState<string | null>(null);

  function openProjectTraces(projectId: string) {
    setTraceProjectId(projectId);
    setSection("traces");
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-brand">
          <span className="app-brand-mark">AC</span>
          <div>
            <strong>Agent Context</strong>
            <span>本地 MCP 工作台</span>
          </div>
        </div>
        <nav aria-label="主菜单">
          <button
            type="button"
            data-active={section === "projects"}
            onClick={() => setSection("projects")}
          >
            <NavIcon kind="projects" />
            <span>项目管理</span>
          </button>
          <button
            type="button"
            data-active={section === "data-sources"}
            onClick={() => setSection("data-sources")}
          >
            <NavIcon kind="data-sources" />
            <span>数据源管理</span>
          </button>
          <button
            type="button"
            data-active={section === "traces"}
            onClick={() => {
              setTraceProjectId(null);
              setSection("traces");
            }}
          >
            <NavIcon kind="traces" />
            <span>链路管理</span>
          </button>
        </nav>
        <p className="app-sidebar-note">连接信息仅保存在本机服务中</p>
      </aside>
      <main className="app-content">
        {section === "projects" ? (
          <ProjectDashboard onOpenTraces={openProjectTraces} />
        ) : null}
        {section === "data-sources" ? <DataSourceDashboard /> : null}
        {section === "traces" ? (
          <TraceExplorer projectId={traceProjectId ?? undefined} />
        ) : null}
      </main>
    </div>
  );
}
