"use client";

import { useEffect, useMemo, useState } from "react";

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
  table,
  preview,
  onClose,
}: {
  table: TableRelationTableIdentity;
  preview: TableRelationMcpPreview;
  onClose: () => void;
}) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const formatted = useMemo(() => JSON.stringify(preview, null, 2), [preview]);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

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
              {table.database_key}.{table.schema_name} · read_table_relations
            </p>
          </div>
          <div className="table-relation-mcp-actions">
            <button
              type="button"
              className="secondary-button"
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
              onClick={onClose}
            >
              ×
            </button>
          </div>
        </header>

        <div className="relation-evidence-body">
          <p className="relation-evidence-group-note">
            这是 agent 调用 MCP 工具{" "}
            <code>read_table_relations</code> 时收到的结构化内容。{" "}
            <code>arguments.task_id</code> 需来自{" "}
            <code>prepare_task_context</code>；下方 <code>result</code>{" "}
            与真实 MCP 响应一致（不含 task_id 字段）。
          </p>
          <pre className="relation-evidence-snippet table-relation-mcp-json">
            <code>{formatted}</code>
          </pre>
        </div>
      </section>
    </div>
  );
}
