"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CSSProperties } from "react";

import { DatabaseCallPayloadModal } from "@/components/database-call-payload-modal";
import {
  getMcpTrace,
  listMcpTraces,
} from "@/lib/api";
import { isDatabaseMcpCall } from "@/lib/database-call-payload";
import {
  INTERNAL_MCP_TOOL_NAMES,
  buildTraceGraphRows,
  internalTraceCalls,
  sortTraceCalls,
  traceCompletenessLabel,
  traceWarningMessages,
} from "@/lib/mcp-traces";
import type {
  InternalMcpToolName,
  McpTraceArtifact,
  McpTraceCompleteness,
  McpTraceDetail,
  McpTraceSummary,
  McpTraceToolCall,
} from "@/lib/types";

type TraceView = "graph" | "list";

function formattedTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function sourceLabel(source: McpTraceToolCall["source"]): string {
  if (source === "legacy") return "历史记录";
  return "服务端观测";
}

function statusLabel(status: McpTraceToolCall["status"]): string {
  if (status === "running") return "运行中";
  if (status === "ok") return "成功";
  if (status === "cancelled") return "已取消";
  return "失败";
}

function artifactKind(artifact: McpTraceArtifact): string {
  return artifact.kind;
}

function artifactSummary(artifact: McpTraceArtifact): string | null {
  const kind = artifactKind(artifact);
  if (kind === "document_read" && "documents" in artifact) {
    const documents = Array.isArray(artifact.documents)
      ? artifact.documents
      : [];
    return `读取 ${documents.length} 个文档`;
  }
  if (kind === "database_call") {
    const database =
      "database" in artifact && typeof artifact.database === "string"
        ? artifact.database
        : "数据库";
    const returnedCount =
      ("returned_count" in artifact &&
      typeof artifact.returned_count === "number"
        ? artifact.returned_count
        : null);
    const count =
      returnedCount != null
        ? ` · 返回 ${returnedCount} 项`
        : "";
    return `${database}${count}`;
  }
  return null;
}

function TraceStatus({
  status,
}: {
  status: McpTraceToolCall["status"];
}) {
  return (
    <span className="trace-status" data-status={status}>
      <span aria-hidden="true" />
      {statusLabel(status)}
    </span>
  );
}

function TraceCompletenessBadge({
  status,
}: {
  status: McpTraceCompleteness;
}) {
  return (
    <span className="trace-completeness-badge" data-status={status}>
      {traceCompletenessLabel(status)}
    </span>
  );
}

function TraceCompletenessNotice({
  status,
  warnings,
}: {
  status: McpTraceCompleteness;
  warnings: string[];
}) {
  if (status === "complete") return null;
  const messages = traceWarningMessages(warnings);
  const fallback =
    status === "running"
      ? "仍有内部工具调用正在运行，链路内容会继续更新。"
      : "这条链路的部分历史信息可能无法完整还原。";

  return (
    <p className="trace-completeness-notice" data-status={status}>
      {messages.length > 0 ? messages.join(" ") : fallback}
    </p>
  );
}

interface TraceCallCardProps {
  call: McpTraceToolCall;
  active: boolean;
  onSelect: () => void;
}

function TraceCallCard({ call, active, onSelect }: TraceCallCardProps) {
  return (
    <button
      type="button"
      className="trace-call-card"
      data-active={active}
      data-status={call.status}
      onClick={onSelect}
    >
      <span className="trace-sequence" aria-label={`第 ${call.sequence} 次调用`}>
        {call.sequence}
      </span>
      {call.source === "legacy" ? (
        <span className="trace-call-kicker">历史记录</span>
      ) : null}
      <strong>{call.tool_name}</strong>
      <span className="trace-call-meta">
        <TraceStatus status={call.status} />
        <span>{call.duration_ms == null ? "—" : `${call.duration_ms} ms`}</span>
        <span>{formattedTime(call.started_at)}</span>
      </span>
      {call.artifacts.map((artifact, index) => {
        const summary = artifactSummary(artifact);
        return summary ? <small key={`${artifactKind(artifact)}-${index}`}>{summary}</small> : null;
      })}
      {call.error_code ? (
        <code className="trace-error-code">{call.error_code}</code>
      ) : null}
    </button>
  );
}

interface TraceCallDetailProps {
  call: McpTraceToolCall | null;
  onClose: () => void;
  onOpenDatabasePayload: (call: McpTraceToolCall) => void;
}

function TraceCallDetail({
  call,
  onClose,
  onOpenDatabasePayload,
}: TraceCallDetailProps) {
  if (!call) {
    return (
      <aside className="trace-call-detail trace-call-detail-empty">
        <span className="section-eyebrow">CALL DETAIL</span>
        <h3>选择一个调用节点</h3>
        <p>这里会展示调用状态、耗时和关联产物；数据库工具可按需查看出入参详情。</p>
      </aside>
    );
  }

  return (
    <aside className="trace-call-detail" aria-label="MCP 调用详情">
      <header>
        <div>
          <span className="section-eyebrow">CALL #{call.sequence}</span>
          <h3>{call.tool_name}</h3>
        </div>
        <button
          type="button"
          className="trace-detail-close"
          aria-label="关闭调用详情"
          onClick={onClose}
        >
          ×
        </button>
      </header>
      <dl className="trace-detail-facts">
        <div>
          <dt>调用范围</dt>
          <dd>Context Router /mcp</dd>
        </div>
        <div>
          <dt>采集方式</dt>
          <dd>{sourceLabel(call.source)}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd><TraceStatus status={call.status} /></dd>
        </div>
        <div>
          <dt>耗时</dt>
          <dd>{call.duration_ms == null ? "—" : `${call.duration_ms} ms`}</dd>
        </div>
        <div>
          <dt>调用 ID</dt>
          <dd>{call.tool_call_id}</dd>
        </div>
        <div>
          <dt>父调用</dt>
          <dd>{call.parent_tool_call_id ?? "任务根节点"}</dd>
        </div>
      </dl>
      {isDatabaseMcpCall(call) && call.request_summary ? (
        <section className="trace-json-summary">
          <h4>参数摘要</h4>
          <pre>{JSON.stringify(call.request_summary, null, 2)}</pre>
        </section>
      ) : null}
      {isDatabaseMcpCall(call) && call.result_summary ? (
        <section className="trace-json-summary">
          <h4>结果摘要</h4>
          <pre>{JSON.stringify(call.result_summary, null, 2)}</pre>
        </section>
      ) : null}
      {call.artifacts.length > 0 ? (
        <section className="trace-artifact-summary">
          <h4>关联产物</h4>
          <ul>
            {call.artifacts.map((artifact, index) => (
              <li key={`${artifactKind(artifact)}-${index}`}>
                {artifactSummary(artifact) ?? artifactKind(artifact)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {call.error_code ? (
        <p className="trace-detail-error">错误码：{call.error_code}</p>
      ) : null}
      {isDatabaseMcpCall(call) ? (
        <section className="trace-database-payload-action">
          <button
            type="button"
            className="primary-button"
            onClick={() => onOpenDatabasePayload(call)}
          >
            查看出入参详情
          </button>
          {call.database_payload_available === false ? (
            <small>
              {call.database_payload_reason === "capture_disabled"
                ? "详情采集未启用"
                : call.database_payload_status === "expired"
                ? "详情已过期"
                : call.database_payload_status === "capture_failed"
                  ? "详情采集失败"
              : "历史调用可能没有详情"}
            </small>
          ) : null}
        </section>
      ) : null}
    </aside>
  );
}

export function TraceExplorer() {
  const [traces, setTraces] = useState<McpTraceSummary[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [trace, setTrace] = useState<McpTraceDetail | null>(null);
  const [view, setView] = useState<TraceView>("graph");
  const [selectedCallId, setSelectedCallId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [toolName, setToolName] = useState<InternalMcpToolName | "">("");
  const [databasePayloadCall, setDatabasePayloadCall] =
    useState<McpTraceToolCall | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingTrace, setLoadingTrace] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const traceListRequestIdRef = useRef(0);

  const loadTraces = useCallback(async () => {
    const requestId = traceListRequestIdRef.current + 1;
    traceListRequestIdRef.current = requestId;
    setLoadingList(true);
    try {
      const nextTraces = await listMcpTraces({
        toolName: toolName || undefined,
        keyword: searchKeyword || undefined,
        limit: 100,
      });
      if (traceListRequestIdRef.current !== requestId) return;
      setTraces(nextTraces);
      setSelectedTaskId((current) => {
        if (current && nextTraces.some((item) => item.task_id === current)) {
          return current;
        }
        return nextTraces[0]?.task_id ?? null;
      });
      setError(null);
    } catch (requestError) {
      if (traceListRequestIdRef.current !== requestId) return;
      setError((requestError as Error).message);
    } finally {
      if (traceListRequestIdRef.current === requestId) {
        setLoadingList(false);
      }
    }
  }, [searchKeyword, toolName]);

  useEffect(() => {
    void loadTraces();
  }, [loadTraces]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearchKeyword(query.trim());
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (selectedTaskId === null) {
      setTrace(null);
      return;
    }

    let active = true;
    setLoadingTrace(true);
    setSelectedCallId(null);
    setDatabasePayloadCall(null);
    void getMcpTrace(selectedTaskId)
      .then((nextTrace) => {
        if (!active) return;
        setTrace(nextTrace);
        const firstInternalCall = sortTraceCalls(
          internalTraceCalls(nextTrace.calls),
        )[0];
        setSelectedCallId(firstInternalCall?.tool_call_id ?? null);
        setError(null);
      })
      .catch((requestError: Error) => {
        if (!active) return;
        setTrace(null);
        setError(requestError.message);
      })
      .finally(() => {
        if (active) setLoadingTrace(false);
      });

    return () => {
      active = false;
    };
  }, [selectedTaskId]);

  useEffect(() => {
    if (loadingList) return;
    if (
      selectedTaskId !== null &&
      traces.some((item) => item.task_id === selectedTaskId)
    ) {
      return;
    }
    setSelectedTaskId(traces[0]?.task_id ?? null);
  }, [loadingList, selectedTaskId, traces]);

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
  const displayedErrorCount = sortedCalls.filter(
    (call) => call.status === "error",
  ).length;

  return (
    <section className="trace-explorer">
      {error ? <div className="error-banner">{error}</div> : null}

      <div className="trace-workspace">
        <aside className="trace-task-panel" aria-label="MCP 任务列表">
          <div className="trace-filter-panel">
            <div className="trace-filter-row">
              <label className="trace-search">
                <span>搜索任务</span>
                <input
                  type="search"
                  value={query}
                  placeholder="任务、项目或目录"
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              <label>
                <span>内部工具</span>
                <select
                  value={toolName}
                  onChange={(event) =>
                    setToolName(event.target.value as InternalMcpToolName | "")
                  }
                >
                  <option value="">全部</option>
                  {INTERNAL_MCP_TOOL_NAMES.map((name) => (
                    <option value={name} key={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="trace-task-list">
            {loadingList ? (
              <p className="trace-panel-message">正在读取任务链路…</p>
            ) : null}
            {!loadingList && traces.length === 0 ? (
              <p className="trace-panel-message">没有符合当前条件的任务。</p>
            ) : null}
            {traces.map((item) => (
              <button
                type="button"
                className="trace-task-item"
                data-active={item.task_id === selectedTaskId}
                onClick={() => setSelectedTaskId(item.task_id)}
                key={item.task_id}
              >
                <span className="trace-task-heading">
                  <strong>#{item.task_id} · {item.agent_name ?? "未标记 Agent"}</strong>
                  <span className="trace-task-indicators">
                    <TraceCompletenessBadge status={item.trace_status} />
                    {item.error_count > 0 ? (
                      <span className="trace-error-count">{item.error_count}</span>
                    ) : null}
                  </span>
                </span>
                <span className="trace-task-title">{item.task}</span>
                <small>{item.project_name} · {item.call_count} 次内部调用</small>
                <small>{formattedTime(item.last_activity_at)}</small>
              </button>
            ))}
          </div>
        </aside>

        <main className="trace-main-panel">
          {loadingTrace ? (
            <div className="trace-main-empty">
              <p>正在加载 MCP 链路…</p>
            </div>
          ) : null}
          {!loadingTrace && !trace ? (
            <div className="trace-main-empty">
              <h2>选择一个任务</h2>
              <p>选择左侧任务后查看工具调用、文档读取和数据库访问链路。</p>
            </div>
          ) : null}
          {!loadingTrace && trace ? (
            <>
              <header className="trace-summary">
                <div>
                  <div className="trace-summary-chips">
                    <span className="file-chip">任务 #{trace.task_id}</span>
                    <TraceCompletenessBadge status={trace.trace_status} />
                  </div>
                  <h2>{trace.task}</h2>
                  <p>
                    {trace.project_name} · {trace.agent_name ?? "未标记 Agent"} · {sortedCalls.length} 次内部调用
                    {displayedErrorCount > 0
                      ? ` · ${displayedErrorCount} 个错误`
                      : ""}
                  </p>
                  <small className="trace-order-note">
                    普通节点只表示服务端执行顺序；仅带“来自调用”标记的分支表示显式父子关系。
                  </small>
                  <TraceCompletenessNotice
                    status={trace.trace_status}
                    warnings={trace.warnings}
                  />
                </div>
                <div className="trace-view-tabs" role="tablist" aria-label="内部调用视图">
                  {([
                    ["graph", "调用树"],
                    ["list", "调用列表"],
                  ] as const).map(([value, label]) => (
                    <button
                      type="button"
                      role="tab"
                      aria-selected={view === value}
                      data-active={view === value}
                      onClick={() => setView(value)}
                      key={value}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </header>

              <div className="trace-content-layout">
                <section className="trace-visual" data-view={view}>
                  {sortedCalls.length === 0 ? (
                    <div className="trace-main-empty">
                      <h3>这个任务还没有 MCP 调用</h3>
                    </div>
                  ) : null}

                  {view === "graph" && sortedCalls.length > 0 ? (
                    <div className="trace-graph">
                      <article className="trace-root-node">
                        <span>任务根节点</span>
                        <strong>#{trace.task_id} · {trace.agent_name ?? "Agent"}</strong>
                        <small>{formattedTime(trace.created_at)}</small>
                      </article>
                      {graphRows.map((row) => (
                        <div
                          className="trace-graph-row"
                          style={{ "--trace-depth": row.depth } as CSSProperties}
                          data-nested={row.depth > 0}
                          key={row.call.tool_call_id}
                        >
                          {row.parentSequence ? (
                            <span className="trace-parent-label">
                              来自调用 #{row.parentSequence}
                            </span>
                          ) : null}
                          <TraceCallCard
                            call={row.call}
                            active={selectedCallId === row.call.tool_call_id}
                            onSelect={() => setSelectedCallId(row.call.tool_call_id)}
                          />
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {view === "list" && sortedCalls.length > 0 ? (
                    <div className="trace-call-list">
                      <div className="trace-call-list-header" aria-hidden="true">
                        <span>顺序</span>
                        <span>内部工具</span>
                        <span>状态</span>
                        <span>耗时</span>
                        <span>开始时间</span>
                      </div>
                      {sortedCalls.map((call) => (
                        <button
                          type="button"
                          className="trace-call-list-item"
                          data-active={selectedCallId === call.tool_call_id}
                          onClick={() => setSelectedCallId(call.tool_call_id)}
                          key={call.tool_call_id}
                        >
                          <strong>#{call.sequence}</strong>
                          <span>
                            {call.source === "legacy" ? (
                              <small>历史记录</small>
                            ) : null}
                            <code>{call.tool_name}</code>
                          </span>
                          <TraceStatus status={call.status} />
                          <span>{call.duration_ms == null ? "—" : `${call.duration_ms} ms`}</span>
                          <span>{formattedTime(call.started_at)}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}

                </section>

                <TraceCallDetail
                  call={selectedCall}
                  onClose={() => setSelectedCallId(null)}
                  onOpenDatabasePayload={setDatabasePayloadCall}
                />
              </div>
            </>
          ) : null}
        </main>
      </div>

      {trace && databasePayloadCall ? (
        <DatabaseCallPayloadModal
          taskId={trace.task_id}
          call={databasePayloadCall}
          onClose={() => setDatabasePayloadCall(null)}
        />
      ) : null}
    </section>
  );
}
