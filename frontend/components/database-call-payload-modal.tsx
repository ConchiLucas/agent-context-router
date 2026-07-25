"use client";

import { useEffect, useMemo, useState } from "react";

import { getMcpDatabaseToolPayload } from "@/lib/api";
import {
  databasePayloadDisplay,
  databasePayloadUnavailableMessage,
} from "@/lib/database-call-payload";
import type { DatabasePayloadView } from "@/lib/database-call-payload";
import type {
  McpDatabaseToolPayload,
  McpTraceToolCall,
} from "@/lib/types";

interface DatabaseCallPayloadModalProps {
  taskId: number;
  call: McpTraceToolCall;
  onClose: () => void;
}

function formattedBytes(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formattedTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function databaseFromPayload(
  payload: McpDatabaseToolPayload | null,
): string | null {
  const database = payload?.request_payload?.database;
  return typeof database === "string" ? database : null;
}

async function copyToClipboard(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

export function DatabaseCallPayloadModal({
  taskId,
  call,
  onClose,
}: DatabaseCallPayloadModalProps) {
  const [payload, setPayload] = useState<McpDatabaseToolPayload | null>(null);
  const [activeView, setActiveView] =
    useState<DatabasePayloadView>("request");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">(
    "idle",
  );

  useEffect(() => {
    let active = true;
    setLoading(true);
    setPayload(null);
    setError(null);
    void getMcpDatabaseToolPayload(taskId, call.tool_call_id)
      .then((nextPayload) => {
        if (!active) return;
        setPayload(nextPayload);
      })
      .catch((requestError: Error) => {
        if (!active) return;
        setError(requestError.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [call.tool_call_id, taskId]);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  useEffect(() => {
    setCopyState("idle");
  }, [activeView]);

  const display = useMemo(
    () => (payload ? databasePayloadDisplay(payload, activeView) : null),
    [activeView, payload],
  );
  const truncated =
    activeView === "request"
      ? payload?.request_truncated
      : payload?.response_truncated;
  const byteCount =
    activeView === "request"
      ? payload?.request_bytes
      : payload?.response_bytes;
  const unavailableMessage = payload
    ? databasePayloadUnavailableMessage(payload)
    : "";
  const database = databaseFromPayload(payload);

  async function copyCurrentPayload() {
    if (!display?.clipboard) return;
    try {
      await copyToClipboard(display.clipboard);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  }

  return (
    <div className="database-payload-modal" role="presentation">
      <section
        className="database-payload-panel"
        role="dialog"
        aria-modal="true"
        aria-label="数据库 MCP 调用出入参详情"
      >
        <header className="database-payload-header">
          <div>
            <span className="file-chip">数据库 MCP 调用详情</span>
            <h2>{call.tool_name}</h2>
            <p>
              任务 #{taskId} · CALL #{call.sequence}
              {database ? ` · ${database}` : ""}
            </p>
          </div>
          <button
            type="button"
            className="close-button"
            aria-label="关闭数据库 MCP 调用详情"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="database-payload-notice">
          这里展示服务端按安全预算保存的数据库工具出入参，内容可能包含敏感业务数据。
        </div>

        <div className="database-payload-body">
          {loading ? (
            <div className="database-payload-state">
              <h3>正在读取出入参详情…</h3>
            </div>
          ) : null}

          {!loading && error ? (
            <div className="database-payload-state" data-status="error">
              <h3>详情加载失败</h3>
              <p>{error}</p>
            </div>
          ) : null}

          {!loading && !error && payload && !payload.available ? (
            <div className="database-payload-state">
              <h3>没有可展示的出入参详情</h3>
              <p>{unavailableMessage}</p>
              {payload.capture_error_code ? (
                <code>{payload.capture_error_code}</code>
              ) : null}
            </div>
          ) : null}

          {!loading && !error && payload?.available ? (
            <div className="database-payload-available">
              <div className="database-payload-toolbar">
              <div
                className="database-payload-tabs"
                role="tablist"
                aria-label="数据库调用出入参"
              >
                {([
                  ["request", "请求参数"],
                  ["response", "响应结果"],
                ] as const).map(([value, label]) => (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={activeView === value}
                    data-active={activeView === value}
                    onClick={() => setActiveView(value)}
                    key={value}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="database-payload-meta">
                <span>{formattedBytes(byteCount)}</span>
                <span>状态：{payload.status ?? "—"}</span>
                <span>采集：{formattedTime(payload.created_at)}</span>
                {payload.expires_at ? (
                  <span>到期：{formattedTime(payload.expires_at)}</span>
                ) : null}
              </div>
              <button
                type="button"
                className="secondary-button"
                disabled={!display?.clipboard}
                onClick={() => void copyCurrentPayload()}
              >
                {copyState === "copied"
                  ? "已复制"
                  : copyState === "error"
                    ? "复制失败"
                    : "复制当前内容"}
              </button>
              </div>

              {truncated ? (
                <div className="database-payload-truncated">
                  当前{activeView === "request" ? "请求" : "响应"}快照已按保存预算截断，页面仅展示实际留存内容。
                </div>
              ) : null}

              <div className="database-payload-content">
                {display?.sql ? (
                  <section className="database-payload-code">
                    <h3>SQL</h3>
                    <pre><code>{display.sql}</code></pre>
                  </section>
                ) : null}
                <section className="database-payload-code">
                  <h3>
                    {activeView === "request" ? "参数 JSON" : "响应 JSON"}
                  </h3>
                  {display?.json ? (
                    <pre><code>{display.json}</code></pre>
                  ) : (
                    <p>当前部分没有保存内容。</p>
                  )}
                </section>
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
