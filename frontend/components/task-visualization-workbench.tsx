"use client";

import {
  type CompositionEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  getAiVisualizationTask,
  getAiVisualizationTasks,
  getAiVisualizationTaskTimeline,
} from "@/lib/api";
import type {
  AiTaskTimelineEvent,
  AiTaskVisualizationDetail,
  AiTaskVisualizationListItem,
  AiTaskVisualizationStatus,
} from "@/lib/types";
import {
  CopyVisualizationButton,
  useVisualizationWorkspaces,
} from "@/components/visualization-record-explorer";

type RelatedSection =
  | "interface-visualization"
  | "data-visualization"
  | "log-visualization";

const statusLabels: Record<AiTaskVisualizationStatus, string> = {
  investigating: "排查中",
  resolved: "已完成",
  failed: "未完成",
  unclosed: "待总结",
};

const eventLabels: Record<AiTaskTimelineEvent["event_type"], string> = {
  mcp_call: "MCP",
  data_query: "数据",
  interface_request: "接口",
  log_investigation: "日志",
  task_result: "结论",
};

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function taskCounts(item: AiTaskVisualizationListItem) {
  const interfaceCount = item.interface_success_count + item.interface_failed_count;
  return `${item.tool_call_count} 次工具 · ${item.data_query_count} 次数据 · ${interfaceCount} 次接口 · ${item.error_event_count} 个错误`;
}

export function TaskVisualizationWorkbench({
  taskId,
  onOpenRelated,
}: {
  taskId: number | null;
  onOpenRelated: (section: RelatedSection, taskId: number) => void;
}) {
  const { workspaces, workspaceError, workspaceLoading, reloadWorkspaces } =
    useVisualizationWorkspaces();
  const [workspaceId, setWorkspaceId] = useState("");
  const [status, setStatus] = useState<AiTaskVisualizationStatus | "">("");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keyword, setKeyword] = useState("");
  const composing = useRef(false);
  const [items, setItems] = useState<AiTaskVisualizationListItem[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(taskId);
  const [detail, setDetail] = useState<AiTaskVisualizationDetail | null>(null);
  const [timeline, setTimeline] = useState<AiTaskTimelineEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [timelineCursor, setTimelineCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");

  const loadTasks = useCallback(async (cursor?: string) => {
    cursor ? setLoadingMore(true) : setLoading(true);
    setError("");
    try {
      const page = await getAiVisualizationTasks({
        workspaceId: workspaceId || undefined,
        status: status || undefined,
        keyword: keyword || undefined,
        cursor,
      });
      setItems((current) => (cursor ? [...current, ...page.items] : page.items));
      setNextCursor(page.has_more ? page.next_cursor ?? null : null);
      if (!cursor && !taskId) {
        setSelectedTaskId((current) =>
          page.items.some((item) => item.task_id === current)
            ? current
            : (page.items[0]?.task_id ?? null),
        );
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "任务列表加载失败");
      if (!cursor) setItems([]);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [keyword, status, taskId, workspaceId]);

  useEffect(() => {
    setItems([]);
    setNextCursor(null);
    void loadTasks();
  }, [loadTasks]);

  useEffect(() => {
    if (taskId) setSelectedTaskId(taskId);
  }, [taskId]);

  useEffect(() => {
    if (!selectedTaskId) {
      setDetail(null);
      setTimeline([]);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setDetailError("");
    Promise.all([
      getAiVisualizationTask(selectedTaskId),
      getAiVisualizationTaskTimeline(selectedTaskId),
    ])
      .then(([nextDetail, nextTimeline]) => {
        if (!active) return;
        setDetail(nextDetail);
        setTimeline(nextTimeline.items);
        setTimelineCursor(nextTimeline.has_more ? nextTimeline.next_cursor ?? null : null);
      })
      .catch((reason) => {
        if (!active) return;
        setDetail(null);
        setTimeline([]);
        setDetailError(reason instanceof Error ? reason.message : "任务详情加载失败");
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedTaskId]);

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    if (!composing.current) setKeyword(keywordDraft.trim());
  };

  const loadMoreTimeline = async () => {
    if (!selectedTaskId || !timelineCursor) return;
    try {
      const page = await getAiVisualizationTaskTimeline(selectedTaskId, {
        cursor: timelineCursor,
      });
      setTimeline((current) => [...current, ...page.items]);
      setTimelineCursor(page.has_more ? page.next_cursor ?? null : null);
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "时间线加载失败");
    }
  };

  return (
    <section className="interface-visualization-page task-visualization-page" aria-labelledby="task-visualization-title">
      <header className="interface-visualization-heading">
        <div>
          <p className="section-eyebrow">AI VISUALIZATION / TASKS</p>
          <h1 id="task-visualization-title">任务可视化</h1>
          <p>按任务汇总 AI 的工具调用、数据查询、接口请求、错误日志和最终结论。</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => void loadTasks()}>
          刷新任务
        </button>
      </header>

      <form className="task-visualization-toolbar" onSubmit={submitSearch}>
        <label>
          工作空间
          <select value={workspaceId} disabled={workspaceLoading} onChange={(event) => setWorkspaceId(event.target.value)}>
            <option value="">全部工作空间</option>
            {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
          </select>
        </label>
        <label>
          状态
          <select value={status} onChange={(event) => setStatus(event.target.value as AiTaskVisualizationStatus | "")}>
            <option value="">全部状态</option>
            {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="task-visualization-keyword">
          搜索任务或结论
          <input
            value={keywordDraft}
            placeholder="输入任务描述、工作空间或结论"
            onChange={(event) => setKeywordDraft(event.target.value)}
            onCompositionStart={() => { composing.current = true; }}
            onCompositionEnd={(event: CompositionEvent<HTMLInputElement>) => {
              composing.current = false;
              setKeywordDraft(event.currentTarget.value);
            }}
          />
        </label>
        <button type="submit" className="primary-button">查询</button>
      </form>

      {workspaceError ? <p className="error-banner visualization-retry-banner" role="alert">{workspaceError}<button type="button" className="secondary-button" onClick={() => void reloadWorkspaces()}>重试</button></p> : null}
      {error ? <p className="error-banner visualization-retry-banner" role="alert">{error}<button type="button" className="secondary-button" onClick={() => void loadTasks()}>重试</button></p> : null}

      <div className="interface-visualization-layout task-visualization-layout">
        <aside className="interface-request-list" aria-label="AI 任务列表">
          {loading && items.length === 0 ? <p className="interface-visualization-state">正在加载最近任务…</p> : null}
          {!loading && items.length === 0 ? <div className="interface-visualization-state"><strong>暂无任务记录</strong><span>AI 工具通过 Context Router MCP 工作后会显示在这里。</span></div> : null}
          {items.map((item) => (
            <button key={item.task_id} type="button" className="interface-request-list-item task-visualization-list-item" data-active={selectedTaskId === item.task_id} onClick={() => setSelectedTaskId(item.task_id)}>
              <span className="interface-request-list-line"><strong>#{item.task_id} · {item.description}</strong><span className={`request-status task-status--${item.status}`}>{statusLabels[item.status]}</span></span>
              <span className="interface-request-list-description">{item.workspace_name} · {item.environment} · {item.agent_name}</span>
              <small>{taskCounts(item)}</small>
              <span className="interface-request-list-meta"><span>最近活动</span><time dateTime={item.last_activity_at}>{formatTime(item.last_activity_at)}</time></span>
            </button>
          ))}
          {nextCursor ? <button type="button" className="secondary-button interface-request-load-more" disabled={loadingMore} onClick={() => void loadTasks(nextCursor)}>{loadingMore ? "加载中…" : "加载更多"}</button> : null}
        </aside>

        <article className="interface-request-detail task-visualization-detail" aria-live="polite">
          {detailLoading ? <p className="interface-visualization-state">正在加载任务详情…</p> : null}
          {detailError ? <p className="error-banner" role="alert">{detailError}</p> : null}
          {!detailLoading && !detail && !detailError ? <div className="interface-visualization-state"><strong>选择一个任务</strong><span>查看完整的执行轨迹和 AI 结论。</span></div> : null}
          {detail ? (
            <>
              <header className="interface-request-detail-heading">
                <div><p className="section-eyebrow">TASK #{detail.task_id}</p><h2>{detail.description}</h2><code>{detail.cwd}</code></div>
                <span className={`request-status task-status--${detail.status}`}>{statusLabels[detail.status]}</span>
              </header>
              <dl className="interface-request-metadata">
                <div><dt>工作空间</dt><dd>{detail.workspace_name}</dd></div>
                <div><dt>环境</dt><dd>{detail.environment}</dd></div>
                <div><dt>AI 工具</dt><dd>{detail.agent_name}</dd></div>
                <div><dt>工具调用</dt><dd>{detail.tool_call_count} 次</dd></div>
                <div><dt>接口结果</dt><dd>{detail.interface_success_count} 成功 / {detail.interface_failed_count} 失败</dd></div>
                <div><dt>错误事件</dt><dd>{detail.error_event_count} 个</dd></div>
              </dl>

              <nav className="visualization-related-actions" aria-label="查看任务关联记录">
                <span>关联记录</span>
                {detail.related.data_visualization ? <button type="button" className="secondary-button" onClick={() => onOpenRelated("data-visualization", detail.task_id)}>数据条件</button> : null}
                {detail.related.interface_visualization ? <button type="button" className="secondary-button" onClick={() => onOpenRelated("interface-visualization", detail.task_id)}>接口请求</button> : null}
                {detail.related.log_visualization ? <button type="button" className="secondary-button" onClick={() => onOpenRelated("log-visualization", detail.task_id)}>错误日志</button> : null}
              </nav>

              <section className="task-conclusion" aria-labelledby="task-conclusion-title">
                <header><div><p className="section-eyebrow">AI CONCLUSION</p><h3 id="task-conclusion-title">任务结论</h3></div>{detail.result ? <CopyVisualizationButton value={[detail.result.summary, detail.result.root_cause, ...detail.result.suggested_actions].filter(Boolean).join("\n\n")} /> : null}</header>
                {detail.result ? (
                  <div className="task-conclusion-content">
                    <p>{detail.result.summary}</p>
                    {detail.result.root_cause ? <div><h4>根因</h4><p>{detail.result.root_cause}</p></div> : null}
                    {detail.result.code_locations.length ? <div><h4>代码位置</h4><ul>{detail.result.code_locations.map((location, index) => <li key={`${location.path}-${index}`}><code>{location.path}{location.line ? `:${location.line}` : ""}</code>{location.description ? <span>{location.description}</span> : null}</li>)}</ul></div> : null}
                    {detail.result.suggested_actions.length ? <div><h4>后续建议</h4><ul>{detail.result.suggested_actions.map((action) => <li key={action}>{action}</li>)}</ul></div> : null}
                    {detail.result.verification.length ? <div><h4>验证结果</h4><ul>{detail.result.verification.map((item, index) => <li key={`${item.type}-${index}`}><strong>{item.description}</strong><span>{item.result}</span></li>)}</ul></div> : null}
                  </div>
                ) : <p className="interface-visualization-state">AI 尚未写入任务结论；现有执行轨迹仍可在下方查看。</p>}
              </section>

              <section className="task-timeline" aria-labelledby="task-timeline-title">
                <header><div><p className="section-eyebrow">ACTIVITY</p><h3 id="task-timeline-title">执行时间线</h3></div><small>最新在前</small></header>
                {timeline.length ? <ol>{timeline.map((event) => <li key={event.event_id}><span className="task-timeline-marker" aria-hidden="true" /><div><header><strong>{event.title}</strong><span>{eventLabels[event.event_type]} · {event.status}</span><time dateTime={event.occurred_at}>{formatTime(event.occurred_at)}</time></header><p>{event.summary}</p></div></li>)}</ol> : <p className="interface-visualization-state">暂无可展示的执行事件。</p>}
                {timelineCursor ? <button type="button" className="secondary-button interface-request-load-more" onClick={() => void loadMoreTimeline()}>加载更早事件</button> : null}
              </section>
            </>
          ) : null}
        </article>
      </div>
    </section>
  );
}
