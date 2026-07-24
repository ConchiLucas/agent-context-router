"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CSSProperties } from "react";

import { DocumentTree } from "@/components/document-tree";
import { MarkdownViewer } from "@/components/markdown-viewer";
import {
  getDocumentDetail,
  getMcpTrace,
  getProjectTree,
  listMcpTraces,
} from "@/lib/api";
import {
  buildTraceDocumentCallNumbers,
  buildTraceGraphRows,
  documentsForTraceCall,
  filterMcpTraces,
  sortTraceCalls,
} from "@/lib/mcp-traces";
import type {
  DocumentDetail,
  DocumentTreeNode,
  McpTraceArtifact,
  McpTraceDetail,
  McpTraceSummary,
  McpTraceToolCall,
} from "@/lib/types";

type TraceView = "graph" | "list" | "tree";
type TraceStatusFilter = "all" | "ok" | "error";

function formattedTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function sourceLabel(source: McpTraceToolCall["source"]): string {
  if (source === "gateway") return "Gateway 观测";
  if (source === "reported") return "客户端上报";
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
      <span className="trace-call-kicker">
        {call.server_name} · {sourceLabel(call.source)}
      </span>
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

interface TraceDocumentCardsProps {
  call: McpTraceToolCall;
  canOpenDocuments: boolean;
  onOpenDocument: (documentId: string) => void;
}

function TraceDocumentCards({
  call,
  canOpenDocuments,
  onOpenDocument,
}: TraceDocumentCardsProps) {
  const documents = documentsForTraceCall(call);
  if (documents.length === 0) return null;

  return (
    <div className="trace-document-row">
      {documents.map((document) => (
        <button
          type="button"
          className="trace-document-card"
          data-status={document.status}
          disabled={document.status === "error" || !canOpenDocuments}
          onClick={(event) => {
            event.stopPropagation();
            onOpenDocument(document.document_id);
          }}
          key={`${call.tool_call_id}-${document.position}-${document.document_id}`}
        >
          <span>文档 {document.position}</span>
          <strong>{document.path ?? document.document_id}</strong>
          {document.section ? <small>章节：{document.section}</small> : null}
          {document.status === "error" ? (
            <code>{document.error_code ?? "读取失败"}</code>
          ) : null}
        </button>
      ))}
    </div>
  );
}

interface TraceCallDetailProps {
  call: McpTraceToolCall | null;
  onClose: () => void;
}

function TraceCallDetail({ call, onClose }: TraceCallDetailProps) {
  if (!call) {
    return (
      <aside className="trace-call-detail trace-call-detail-empty">
        <span className="section-eyebrow">CALL DETAIL</span>
        <h3>选择一个调用节点</h3>
        <p>这里会展示服务端保存的脱敏参数摘要、结果摘要和关联产物。</p>
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
          <dt>服务</dt>
          <dd>{call.server_name}</dd>
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
      {call.request_summary ? (
        <section className="trace-json-summary">
          <h4>参数摘要</h4>
          <pre>{JSON.stringify(call.request_summary, null, 2)}</pre>
        </section>
      ) : null}
      {call.result_summary ? (
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
    </aside>
  );
}

interface TraceDocumentDrawerProps {
  detail: DocumentDetail | null;
  loading: boolean;
  onClose: () => void;
}

function TraceDocumentDrawer({
  detail,
  loading,
  onClose,
}: TraceDocumentDrawerProps) {
  return (
    <aside
      className="document-detail-drawer trace-document-drawer"
      role="dialog"
      aria-label="Markdown 文档详情"
    >
      <button
        type="button"
        className="close-button detail-close-button"
        aria-label="关闭文档详情"
        onClick={onClose}
      >
        ×
      </button>
      {loading ? (
        <p className="empty-message">正在读取内存中的文档内容…</p>
      ) : detail ? (
        <>
          <header className="document-detail-header">
            <div>
              <span className="file-chip">Markdown</span>
              <h2>{detail.description}</h2>
            </div>
            <code>{detail.relative_path ?? detail.path}</code>
          </header>
          {detail.error ? <div className="error-banner">{detail.error}</div> : null}
          <MarkdownViewer content={detail.content} />
        </>
      ) : (
        <p className="empty-message">文档内容读取失败。</p>
      )}
    </aside>
  );
}

interface TraceExplorerProps {
  projectId?: string;
}

export function TraceExplorer({ projectId }: TraceExplorerProps) {
  const [traces, setTraces] = useState<McpTraceSummary[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [trace, setTrace] = useState<McpTraceDetail | null>(null);
  const [view, setView] = useState<TraceView>("graph");
  const [selectedCallId, setSelectedCallId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [agentName, setAgentName] = useState("");
  const [serverName, setServerName] = useState("");
  const [status, setStatus] = useState<TraceStatusFilter>("all");
  const [tree, setTree] = useState<DocumentTreeNode | null>(null);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [documentDetail, setDocumentDetail] = useState<DocumentDetail | null>(
    null,
  );
  const [documentLoading, setDocumentLoading] = useState(false);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingTrace, setLoadingTrace] = useState(false);
  const [traceRefreshToken, setTraceRefreshToken] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const documentRequestIdRef = useRef(0);

  const loadTraces = useCallback(async () => {
    setLoadingList(true);
    try {
      const nextTraces = await listMcpTraces({ projectId, limit: 100 });
      setTraces(nextTraces);
      setSelectedTaskId((current) => {
        if (current && nextTraces.some((item) => item.task_id === current)) {
          return current;
        }
        return nextTraces[0]?.task_id ?? null;
      });
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setLoadingList(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadTraces();
  }, [loadTraces]);

  useEffect(() => {
    if (selectedTaskId === null) {
      setTrace(null);
      return;
    }

    let active = true;
    setLoadingTrace(true);
    setSelectedCallId(null);
    setDocumentDetail(null);
    documentRequestIdRef.current += 1;
    void getMcpTrace(selectedTaskId)
      .then((nextTrace) => {
        if (!active) return;
        setTrace(nextTrace);
        setSelectedCallId(nextTrace.calls[0]?.tool_call_id ?? null);
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
  }, [selectedTaskId, traceRefreshToken]);

  useEffect(() => {
    if (!trace?.project_id) {
      setTree(null);
      setTreeError(null);
      return;
    }

    let active = true;
    setTree(null);
    setTreeError(null);
    void getProjectTree(trace.project_id)
      .then((nextTree) => {
        if (active) setTree(nextTree);
      })
      .catch((requestError: Error) => {
        if (active) setTreeError(requestError.message);
      });

    return () => {
      active = false;
    };
  }, [trace?.project_id]);

  const agentNames = useMemo(
    () =>
      Array.from(
        new Set(
          traces
            .map((item) => item.agent_name)
            .filter((item): item is string => Boolean(item)),
        ),
      ).sort((left, right) => left.localeCompare(right)),
    [traces],
  );
  const serverNames = useMemo(
    () =>
      Array.from(new Set(traces.flatMap((item) => item.server_names))).sort(
        (left, right) => left.localeCompare(right),
      ),
    [traces],
  );
  const filteredTraces = useMemo(
    () =>
      filterMcpTraces(traces, {
        query,
        agentName,
        serverName,
        status,
      }),
    [agentName, query, serverName, status, traces],
  );

  useEffect(() => {
    if (loadingList) return;
    if (
      selectedTaskId !== null &&
      filteredTraces.some((item) => item.task_id === selectedTaskId)
    ) {
      return;
    }
    setSelectedTaskId(filteredTraces[0]?.task_id ?? null);
  }, [filteredTraces, loadingList, selectedTaskId]);

  const sortedCalls = useMemo(
    () => sortTraceCalls(trace?.calls ?? []),
    [trace],
  );
  const graphRows = useMemo(
    () => buildTraceGraphRows(trace?.calls ?? []),
    [trace],
  );
  const documentCallNumbers = useMemo(
    () => buildTraceDocumentCallNumbers(trace?.calls ?? []),
    [trace],
  );
  const selectedCall =
    sortedCalls.find((call) => call.tool_call_id === selectedCallId) ?? null;

  async function openDocument(documentId: string) {
    if (!trace?.project_id) return;
    const requestId = documentRequestIdRef.current + 1;
    documentRequestIdRef.current = requestId;
    setDocumentLoading(true);
    setDocumentDetail(null);
    try {
      const nextDetail = await getDocumentDetail(trace.project_id, documentId);
      if (documentRequestIdRef.current !== requestId) return;
      setDocumentDetail(nextDetail);
      setError(null);
    } catch (requestError) {
      if (documentRequestIdRef.current !== requestId) return;
      setError((requestError as Error).message);
    } finally {
      if (documentRequestIdRef.current === requestId) {
        setDocumentLoading(false);
      }
    }
  }

  function closeDocument() {
    documentRequestIdRef.current += 1;
    setDocumentDetail(null);
    setDocumentLoading(false);
  }

  async function refreshTraces() {
    await loadTraces();
    setTraceRefreshToken((current) => current + 1);
  }

  return (
    <section className="trace-explorer">
      <header className="trace-page-toolbar">
        <div>
          <span className="section-eyebrow">MCP TRACES</span>
          <h1>链路管理</h1>
          <p>
            查看 Codex、Antigravity 等客户端经过 Context Router 的 MCP 调用。
            {projectId ? " 当前仅显示所选项目。" : ""}
          </p>
        </div>
        <button
          type="button"
          className="secondary-button"
          disabled={loadingList}
          onClick={() => void refreshTraces()}
        >
          {loadingList ? "正在刷新…" : "刷新链路"}
        </button>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="trace-workspace">
        <aside className="trace-task-panel" aria-label="MCP 任务列表">
          <div className="trace-filter-panel">
            <label className="trace-search">
              <span>搜索任务</span>
              <input
                type="search"
                value={query}
                placeholder="任务、项目、目录或任务号"
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <div className="trace-filter-row">
              <label>
                <span>Agent</span>
                <select
                  value={agentName}
                  onChange={(event) => setAgentName(event.target.value)}
                >
                  <option value="">全部</option>
                  {agentNames.map((name) => (
                    <option value={name} key={name}>{name}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>MCP 服务</span>
                <select
                  value={serverName}
                  onChange={(event) => setServerName(event.target.value)}
                >
                  <option value="">全部</option>
                  {serverNames.map((name) => (
                    <option value={name} key={name}>{name}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="trace-status-filters" aria-label="任务状态筛选">
              {([
                ["all", "全部"],
                ["ok", "无错误"],
                ["error", "有错误"],
              ] as const).map(([value, label]) => (
                <button
                  type="button"
                  data-active={status === value}
                  onClick={() => setStatus(value)}
                  key={value}
                >
                  {label}
                </button>
              ))}
            </div>
            <p className="trace-filter-scope">
              当前筛选仅作用于已加载的最近 100 条任务链路。
            </p>
          </div>

          <div className="trace-task-list">
            {loadingList ? (
              <p className="trace-panel-message">正在读取任务链路…</p>
            ) : null}
            {!loadingList && filteredTraces.length === 0 ? (
              <p className="trace-panel-message">没有符合当前条件的任务。</p>
            ) : null}
            {filteredTraces.map((item) => (
              <button
                type="button"
                className="trace-task-item"
                data-active={item.task_id === selectedTaskId}
                onClick={() => setSelectedTaskId(item.task_id)}
                key={item.task_id}
              >
                <span className="trace-task-heading">
                  <strong>#{item.task_id} · {item.agent_name ?? "未标记 Agent"}</strong>
                  {item.error_count > 0 ? (
                    <span className="trace-error-count">{item.error_count}</span>
                  ) : null}
                </span>
                <span className="trace-task-title">{item.task}</span>
                <small>{item.project_name} · {item.call_count} 次调用</small>
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
                  <span className="file-chip">任务 #{trace.task_id}</span>
                  <h2>{trace.task}</h2>
                  <p>
                    {trace.project_name} · {trace.agent_name ?? "未标记 Agent"} · {trace.call_count} 次调用
                    {trace.error_count > 0 ? ` · ${trace.error_count} 个错误` : ""}
                  </p>
                </div>
                <div className="trace-view-tabs" role="tablist" aria-label="链路视图">
                  {([
                    ["graph", "链路图"],
                    ["list", "调用列表"],
                    ["tree", "文档树"],
                  ] as const).map(([value, label]) => (
                    <button
                      type="button"
                      role="tab"
                      aria-selected={view === value}
                      data-active={view === value}
                      onClick={() => {
                        setView(value);
                        closeDocument();
                      }}
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
                          <TraceDocumentCards
                            call={row.call}
                            canOpenDocuments={Boolean(trace.project_id)}
                            onOpenDocument={(documentId) =>
                              void openDocument(documentId)
                            }
                          />
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {view === "list" && sortedCalls.length > 0 ? (
                    <div className="trace-call-list">
                      <div className="trace-call-list-header" aria-hidden="true">
                        <span>顺序</span>
                        <span>服务 / 工具</span>
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
                            <small>{call.server_name}</small>
                            <code>{call.tool_name}</code>
                          </span>
                          <TraceStatus status={call.status} />
                          <span>{call.duration_ms == null ? "—" : `${call.duration_ms} ms`}</span>
                          <span>{formattedTime(call.started_at)}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}

                  {view === "tree" ? (
                    <div className="trace-tree-canvas">
                      {!trace.project_id ? (
                        <div className="trace-main-empty">
                          <h3>这个历史任务没有可用的项目标识</h3>
                          <p>仍可在链路图中查看文档读取产物。</p>
                        </div>
                      ) : null}
                      {trace.project_id && treeError ? (
                        <div className="trace-main-empty">
                          <h3>当前项目文档树不可用</h3>
                          <p>{treeError}</p>
                        </div>
                      ) : null}
                      {trace.project_id && !tree && !treeError ? (
                        <p className="trace-panel-message">正在读取项目文档树…</p>
                      ) : null}
                      {tree ? (
                        <div className="tree-content">
                          <ul className="document-tree">
                            <DocumentTree
                              node={tree}
                              selectedId={documentDetail?.id ?? null}
                              callNumbersByDocumentId={documentCallNumbers}
                              onSelect={(node) => void openDocument(node.id)}
                            />
                          </ul>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </section>

                <TraceCallDetail
                  call={selectedCall}
                  onClose={() => setSelectedCallId(null)}
                />
              </div>
            </>
          ) : null}
        </main>
      </div>

      {documentLoading || documentDetail ? (
        <TraceDocumentDrawer
          detail={documentDetail}
          loading={documentLoading}
          onClose={closeDocument}
        />
      ) : null}
    </section>
  );
}
