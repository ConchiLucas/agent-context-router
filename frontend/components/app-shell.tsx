"use client";

import { useState } from "react";

import { DataSourceDashboard } from "@/components/data-source-dashboard";
import { ProjectDashboard } from "@/components/project-dashboard";

type Section = "projects" | "data-sources";

function NavIcon({ kind }: { kind: Section }) {
  if (kind === "projects") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 6.5h6l1.7 2H20v9.5H4z" />
        <path d="M4 6.5V5h6l1.7 2H20v1.5" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <ellipse cx="12" cy="5.5" rx="7.5" ry="3" />
      <path d="M4.5 5.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6" />
      <path d="M4.5 11.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6" />
    </svg>
  );
}

export function AppShell() {
  const [section, setSection] = useState<Section>("projects");

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
        </nav>
        <p className="app-sidebar-note">连接信息仅保存在本机服务中</p>
      </aside>
      <main className="app-content">
        {section === "projects" ? <ProjectDashboard /> : <DataSourceDashboard />}
      </main>
    </div>
  );
}
