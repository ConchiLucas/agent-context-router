"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getAiInterfaceRequest,
  getAiInterfaceRequests,
  listWorkspaces,
} from "@/lib/api";
import type {
  AiInterfaceRequestDetail,
  AiInterfaceRequestListItem,
  WorkspaceSummary,
} from "@/lib/types";

type StatusFilter = "all" | "success" | "failed";

interface EvidenceRow {
  location: string;
  parameter: string;
  source: string;
  confidence: string;
}

function sourceLabel(source: string): string {
  return {
    codex: "Codex",
    antigravity: "Antigravity",
    agent: "本机 Agent",
    manual: "手动测试",
  }[source.toLowerCase()] ?? source;
}

function formatTime(value: string): string {
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

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function jsonText(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2) ?? "";
}

function evidenceRows(evidence: Record<string, unknown>): EvidenceRow[] {
  const rows: EvidenceRow[] = [];
  for (const [location, rawFields] of Object.entries(evidence)) {
    if (!rawFields || typeof rawFields !== "object" || Array.isArray(rawFields)) continue;
    for (const [parameter, rawEvidence] of Object.entries(rawFields)) {
      const item = rawEvidence as Record<string, unknown>;
      rows.push({
        location,
        parameter,
        source: typeof item.source === "string" ? item.source : "unknown",
        confidence: typeof item.confidence === "string" ? item.confidence : "-",
      });
    }
  }
  return rows;
}

function evidenceSourceLabel(source: string): string {
  return {
    caller: "用户 / AI",
    successful_history: "成功历史",
    value_mapping: "数据库映射",
    schema_default: "接口默认值",
    schema_example: "接口示例",
    safe_pagination_default: "安全分页",
  }[source] ?? source;
}

export function InterfaceVisualizationWorkbench() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [items, setItems] = useState<AiInterfaceRequestListItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<AiInterfaceRequestDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");

  useEffect(() => {
    listWorkspaces().then(setWorkspaces).catch(() => setWorkspaces([]));
  }, []);

  const success = statusFilter === "all" ? undefined : statusFilter === "success";

  const loadRequests = useCallback(
    async (append = false) => {
      append ? setLoadingMore(true) : setLoading(true);
      setError("");
      try {
        const result = await getAiInterfaceRequests({
          workspaceId: workspaceId || undefined,
          success,
          limit: 50,
          offset: append ? items.length : 0,
        });
        const nextItems = append ? [...items, ...result.items] : result.items;
        setItems(nextItems);
        setHasMore(result.has_more);
        setSelectedId((current) =>
          nextItems.some((item) => item.id === current) ? current : (nextItems[0]?.id ?? ""),
        );
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "接口请求记录加载失败");
        if (!append) {
          setItems([]);
          setSelectedId("");
        }
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [items, success, workspaceId],
  );

  useEffect(() => {
    void loadRequests(false);
    // The list is intentionally refreshed only when its server-side filters change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, statusFilter]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailError("");
      return;
    }
    let active = true;
    setDetailLoading(true);
    setDetailError("");
    getAiInterfaceRequest(selectedId)
      .then((result) => {
        if (active) setDetail(result);
      })
      .catch((reason) => {
        if (active) {
          setDetail(null);
          setDetailError(reason instanceof Error ? reason.message : "请求详情加载失败");
        }
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedId]);

  const evidence = useMemo(
    () => evidenceRows(detail?.parameter_evidence ?? {}),
    [detail],
  );

  return (
    <section className="interface-visualization-page" aria-labelledby="interface-visualization-title">
      <header className="interface-visualization-heading">
        <div>
          <p className="eyebrow">AI VISUALIZATION / INTERFACE</p>
          <h1 id="interface-visualization-title">接口可视化</h1>
          <p>展示 Codex、Antigravity 和手动测试实际执行的接口请求，最新请求优先。</p>
        </div>
        <button type="button" className="secondary-button" disabled={loading} onClick={() => void loadRequests(false)}>
          {loading ? "正在刷新…" : "刷新列表"}
        </button>
      </header>

      <div className="interface-visualization-toolbar" aria-label="请求列表筛选">
        <label>
          <span>工作空间</span>
          <select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}>
            <option value="">全部工作空间</option>
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
            ))}
          </select>
        </label>
        <label>
          <span>执行结果</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
            <option value="all">全部结果</option>
            <option value="success">成功</option>
            <option value="failed">失败</option>
          </select>
        </label>
        <p aria-live="polite">{loading ? "正在读取请求记录" : `当前显示 ${items.length} 条请求`}</p>
      </div>

      {error ? <p className="error-banner" role="alert">{error}</p> : null}

      <div className="interface-visualization-layout">
        <aside className="interface-request-list" aria-label="接口请求列表">
          {loading && items.length === 0 ? <p className="interface-visualization-state">正在加载最近请求…</p> : null}
          {!loading && !error && items.length === 0 ? (
            <div className="interface-visualization-state">
              <strong>暂无接口请求</strong>
              <span>Codex、Antigravity 或手动测试完成请求后会显示在这里。</span>
            </div>
          ) : null}
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="interface-request-list-item"
              data-active={item.id === selectedId}
              aria-pressed={item.id === selectedId}
              onClick={() => setSelectedId(item.id)}
            >
              <span className="interface-request-list-line">
                <span className={`http-method http-method--${item.method.toLowerCase()}`}>{item.method}</span>
                <strong title={item.interface_name}>{item.interface_name}</strong>
                <span className={item.success ? "request-status request-status--success" : "request-status request-status--failed"}>
                  {item.success ? "成功" : "失败"}
                </span>
              </span>
              <code title={item.path}>{item.path}</code>
              <span className="interface-request-list-description" title={item.description}>{item.description}</span>
              <span className="interface-request-list-meta">
                <span>{sourceLabel(item.source)} · {item.workspace_name}</span>
                <time dateTime={item.created_at}>{formatTime(item.created_at)}</time>
              </span>
            </button>
          ))}
          {hasMore ? (
            <button type="button" className="secondary-button interface-request-load-more" disabled={loadingMore} onClick={() => void loadRequests(true)}>
              {loadingMore ? "正在加载…" : "加载更多"}
            </button>
          ) : null}
        </aside>

        <article className="interface-request-detail" aria-live="polite">
          {detailLoading ? <p className="interface-visualization-state">正在加载请求详情…</p> : null}
          {detailError ? <p className="error-banner" role="alert">{detailError}</p> : null}
          {!detailLoading && !detailError && !detail ? (
            <div className="interface-visualization-state">
              <strong>选择一条请求查看详情</strong>
              <span>这里会显示最终参数、参数来源和接口响应。</span>
            </div>
          ) : null}
          {!detailLoading && detail ? (
            <>
              <header className="interface-request-detail-heading">
                <div>
                  <span className={`http-method http-method--${detail.method.toLowerCase()}`}>{detail.method}</span>
                  <h2>{detail.interface_name}</h2>
                  <code>{detail.path}</code>
                </div>
                <span className={detail.success ? "request-status request-status--success" : "request-status request-status--failed"}>
                  {detail.success ? `请求成功 · ${detail.status_code ?? "-"}` : `请求失败 · ${detail.status_code ?? "-"}`}
                </span>
              </header>

              <section className="interface-request-intent">
                <div><span>{sourceLabel(detail.source)}</span><time dateTime={detail.created_at}>{formatTime(detail.created_at)}</time></div>
                <p>{detail.description}</p>
              </section>

              <dl className="interface-request-metadata">
                <div><dt>工作空间</dt><dd>{detail.workspace_name}</dd></div>
                <div><dt>环境</dt><dd>{detail.environment}</dd></div>
                <div><dt>接口服务</dt><dd>{detail.service_name}</dd></div>
                <div><dt>转发地址</dt><dd>{detail.address_name ?? "-"}</dd></div>
                <div><dt>登录账号</dt><dd>{detail.login_account ?? "-"}{detail.role_name ? ` · ${detail.role_name}` : ""}</dd></div>
                <div><dt>响应</dt><dd>{detail.duration_ms} ms · {formatBytes(detail.response_bytes)}</dd></div>
              </dl>

              {evidence.length ? (
                <section className="interface-request-evidence">
                  <h3>参数来源</h3>
                  <div className="interface-request-evidence-table" role="table" aria-label="请求参数来源">
                    {evidence.map((item) => (
                      <div role="row" key={`${item.location}:${item.parameter}`}>
                        <code role="cell">{item.location}.{item.parameter}</code>
                        <span role="cell">{evidenceSourceLabel(item.source)}</span>
                        <small role="cell">{item.confidence}</small>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}

              {detail.response_truncated ? (
                <p className="interface-visualization-notice">响应超过记录上限，当前展示的是截断内容。</p>
              ) : null}

              <div className="interface-request-payloads">
                <section>
                  <h3>请求参数</h3>
                  <pre tabIndex={0}>{jsonText(detail.request)}</pre>
                </section>
                <section>
                  <h3>响应结果</h3>
                  <pre tabIndex={0}>{jsonText(detail.response)}</pre>
                </section>
              </div>
            </>
          ) : null}
        </article>
      </div>
    </section>
  );
}

