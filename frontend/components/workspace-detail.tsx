"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ProjectDashboard,
  type ProjectDashboardHandle,
} from "@/components/project-dashboard";
import { WorkspaceDataSourceOverview } from "@/components/workspace-data-source-overview";
import { WorkspaceEnvironmentMapping } from "@/components/workspace-environment-mapping";
import { WorkspaceRuntimeSync } from "@/components/workspace-runtime-sync";
import {
  getWorkspaceDatabaseEnvironmentMappings,
  getWorkspaceEnvironmentConfig,
} from "@/lib/api";
import type {
  DatabaseEnvironment,
  ProjectKind,
  WorkspaceSummary,
} from "@/lib/types";

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
  const currentWorkspace = workspace;
  const [projectCounts, setProjectCounts] = useState<Record<ProjectKind, number>>({
    frontend: 0,
    backend: 0,
  });
  const [showEnvironmentMapping, setShowEnvironmentMapping] = useState(false);
  const [activeDatabaseEnvironment, setActiveDatabaseEnvironment] =
    useState<DatabaseEnvironment | null>(null);
  const projectDashboardRef = useRef<ProjectDashboardHandle>(null);

  const updateProjectCounts = useCallback(
    (counts: Record<ProjectKind, number>) => {
      setProjectCounts(counts);
    },
    [],
  );

  useEffect(() => {
    let active = true;
    void Promise.all([
      getWorkspaceDatabaseEnvironmentMappings(workspace.id),
      getWorkspaceEnvironmentConfig(workspace.id),
    ])
      .then(([configuration, environmentConfig]) => {
        if (!active) return;
        setActiveDatabaseEnvironment(
          configuration.configured
            ? configuration.active_environment
            : environmentConfig.configured
              ? environmentConfig.active_environment
              : null,
        );
      })
      .catch(() => {
        // Environment mapping is optional. The detail panel will expose a
        // retryable error if the user chooses to open it.
      });
    return () => {
      active = false;
    };
  }, [workspace.id]);

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
        <button
          type="button"
          className="secondary-button workspace-environment-button"
          data-environment={activeDatabaseEnvironment ?? "unconfigured"}
          onClick={() => setShowEnvironmentMapping(true)}
        >
          环境详情 ·{" "}
          {activeDatabaseEnvironment
            ? activeDatabaseEnvironment.toUpperCase()
            : "未配置"}
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
      />
      {tab === "data-sources" ? (
        <WorkspaceDataSourceOverview workspaceId={currentWorkspace.id} />
      ) : null}
      {showEnvironmentMapping ? (
        <WorkspaceEnvironmentMapping
          workspace={currentWorkspace}
          onClose={() => setShowEnvironmentMapping(false)}
          onEnvironmentChanged={setActiveDatabaseEnvironment}
        />
      ) : null}
    </section>
  );
}
