"use client";

import { useCallback, useEffect, useState } from "react";

import { getWorkspaceDataSourceSummary } from "@/lib/api";
import type {
  WorkspaceDataSourceAssignment,
  WorkspaceDataSourceSummary,
} from "@/lib/types";

interface WorkspaceDataSourceOverviewProps {
  workspaceId: string;
}

function assignmentStatus(assignment: WorkspaceDataSourceAssignment): string {
  const labels: Record<string, string> = {
    active: "授权条件满足",
    workspace_disabled: "工作空间已停用",
    source_disabled: "数据源已停用",
    database_unavailable: "数据库不可用",
    system_database: "系统库",
    link_disabled: "授权已停用",
    not_readonly: "不是只读授权",
    missing_mcp_alias: "缺少 MCP 别名",
  };
  return labels[assignment.status] ?? assignment.status ?? "已关联";
}

export function WorkspaceDataSourceOverview({
  workspaceId,
}: WorkspaceDataSourceOverviewProps) {
  const [summary, setSummary] =
    useState<WorkspaceDataSourceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      setSummary(await getWorkspaceDataSourceSummary(workspaceId));
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  if (loading) {
    return <p className="empty-message">正在汇总工作空间数据源…</p>;
  }

  if (error) {
    return (
      <div className="workspace-summary-error">
        <div className="error-banner" role="alert">
          {error}
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={() => void loadSummary()}
        >
          重新加载
        </button>
      </div>
    );
  }

  if (!summary || summary.sources.length === 0) {
    return (
      <div className="empty-state workspace-data-source-empty">
        <span className="empty-database-icon">◎</span>
        <h2>这个工作空间还没有数据源授权</h2>
        <p>
          请切换到“后端项目”，在项目卡片中打开“管理数据源”，为它选择数据库。
        </p>
      </div>
    );
  }

  return (
    <section className="workspace-data-source-overview">
      <div className="workspace-summary-stats" aria-label="数据源汇总指标">
        <div>
          <strong>{summary.source_count}</strong>
          <span>物理数据源</span>
        </div>
        <div>
          <strong>{summary.database_count}</strong>
          <span>去重数据库</span>
        </div>
        <div>
          <strong>{summary.assignment_count}</strong>
          <span>项目授权</span>
        </div>
        <div>
          <strong>{summary.project_count}</strong>
          <span>已配置项目</span>
        </div>
      </div>

      <div className="workspace-source-list">
        {summary.sources.map((source) => (
          <article
            className="workspace-source-card"
            data-enabled={source.enabled}
            key={source.id}
          >
            <header>
              <div>
                <div className="data-source-card-chips">
                  <span className="engine-chip">
                    {source.engine.toUpperCase()}
                  </span>
                  <span className="data-source-category-chip">
                    {source.category}
                  </span>
                </div>
                <h2>{source.name}</h2>
              </div>
              <span
                className="project-status-chip"
                data-enabled={source.enabled}
              >
                {source.enabled ? "已启用" : "已停用"}
              </span>
            </header>
            <div className="workspace-source-metrics">
              <span>{source.database_count} 个数据库</span>
              <span>{source.project_count} 个项目</span>
              <span>{source.assignment_count} 条授权</span>
            </div>
            <div className="workspace-assignment-list">
              {source.assignments.map((assignment) => (
                <div
                  className="workspace-assignment-row"
                  key={assignment.link_id}
                >
                  <div>
                    <strong>
                      {assignment.project_kind === "frontend"
                        ? "前端项目"
                        : assignment.project_kind === "backend"
                          ? "后端项目"
                          : "项目"}
                      {" · "}
                      {assignment.project_name}
                    </strong>
                    <span>
                      {assignment.database_display_name ||
                        assignment.database_name}
                    </span>
                  </div>
                  <code>
                    {assignment.mcp_alias || assignment.alias || "未设置别名"}
                  </code>
                  <span
                    className="workspace-assignment-status"
                    data-ready={assignment.status === "active"}
                  >
                    {assignmentStatus(assignment)}
                  </span>
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
