"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getDocumentReadStatTasks,
  getMcpTrace,
  listDocumentReadStats,
  listWorkspaces,
} from "@/lib/api";
import { DocumentChainAnalyticsPanel } from "@/components/document-chain-analytics";
import type {
  DocumentReadStatItem,
  DocumentReadTaskItem,
  InternalMcpToolName,
  McpTraceDetail,
  McpTraceToolCall,
  WorkspaceSummary,
} from "@/lib/types";

type TraceView = "graph" | "list";

function formattedTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function isInternalCall(call: McpTraceToolCall): boolean {
  return (
    call.tool_name === "prepare_task_context" ||
    call.tool_name === "search_context_documents" ||
    call.tool_name === "read_context_document" ||
    call.tool_name === "search_database_objects" ||
    call.tool_name === "execute_database_query"
  );
}

function internalTraceCalls(calls: McpTraceToolCall[]): McpTraceToolCall[] {
  return calls.filter(isInternalCall);
}

function sortTraceCalls(calls: McpTraceToolCall[]): McpTraceToolCall[] {
  return [...calls].sort((left, right) => {
    const leftTime = Date.parse(left.started_at);
    const rightTime = Date.parse(right.started_at);
    if (!Number.isNaN(leftTime) && !Number.isNaN(rightTime) && leftTime !== rightTime) {
      return leftTime - rightTime;
    }
    return left.tool_call_id - right.tool_call_id;
  });
}

interface TraceGraphRow {
  call: McpTraceToolCall;
  depth: number;
}

function buildTraceGraphRows(calls: McpTraceToolCall[]): TraceGraphRow[] {
  const callMap = new Map<number, McpTraceToolCall>();
  for (const call of calls) {
    callMap.set(call.tool_call_id, call);
  }

  const childrenMap = new Map<number | null, McpTraceToolCall[]>();
  for (const call of calls) {
    const parentId =
      call.parent_tool_call_id !== undefined && call.parent_tool_call_id !== null && callMap.has(call.parent_tool_call_id)
        ? call.parent_tool_call_id
        : null;
    const group = childrenMap.get(parentId) ?? [];
    group.push(call);
    childrenMap.set(parentId, group);
  }

  const rows: TraceGraphRow[] = [];
  const visited = new Set<number>();

  const traverse = (parentId: number | null, depth: number) => {
    const children = childrenMap.get(parentId) ?? [];
    for (const child of children) {
      if (visited.has(child.tool_call_id)) continue;
      visited.add(child.tool_call_id);
      rows.push({ call: child, depth });
      traverse(child.tool_call_id, depth + 1);
    }
  };

  traverse(null, 0);

  for (const call of calls) {
    if (!visited.has(call.tool_call_id)) {
      visited.add(call.tool_call_id);
      rows.push({ call, depth: 0 });
      traverse(call.tool_call_id, 1);
    }
  }

  return rows;
}

function TraceCompletenessBadge({ status }: { status?: string }) {
  if (status === "partial") {
    return <span className="trace-status-badge partial">包含丢失调用</span>;
  }
  if (status === "reconstructed") {
    return <span className="trace-status-badge reconstructed">重构补全</span>;
  }
  return <span className="trace-status-badge complete">完整采集</span>;
}

export function DocumentReadStats() {
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<DocumentReadTaskItem | null>(null);

  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>("");
  const [stats, setStats] = useState<DocumentReadStatItem[]>([]);
  const [tasks, setTasks] = useState<DocumentReadTaskItem[]>([]);
  const [trace, setTrace] = useState<McpTraceDetail | null>(null);

  const [loadingList, setLoadingList] = useState(false);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [loadingTrace, setLoadingTrace] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [traceView, setTraceView] = useState<TraceView>("graph");
  const [selectedCallId, setSelectedCallId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"ranking" | "analytics">("ranking");

  useEffect(() => {
    void listWorkspaces()
      .then(setWorkspaces)
      .catch(() => {});
  }, []);

  useEffect(() => {
    let active = true;
    setLoadingList(true);
    setError(null);
    listDocumentReadStats({
      workspace_id: selectedWorkspaceId || undefined,
      limit: 100,
    })
      .then((data) => {
        if (active) setStats(data);
      })
      .catch((err: Error) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoadingList(false);
      });
    return () => {
      active = false;
    };
  }, [selectedWorkspaceId]);

  useEffect(() => {
    if (!activeDocId) {
      setTasks([]);
      return;
    }
    let active = true;
    setLoadingTasks(true);
    setError(null);
    getDocumentReadStatTasks(activeDocId, { limit: 100 })
      .then((data) => {
        if (active) setTasks(data);
      })
      .catch((err: Error) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoadingTasks(false);
      });
    return () => {
      active = false;
    };
  }, [activeDocId]);

  useEffect(() => {
    if (!activeTask) {
      setTrace(null);
      return;
    }
    let active = true;
    setLoadingTrace(true);
    setSelectedCallId(null);
    setError(null);
    getMcpTrace(activeTask.task_id)
      .then((data) => {
        if (!active) return;
        setTrace(data);
        const firstCall = sortTraceCalls(internalTraceCalls(data.calls))[0];
        setSelectedCallId(firstCall?.tool_call_id ?? null);
      })
      .catch((err: Error) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoadingTrace(false);
      });
    return () => {
      active = false;
    };
  }, [activeTask]);

  const maxReadCount = useMemo(() => {
    if (stats.length === 0) return 1;
    return Math.max(...stats.map((item) => item.read_count));
  }, [stats]);

  const sortedCalls = useMemo(
    () => sortTraceCalls(internalTraceCalls(trace?.calls ?? [])),
    [trace],
  );
  const graphRows = useMemo(
    () => buildTraceGraphRows(sortedCalls),
    [sortedCalls],
  );
  const selectedCall =
    sortedCalls.find((call) => call.tool_call_id === selectedCallId) ?? null;

  return (
    <div className="doc-stats-container">
      {error ? <div className="error-banner">{error}</div> : null}

      {!activeDocId ? (
        <section className="doc-stats-card">
          <div className="doc-stats-header">
            <div>
              <h2 className="doc-stats-title">文档阅读与链路效能</h2>
            </div>
            <div className="doc-stats-filters">
              <label htmlFor="workspace-filter" className="doc-stats-filter-label">
                工作空间：
              </label>
              <select
                id="workspace-filter"
                className="doc-stats-select"
                value={selectedWorkspaceId}
                onChange={(e) => setSelectedWorkspaceId(e.target.value)}
              >
                <option value="">全部工作空间</option>
                {workspaces.map((ws) => (
                  <option key={ws.id} value={ws.id}>
                    {ws.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="doc-stats-tabs" role="tablist" aria-label="文档统计视图">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "ranking"}
              data-active={activeTab === "ranking"}
              onClick={() => setActiveTab("ranking")}
            >
              文档阅读排行榜
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "analytics"}
              data-active={activeTab === "analytics"}
              onClick={() => setActiveTab("analytics")}
            >
              Agent 检索效能诊断
            </button>
          </div>

          {activeTab === "analytics" ? (
            <div className="p-2">
              <DocumentChainAnalyticsPanel workspaceId={selectedWorkspaceId || undefined} />
            </div>
          ) : loadingList ? (
            <div className="doc-stats-loading">正在加载统计数据…</div>
          ) : stats.length === 0 ? (
            <div className="doc-stats-empty">暂无文档阅读数据</div>
          ) : (
            <div className="doc-stats-table-wrapper">
              <table className="doc-stats-table">
                <thead>
                  <tr>
                    <th>文档路径 / ID</th>
                    <th style={{ width: "200px" }}>阅读次数</th>
                    <th style={{ width: "120px" }}>关联任务数</th>
                    <th style={{ width: "160px" }}>最后阅读时间</th>
                    <th style={{ width: "100px", textAlign: "right" }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.map((item) => {
                    const percent = Math.round((item.read_count / maxReadCount) * 100);
                    return (
                      <tr key={item.document_id}>
                        <td className="doc-path-cell font-mono">
                          {item.document_path || item.document_id}
                        </td>
                        <td>
                          <div className="doc-progress-cell">
                            <span className="doc-count-badge">{item.read_count} 次</span>
                            <div className="doc-progress-track">
                              <div
                                className="doc-progress-bar"
                                style={{ width: `${percent}%` }}
                              />
                            </div>
                          </div>
                        </td>
                        <td className="doc-meta-cell">{item.task_count} 个任务</td>
                        <td className="doc-meta-cell">{formattedTime(item.last_read_at)}</td>
                        <td style={{ textAlign: "right" }}>
                          <button
                            type="button"
                            className="doc-stats-action-btn"
                            onClick={() => setActiveDocId(item.document_id)}
                          >
                            查看任务
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : !activeTask ? (
        <section className="doc-stats-card">
          <div className="doc-stats-header">
            <div className="doc-stats-breadcrumb">
              <button
                type="button"
                className="doc-stats-back-btn"
                onClick={() => setActiveDocId(null)}
              >
                ← 返回文档列表
              </button>
              <span className="doc-stats-divider">/</span>
              <h2 className="doc-stats-title font-mono">{activeDocId}</h2>
            </div>
          </div>

          {loadingTasks ? (
            <div className="doc-stats-loading">正在加载任务关联数据…</div>
          ) : tasks.length === 0 ? (
            <div className="doc-stats-empty">暂无关联的任务记录</div>
          ) : (
            <div className="doc-stats-table-wrapper">
              <table className="doc-stats-table">
                <thead>
                  <tr>
                    <th style={{ width: "90px" }}>Task ID</th>
                    <th>任务描述</th>
                    <th style={{ width: "130px" }}>Agent</th>
                    <th style={{ width: "100px" }}>阅读次数</th>
                    <th>读取章节</th>
                    <th style={{ width: "160px" }}>创建时间</th>
                    <th style={{ width: "100px", textAlign: "right" }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {tasks.map((taskItem) => (
                    <tr key={taskItem.task_id}>
                      <td className="font-mono text-muted">#{taskItem.task_id}</td>
                      <td>
                        <span className="font-medium">{taskItem.task}</span>
                        {taskItem.active_project_name ? (
                          <span className="doc-tag-project">
                            {taskItem.active_project_name}
                          </span>
                        ) : null}
                      </td>
                      <td className="doc-meta-cell">{taskItem.agent_name || "未标记"}</td>
                      <td className="font-semibold">{taskItem.read_count} 次</td>
                      <td>
                        <div className="doc-section-tags">
                          {taskItem.sections.length > 0 ? (
                            taskItem.sections.map((sec, idx) => (
                              <span key={idx} className="doc-section-tag">
                                {sec}
                              </span>
                            ))
                          ) : (
                            <span className="text-muted">全文 / 未指定章节</span>
                          )}
                        </div>
                      </td>
                      <td className="doc-meta-cell">{formattedTime(taskItem.created_at)}</td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          className="doc-stats-action-btn"
                          onClick={() => setActiveTask(taskItem)}
                        >
                          调用链路
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : (
        <section className="doc-stats-card">
          <div className="doc-stats-header">
            <div className="doc-stats-breadcrumb">
              <button
                type="button"
                className="doc-stats-back-btn"
                onClick={() => setActiveTask(null)}
              >
                ← 返回关联任务列表
              </button>
              <span className="doc-stats-divider">/</span>
              <h2 className="doc-stats-title">Task #{activeTask.task_id} 调用链路</h2>
            </div>
          </div>

          {loadingTrace ? (
            <div className="doc-stats-loading">正在加载 Trace 链路…</div>
          ) : !trace ? (
            <div className="doc-stats-empty">暂无 Trace 数据</div>
          ) : (
            <div className="trace-main-panel">
              <header className="trace-summary">
                <div>
                  <div className="trace-summary-chips">
                    <span className="file-chip">任务 #{trace.task_id}</span>
                    <TraceCompletenessBadge status={trace.trace_status} />
                  </div>
                  <h3 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "6px 0 0" }}>
                    {trace.task}
                  </h3>
                  <p className="text-muted" style={{ fontSize: "0.76rem", margin: "4px 0 0" }}>
                    {trace.project_name} · {trace.agent_name ?? "未标记 Agent"} · {sortedCalls.length} 次内部调用
                  </p>
                </div>
                <div className="trace-view-tabs" role="tablist" aria-label="内部调用视图">
                  {([
                    ["graph", "调用树"],
                    ["list", "调用列表"],
                  ] as const).map(([value, label]) => (
                    <button
                      type="button"
                      role="tab"
                      aria-selected={traceView === value}
                      data-active={traceView === value}
                      onClick={() => setTraceView(value)}
                      key={value}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </header>

              <div className="trace-content-layout">
                <section className="trace-visual" data-view={traceView}>
                  {sortedCalls.length === 0 ? (
                    <div className="trace-empty-message">未捕获到相关的 MCP 工具调用。</div>
                  ) : traceView === "graph" ? (
                    <div className="trace-graph-view">
                      {graphRows.map(({ call, depth }) => (
                        <button
                          type="button"
                          key={call.tool_call_id}
                          className="trace-call-item"
                          data-selected={selectedCallId === call.tool_call_id}
                          style={{
                            marginLeft: `${depth * 16}px`,
                            width: `calc(100% - ${depth * 16}px)`,
                          }}
                          onClick={() => setSelectedCallId(call.tool_call_id)}
                        >
                          <span className="font-mono">{call.tool_name}</span>
                          <span className="text-muted">
                            {call.duration_ms ? `${call.duration_ms}ms` : "-"}
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="trace-list-view">
                      {sortedCalls.map((call) => (
                        <button
                          type="button"
                          key={call.tool_call_id}
                          className="trace-call-item"
                          data-selected={selectedCallId === call.tool_call_id}
                          onClick={() => setSelectedCallId(call.tool_call_id)}
                        >
                          <span className="font-mono">{call.tool_name}</span>
                          <span className="text-muted">
                            {call.duration_ms ? `${call.duration_ms}ms` : "-"}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </section>

                <aside className="trace-detail-pane">
                  {selectedCall ? (
                    <div className="trace-detail-content">
                      <div className="trace-detail-section">
                        <div className="font-bold text-sm">{selectedCall.tool_name}</div>
                        <div className="text-muted text-xs">
                          Tool Call ID: {selectedCall.tool_call_id}
                        </div>
                      </div>
                      <div className="trace-detail-section">
                        <div className="trace-detail-label">输入参数</div>
                        <pre className="trace-json-box font-mono">
                          {JSON.stringify(selectedCall.request_summary, null, 2)}
                        </pre>
                      </div>
                      <div className="trace-detail-section">
                        <div className="trace-detail-label">返回结果摘要</div>
                        <pre className="trace-json-box font-mono">
                          {JSON.stringify(selectedCall.result_summary, null, 2)}
                        </pre>
                      </div>
                    </div>
                  ) : (
                    <div className="trace-detail-empty">
                      请选择左侧的具体调用节点查看详情
                    </div>
                  )}
                </aside>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
