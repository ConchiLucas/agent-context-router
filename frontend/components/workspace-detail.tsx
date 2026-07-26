"use client";

import { useCallback, useRef, useState } from "react";

import {
  ProjectDashboard,
  type ProjectDashboardHandle,
} from "@/components/project-dashboard";
import { WorkspaceDataSourceOverview } from "@/components/workspace-data-source-overview";
import { getWorkspace } from "@/lib/api";
import type { ProjectKind, WorkspaceSummary } from "@/lib/types";

interface WorkspaceDetailProps {
  workspace: WorkspaceSummary;
  onBack: () => void;
}

type WorkspaceDetailTab = ProjectKind | "data-sources";

export function WorkspaceDetail({
  workspace,
  onBack,
}: WorkspaceDetailProps) {
  const [tab, setTab] = useState<WorkspaceDetailTab>("frontend");
  const [currentWorkspace, setCurrentWorkspace] =
    useState<WorkspaceSummary>(workspace);
  const [projectCounts, setProjectCounts] = useState<Record<ProjectKind, number>>({
    frontend: 0,
    backend: 0,
  });
  const projectDashboardRef = useRef<ProjectDashboardHandle>(null);

  const refreshWorkspace = useCallback(async () => {
    try {
      setCurrentWorkspace(await getWorkspace(workspace.id));
    } catch {
      // The project mutation has already succeeded. Keep the current header
      // counters and let the next navigation reload them instead of presenting
      // the completed mutation as a failure.
    }
  }, [workspace.id]);

  const updateProjectCounts = useCallback(
    (counts: Record<ProjectKind, number>) => {
      setProjectCounts(counts);
    },
    [],
  );

  function addProject() {
    if (tab === "data-sources") setTab("backend");
    projectDashboardRef.current?.openCreateProject();
  }

  return (
    <section className="workspace-detail">
      <header className="workspace-detail-header">
        <button
          type="button"
          className="workspace-back-button"
          onClick={onBack}
        >
          <span aria-hidden="true">←</span>
          返回工作空间
        </button>
        <div className="workspace-detail-title">
          <div>
            <span className="section-eyebrow">Workspace</span>
            <h1>{currentWorkspace.name}</h1>
            <code>{currentWorkspace.root_path}</code>
          </div>
          <div className="workspace-detail-badges">
            <span className="project-type-chip">
              {currentWorkspace.workspace_type}
            </span>
            <span
              className="project-status-chip"
              data-enabled={currentWorkspace.enabled}
            >
              {currentWorkspace.enabled
                ? "工作空间已启用"
                : "工作空间已停用"}
            </span>
          </div>
        </div>
      </header>

      {!currentWorkspace.enabled ? (
        <div className="workspace-disabled-banner">
          工作空间已停用，目录下的项目不会参与 MCP 的 cwd 匹配。你仍可以查看和修改配置。
        </div>
      ) : null}

      <div className="workspace-context-actions" aria-label="工作空间操作">
        <button
          type="button"
          className="secondary-button"
          onClick={() => projectDashboardRef.current?.showMcpIntegration()}
        >
          MCP 接入
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() =>
            projectDashboardRef.current?.refreshWorkspaceMapping()
          }
        >
          刷新映射
        </button>
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
        <button type="button" className="primary-button" onClick={addProject}>
          添加项目
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
        <button
          type="button"
          role="tab"
          aria-selected={tab === "data-sources"}
          data-active={tab === "data-sources"}
          onClick={() => setTab("data-sources")}
        >
          <span>数据源汇总</span>
          <small>{currentWorkspace.data_source_count}</small>
        </button>
      </nav>

      <ProjectDashboard
        ref={projectDashboardRef}
        workspace={currentWorkspace}
        projectKind={tab === "frontend" ? "frontend" : "backend"}
        visible={tab !== "data-sources"}
        onProjectCountsChanged={updateProjectCounts}
        onWorkspaceChanged={refreshWorkspace}
      />
      {tab === "data-sources" ? (
        <WorkspaceDataSourceOverview workspaceId={currentWorkspace.id} />
      ) : null}
    </section>
  );
}
