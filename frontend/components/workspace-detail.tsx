"use client";

import Link from "next/link";
import { useCallback, useRef, useState } from "react";

import {
  ProjectDashboard,
  type ProjectDashboardHandle,
} from "@/components/project-dashboard";
import { WorkspaceRuntimeSync } from "@/components/workspace-runtime-sync";
import type { ProjectKind, WorkspaceSummary } from "@/lib/types";

interface WorkspaceDetailProps {
  workspace: WorkspaceSummary;
  onBack: () => void;
}

type WorkspaceDetailTab = ProjectKind;

export function WorkspaceDetail({
  workspace,
  onBack,
}: WorkspaceDetailProps) {
  const [tab, setTab] = useState<WorkspaceDetailTab>("frontend");
  const currentWorkspace = workspace;
  const [projectCounts, setProjectCounts] = useState<Record<ProjectKind, number>>({
    frontend: 0,
    backend: 0,
  });
  const projectDashboardRef = useRef<ProjectDashboardHandle>(null);

  const updateProjectCounts = useCallback(
    (counts: Record<ProjectKind, number>) => {
      setProjectCounts(counts);
    },
    [],
  );

  return (
    <section className="workspace-detail">
      <header className="workspace-detail-header">
        <button
          type="button"
          className="close-button workspace-detail-close-button"
          aria-label="关闭工作空间详情"
          onClick={onBack}
        >
          ×
        </button>
        <div className="workspace-detail-title">
          <div>
            <h1>{currentWorkspace.name}</h1>
            <code>{currentWorkspace.root_path}</code>
          </div>
        </div>
      </header>


      <div className="workspace-context-actions" aria-label="工作空间操作">
        <WorkspaceRuntimeSync workspaceId={currentWorkspace.id} />
        <button
          type="button"
          className="secondary-button"
          onClick={() => projectDashboardRef.current?.showMcpIntegration()}
        >
          MCP 接入
        </button>
        <Link
          className="secondary-button workspace-environment-button"
          data-environment="local"
          href={`/workspaces/${encodeURIComponent(currentWorkspace.id)}/mcp-environments`}
        >
          环境详情
        </Link>
        <button
          type="button"
          className="secondary-button"
          onClick={() =>
            projectDashboardRef.current?.showWorkspaceTaskHistory()
          }
        >
          查看调用记录
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() => projectDashboardRef.current?.showWorkspaceTree()}
        >
          查看文档树
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() =>
            projectDashboardRef.current?.showWorkspaceMcpPreview()
          }
        >
          查看 MCP JSON
        </button>
      </div>

      <nav
        className="workspace-detail-tabs"
        role="tablist"
        aria-label="工作空间详情"
      >
        <button
          type="button"
          role="tab"
          aria-selected={tab === "frontend"}
          data-active={tab === "frontend"}
          onClick={() => setTab("frontend")}
        >
          <span>前端项目</span>
          <small>{projectCounts.frontend}</small>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "backend"}
          data-active={tab === "backend"}
          onClick={() => setTab("backend")}
        >
          <span>后端项目</span>
          <small>{projectCounts.backend}</small>
        </button>
      </nav>

      <ProjectDashboard
        ref={projectDashboardRef}
        workspace={currentWorkspace}
        projectKind={tab}
        visible
        onProjectCountsChanged={updateProjectCounts}
      />
    </section>
  );
}
