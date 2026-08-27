"use client";

import { useCallback, useState } from "react";

import {
  getAiLogInvestigation,
  getAiLogInvestigations,
} from "@/lib/api";
import {
  CopyVisualizationButton,
  useVisualizationRecords,
  useVisualizationWorkspaces,
} from "@/components/visualization-record-explorer";
import type {
  AiLogInvestigationDetail,
  AiLogInvestigationListItem,
} from "@/lib/types";

type SeverityFilter = "all" | "error" | "critical";

function sourceLabel(source: string): string {
  return {
    codex: "Codex",
    antigravity: "Antigravity",
    agent: "本机 Agent",
  }[source.toLowerCase()] ?? source;
}

function severityLabel(severity: string): string {
  return severity === "critical" ? "严重" : "错误";
}

function formatTime(value?: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function LogVisualizationWorkbench({
  taskId,
  onOpenRelated,
}: {
  taskId?: number | null;
  onOpenRelated?: (
    section: "task-visualization" | "interface-visualization" | "data-visualization" | "log-visualization",
    taskId: number,
  ) => void;
}) {
  const [workspaceId, setWorkspaceId] = useState("");
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all");
  const {
    workspaces,
    workspaceError,
    workspaceLoading,
    reloadWorkspaces,
  } = useVisualizationWorkspaces();
  const loadPage = useCallback(
    (cursor?: string) => getAiLogInvestigations({
      workspaceId: workspaceId || undefined,
      severity: severityFilter === "all" ? undefined : severityFilter,
      limit: 50,
      cursor,
      taskId: taskId ?? undefined,
    }),
    [severityFilter, taskId, workspaceId],
  );
  const loadDetail = useCallback(
    (id: string) => getAiLogInvestigation(id),
    [],
  );
  const {
    items,
    selectedId,
    setSelectedId,
    detail,
    loading,
    loadingMore,
    detailLoading,
    error,
    detailError,
    hasMore,
    refresh,
    loadMore,
  } = useVisualizationRecords<AiLogInvestigationListItem, AiLogInvestigationDetail>({
    filterKey: `${workspaceId}:${severityFilter}:${taskId ?? ""}`,
    loadPage,
    loadDetail,
    listErrorMessage: "日志排查记录加载失败",
    detailErrorMessage: "错误详情加载失败",
  });

  return (
    <section className="interface-visualization-page" aria-labelledby="log-visualization-title">
      <header className="interface-visualization-heading">
        <div>
          <p className="eyebrow">AI VISUALIZATION / LOGS</p>
          <h1 id="log-visualization-title">日志可视化</h1>
          <p>展示 AI 从已注册 Docker 容器中确认的错误快照，最新排查优先。</p>
        </div>
        <button type="button" className="secondary-button" disabled={loading} onClick={() => void refresh()}>
          {loading ? "正在刷新…" : "刷新列表"}
        </button>
      </header>

      <div className="interface-visualization-toolbar" aria-label="日志排查列表筛选">
        <label>
          <span>工作空间</span>
          <select value={workspaceId} disabled={workspaceLoading} onChange={(event) => setWorkspaceId(event.target.value)}>
            <option value="">全部工作空间</option>
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
            ))}
          </select>
        </label>
        <label>
          <span>严重级别</span>
          <select value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value as SeverityFilter)}>
            <option value="all">全部级别</option>
            <option value="error">错误</option>
            <option value="critical">严重</option>
          </select>
        </label>
        <p aria-live="polite">{loading ? "正在读取排查记录" : `当前显示 ${items.length} 条记录`}</p>
      </div>

      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      {taskId ? <p className="interface-visualization-notice">当前只显示任务 #{taskId} 的错误记录。</p> : null}
      {workspaceError ? (
        <p className="error-banner visualization-retry-banner" role="alert">
          <span>{workspaceError}</span>
          <button type="button" className="secondary-button" onClick={() => void reloadWorkspaces()}>重新加载工作空间</button>
        </p>
      ) : null}

      <div className="interface-visualization-layout">
        <aside className="interface-request-list" aria-label="日志排查记录列表">
          {loading && items.length === 0 ? <p className="interface-visualization-state">正在加载最近排查…</p> : null}
          {!loading && !error && items.length === 0 ? (
            <div className="interface-visualization-state">
              <strong>暂无错误记录</strong>
              <span>AI 在已注册容器中确认错误后会显示在这里。</span>
            </div>
          ) : null}
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="interface-request-list-item log-investigation-list-item"
              data-active={item.id === selectedId}
              aria-pressed={item.id === selectedId}
              onClick={() => setSelectedId(item.id)}
            >
              <span className="interface-request-list-line">
                <span className={`log-severity log-severity--${item.severity}`}>{severityLabel(item.severity)}</span>
                <strong title={item.error_title}>{item.error_title}</strong>
                {item.occurrence_count > 1 ? <span className="log-occurrence">×{item.occurrence_count}</span> : null}
              </span>
              <code title={item.container_name}>{item.container_name}</code>
              <span className="interface-request-list-description" title={item.description}>{item.description}</span>
              <span className="interface-request-list-meta">
                <span>{sourceLabel(item.source)} · {item.workspace_name} · {item.environment}</span>
                <time dateTime={item.updated_at}>{formatTime(item.updated_at)}</time>
              </span>
            </button>
          ))}
          {hasMore ? (
            <button type="button" className="secondary-button interface-request-load-more" disabled={loadingMore} onClick={() => void loadMore()}>
              {loadingMore ? "正在加载…" : "加载更多"}
            </button>
          ) : null}
        </aside>

        <article className="interface-request-detail log-investigation-detail" aria-live="polite">
          {detailLoading ? <p className="interface-visualization-state">正在加载错误详情…</p> : null}
          {detailError ? <p className="error-banner" role="alert">{detailError}</p> : null}
          {!detailLoading && !detailError && !detail ? (
            <div className="interface-visualization-state">
              <strong>选择一条记录查看详情</strong>
              <span>详情仅展示本次排查确认的错误快照和容器信息。</span>
            </div>
          ) : null}
          {!detailLoading && detail ? (
            <>
              <header className="interface-request-detail-heading">
                <div>
                  <span className={`log-severity log-severity--${detail.severity}`}>{severityLabel(detail.severity)}</span>
                  <h2>{detail.error_title}</h2>
                  <code>{detail.container_name}</code>
                </div>
                <time dateTime={detail.occurred_at ?? detail.updated_at}>{formatTime(detail.occurred_at ?? detail.updated_at)}</time>
              </header>

              <dl className="interface-request-metadata">
                <div><dt>工作空间</dt><dd>{detail.workspace_name}</dd></div>
                <div><dt>任务环境</dt><dd>{detail.environment}</dd></div>
                <div><dt>项目</dt><dd>{detail.project_name ?? "-"}</dd></div>
                <div><dt>容器</dt><dd>{detail.container_name}</dd></div>
                <div><dt>镜像</dt><dd>{detail.image}</dd></div>
                <div><dt>AI 来源</dt><dd>{sourceLabel(detail.source)}</dd></div>
              </dl>

              {detail.task_id && onOpenRelated ? (
                <nav className="visualization-related-actions" aria-label="查看同任务记录">
                  <span>关联任务 #{detail.task_id}</span>
                  <button type="button" className="secondary-button" onClick={() => onOpenRelated("task-visualization", detail.task_id!)}>返回任务</button>
                  <button type="button" className="secondary-button" onClick={() => onOpenRelated("interface-visualization", detail.task_id!)}>查看接口请求</button>
                  <button type="button" className="secondary-button" onClick={() => onOpenRelated("data-visualization", detail.task_id!)}>查看数据条件</button>
                </nav>
              ) : null}

              {detail.truncated ? (
                <p className="interface-visualization-notice">日志超过快照上限，当前展示的是经过截断和脱敏的错误内容。</p>
              ) : null}

              <section className="log-error-excerpt">
                <header>
                  <h3>错误内容</h3>
                  <div>
                    <span>{detail.log_line_count} 行已扫描 · {detail.occurrence_count} 个错误事件</span>
                    <CopyVisualizationButton value={detail.error_excerpt} />
                  </div>
                </header>
                <pre tabIndex={0}>{detail.error_excerpt}</pre>
              </section>
            </>
          ) : null}
        </article>
      </div>
    </section>
  );
}
