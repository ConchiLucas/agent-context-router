"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { getTableRelationMcpPreview } from "@/lib/api";
import type {
  TableRelationMcpPreview,
  TableRelationTableIdentity,
} from "@/lib/types";

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

export function TableRelationMcpModal({
  workspaceId,
  table,
  preview,
  returnFocusTo,
  onClose,
}: {
  workspaceId: string;
  table: TableRelationTableIdentity;
  preview: TableRelationMcpPreview;
  returnFocusTo: HTMLElement | null;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const busyRef = useRef(false);
  const onCloseRef = useRef(onClose);
  const previewCacheRef = useRef<Partial<Record<"default" | "full", TableRelationMcpPreview>>>(
    { default: preview },
  );
  const [mode, setMode] = useState<"default" | "full">("default");
  const [currentPreview, setCurrentPreview] = useState(preview);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const formatted = useMemo(
    () => JSON.stringify(currentPreview, null, 2),
    [currentPreview],
  );

  useEffect(() => {
    busyRef.current = busy;
    onCloseRef.current = onClose;
  }, [busy, onClose]);

  useEffect(() => {
    const panel = panelRef.current;
    const rootOverflow = document.documentElement.style.overflow;
    const bodyOverflow = document.body.style.overflow;
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    panel?.querySelector<HTMLElement>("[data-autofocus]")?.focus();

    function keepFocusInside(event: KeyboardEvent) {
      if (event.key === "Escape" && !busyRef.current) {
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(
          "button:not(:disabled), [href], [tabindex]:not([tabindex='-1'])",
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", keepFocusInside);
    return () => {
      window.removeEventListener("keydown", keepFocusInside);
      document.documentElement.style.overflow = rootOverflow;
      document.body.style.overflow = bodyOverflow;
      returnFocusTo?.focus();
    };
  }, [returnFocusTo]);

  async function changeMode(nextMode: "default" | "full") {
    if (nextMode === mode || busy) return;
    const cached = previewCacheRef.current[nextMode];
    if (cached) {
      setCurrentPreview(cached);
      setMode(nextMode);
      setError(null);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const nextPreview = await getTableRelationMcpPreview(
        workspaceId,
        {
          databaseKey: table.database_key,
          schemaName: table.schema_name,
          tableName: table.table_name,
        },
        { mode: nextMode },
      );
      previewCacheRef.current[nextMode] = nextPreview;
      setCurrentPreview(nextPreview);
      setMode(nextMode);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "MCP 返回读取失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleCopy() {
    try {
      await copyToClipboard(formatted);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1600);
    } catch {
      setCopyState("error");
      window.setTimeout(() => setCopyState("idle"), 1600);
    }
  }

  return (
    <div className="relation-evidence-modal" role="presentation">
      <section
        ref={panelRef}
        className="relation-evidence-panel table-relation-mcp-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`${table.table_name} 的 MCP 返回`}
      >
        <header className="relation-evidence-header">
          <div className="relation-evidence-title">
            <p className="table-relation-row-identity">
              <code className="table-relation-row-id">{table.table_name}</code>
            </p>
            <p className="relation-evidence-context">
              {table.database_key}.{table.schema_name} · {currentPreview.result.environment.toUpperCase()} · read_table_relations
            </p>
          </div>
          <div className="table-relation-mcp-actions">
            <button
              type="button"
              className="secondary-button"
              disabled={busy}
              onClick={() => void handleCopy()}
            >
              {copyState === "copied"
                ? "已复制"
                : copyState === "error"
                  ? "复制失败"
                  : "复制 JSON"}
            </button>
            <button
              type="button"
              className="close-button"
              aria-label="关闭 MCP 返回"
              disabled={busy}
              onClick={onClose}
            >
              ×
            </button>
          </div>
        </header>

        <div className="relation-evidence-body">
          <div className="table-relation-mcp-mode-row">
            <div
              className="table-relation-mcp-modes"
              role="tablist"
              aria-label="MCP 返回范围"
            >
              <button
                type="button"
                role="tab"
                data-autofocus
                aria-selected={mode === "default"}
                data-active={mode === "default"}
                disabled={busy}
                onClick={() => void changeMode("default")}
              >
                默认返回
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "full"}
                data-active={mode === "full"}
                disabled={busy}
                onClick={() => void changeMode("full")}
              >
                完整返回
              </button>
            </div>
            <span aria-live="polite">{busy ? "正在读取…" : ""}</span>
          </div>
          <p className="relation-evidence-group-note">
            这是 agent 调用 MCP 工具{" "}
            <code>read_table_relations</code> 时收到的结构化内容。{" "}
            <code>arguments.task_id</code> 需来自{" "}
            <code>prepare_task_context</code>。未传 <code>environment</code> 时继承任务环境；
            {mode === "default" ? (
              <>当前是默认调用，只返回关系，不展开证据。</>
            ) : (
              <>
                当前显式请求全部 <code>sections</code> 和 <code>evidence=all</code>，用于人工调试。
              </>
            )}
          </p>
          {error ? <p className="table-relation-error" role="alert">{error}</p> : null}
          <pre
            className="relation-evidence-snippet table-relation-mcp-json"
            aria-busy={busy}
          >
            <code>{formatted}</code>
          </pre>
        </div>
      </section>
    </div>
  );
}
