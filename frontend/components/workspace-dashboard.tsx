"use client";

import { useCallback, useEffect, useState } from "react";

import { WorkspaceDetail } from "@/components/workspace-detail";
import { listWorkspaces } from "@/lib/api";
import type { WorkspaceSummary } from "@/lib/types";

const ALL_WORKSPACE_TYPES = "__all__";

function formattedTime(value?: string | null): string {
  if (!value) return "尚未更新";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function WorkspaceDashboard() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [activeWorkspace, setActiveWorkspace] =
    useState<WorkspaceSummary | null>(null);
  const [selectedType, setSelectedType] = useState(ALL_WORKSPACE_TYPES);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadWorkspaces = useCallback(async () => {
    setLoading(true);
    try {
      const next = await listWorkspaces();
      setWorkspaces(next);
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWorkspaces();
  }, [loadWorkspaces]);

  useEffect(() => {
    if (
      selectedType !== ALL_WORKSPACE_TYPES &&
      !workspaces.some(
        (workspace) => workspace.workspace_type === selectedType,
      )
    ) {
      setSelectedType(ALL_WORKSPACE_TYPES);
    }
  }, [selectedType, workspaces]);

  if (activeWorkspace) {
    return (
      <WorkspaceDetail
        key={activeWorkspace.id}
        workspace={activeWorkspace}
        onBack={() => {
          setActiveWorkspace(null);
          void loadWorkspaces();
        }}
      />
    );
  }

  const workspaceTypes = Array.from(
    new Set(workspaces.map((workspace) => workspace.workspace_type)),
  ).sort((left, right) => left.localeCompare(right, "zh-CN"));
  const visibleWorkspaces =
    selectedType === ALL_WORKSPACE_TYPES
      ? workspaces
      : workspaces.filter(
          (workspace) => workspace.workspace_type === selectedType,
        );

  return (
    <>
      <nav
        className="project-type-tabs"
        role="tablist"
        aria-label="工作空间类型"
      >
        <button
          type="button"
          role="tab"
          aria-selected={selectedType === ALL_WORKSPACE_TYPES}
          data-active={selectedType === ALL_WORKSPACE_TYPES}
          onClick={() => setSelectedType(ALL_WORKSPACE_TYPES)}
        >
          <span>全部工作空间</span>
          <small>{workspaces.length}</small>
        </button>
        {workspaceTypes.map((type) => (
          <button
            type="button"
            role="tab"
            aria-selected={selectedType === type}
            data-active={selectedType === type}
            key={type}
            onClick={() => setSelectedType(type)}
          >
            <span>{type}</span>
            <small>
              {
                workspaces.filter(
                  (workspace) => workspace.workspace_type === type,
                ).length
              }
            </small>
          </button>
        ))}
      </nav>

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      {loading ? <p className="empty-message">正在读取工作空间…</p> : null}
      {!loading && workspaces.length === 0 ? (
        <div className="empty-state workspace-empty-state">
          <span className="workspace-empty-icon">◇</span>
          <h2>还没有工作空间</h2>
          <p>当前没有可查看的工作空间配置。</p>
        </div>
      ) : null}
      {!loading &&
      workspaces.length > 0 &&
      visibleWorkspaces.length === 0 ? (
        <div className="empty-state workspace-empty-state">
          <h2>这个类型还没有工作空间</h2>
          <p>请选择其他工作空间类型查看。</p>
        </div>
      ) : null}

      <section className="workspace-grid" aria-label="工作空间列表">
        {visibleWorkspaces.map((workspace) => (
          <article className="workspace-card" key={workspace.id}>
            <header>
              <div>
                <div className="project-card-chips">
                  <span className="file-chip">Workspace</span>
                  <span className="project-type-chip">
                    {workspace.workspace_type}
                  </span>
                </div>
                <h2>{workspace.name}</h2>
              </div>
            </header>
            <code className="workspace-root-path">{workspace.root_path}</code>
            <div className="workspace-card-stats">
              <div>
                <strong>{workspace.project_count ?? 0}</strong>
                <span>项目</span>
              </div>
              <div>
                <strong>{workspace.data_source_count ?? 0}</strong>
                <span>数据源</span>
              </div>
              <div>
                <strong>{workspace.database_count ?? 0}</strong>
                <span>数据库</span>
              </div>
              <div data-warning={(workspace.error_project_count ?? 0) > 0}>
                <strong>{workspace.error_project_count ?? 0}</strong>
                <span>异常</span>
              </div>
              <div>
                <strong>
                  {workspace.database_authorization_count ?? 0}
                </strong>
                <span>授权</span>
              </div>
            </div>
            <p className="refresh-time">
              最近更新：{formattedTime(workspace.updated_at)}
            </p>
            <div className="workspace-card-actions">
              <button
                type="button"
                className="primary-button"
                onClick={() => setActiveWorkspace(workspace)}
              >
                进入工作空间
              </button>
            </div>
          </article>
        ))}
      </section>
    </>
  );
}
