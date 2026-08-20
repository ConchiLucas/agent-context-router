"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { WorkspaceDetail } from "@/components/workspace-detail";
import { WorkspaceContainersModal } from "@/components/workspace-containers-modal";
import {
  getWorkspace,
  listWorkspaces,
  refreshWorkspace,
  reloadLocalWorkspaceMapping,
} from "@/lib/api";
import {
  clearWorkspaceRefreshError,
  finishWorkspaceRefresh,
  replaceWorkspaceSummary,
  runWorkspaceRefresh,
  setWorkspaceRefreshError,
  startWorkspaceRefresh,
} from "@/lib/workspace-dashboard";
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
  const [reloadingMapping, setReloadingMapping] = useState(false);
  const [refreshingWorkspaceIds, setRefreshingWorkspaceIds] = useState<
    Set<string>
  >(() => new Set());
  const [refreshErrors, setRefreshErrors] = useState<
    Record<string, string>
  >({});

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

  const handleRefreshWorkspace = useCallback(async (workspaceId: string) => {
    setRefreshingWorkspaceIds((current) =>
      startWorkspaceRefresh(current, workspaceId),
    );
    setRefreshErrors((current) =>
      clearWorkspaceRefreshError(current, workspaceId),
    );
    const result = await runWorkspaceRefresh(
      workspaceId,
      refreshWorkspace,
      getWorkspace,
    );
    const refreshed = result.summary;
    if (refreshed) {
      setWorkspaces((current) =>
        replaceWorkspaceSummary(current, refreshed),
      );
    }
    setRefreshErrors((current) =>
      result.error
        ? setWorkspaceRefreshError(current, workspaceId, result.error)
        : clearWorkspaceRefreshError(current, workspaceId),
    );
    setRefreshingWorkspaceIds((current) =>
      finishWorkspaceRefresh(current, workspaceId),
    );
  }, []);

  const handleReloadMapping = useCallback(async () => {
    setReloadingMapping(true);
    try {
      setWorkspaces(await reloadLocalWorkspaceMapping());
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setReloadingMapping(false);
    }
  }, []);

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
  const refreshError = Object.values(refreshErrors).join("；");

  return (
    <>
      <div className="workspace-mapping-toolbar">
        <p>卡片显示和目录来自当前项目的本机映射文件。</p>
        <button
          type="button"
          className="secondary-button"
          disabled={reloadingMapping}
          onClick={() => void handleReloadMapping()}
        >
          {reloadingMapping ? "正在重载…" : "重载本机映射"}
        </button>
      </div>
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

      {error || refreshError ? (
        <div className="error-banner" role="alert">
          {error ?? refreshError}
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
        {visibleWorkspaces.map((workspace) => {
          const isRefreshing = refreshingWorkspaceIds.has(workspace.id);
          return (
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
              <button
                type="button"
                className="secondary-button workspace-refresh-button"
                disabled={isRefreshing}
                aria-busy={isRefreshing}
                aria-label={
                  isRefreshing
                    ? `正在刷新 ${workspace.name} 的映射`
                    : `刷新 ${workspace.name} 的映射`
                }
                onClick={() => void handleRefreshWorkspace(workspace.id)}
              >
                {isRefreshing ? "刷新中…" : "刷新映射"}
              </button>
            </header>
            <code className="workspace-root-path">{workspace.root_path}</code>
            {workspace.document_reader_count > 0 ? (
              <p className="workspace-document-readers">
                共享文档目录 {workspace.document_reader_count} 个
              </p>
            ) : null}
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
              <WorkspaceContainersModal workspace={workspace} />
              <Link
                className="secondary-button workspace-environment-defaults-link"
                href={`/workspaces/${encodeURIComponent(workspace.id)}/mcp-environments`}
              >
                环境详情
              </Link>
              <button
                type="button"
                className="primary-button"
                onClick={() => setActiveWorkspace(workspace)}
              >
                进入工作空间
              </button>
            </div>
            </article>
          );
        })}
      </section>
    </>
  );
}
