"use client";

import { useEffect, useMemo, useState } from "react";

import {
  listMcpTools,
  listSystemGuides,
  updateSystemGuideContent,
} from "@/lib/api";
import type {
  JsonValue,
  McpToolsListResult,
  SystemGuideDetail,
  SystemGuideDocument,
} from "@/lib/types";

type EditorMode = "tree" | "source";
const MCP_TOOL_ID_PREFIX = "mcp-tool:";
const MCP_TOOL_DESCRIPTIONS_ZH: Readonly<Record<string, string>> = {
  prepare_task_context:
    "根据当前工作目录识别 Workspace，创建 task_id，并返回精简文档树和可用能力。",
  read_task_context:
    "按需读取当前任务的数据库别名或环境配置，不在 prepare 阶段默认返回。",
  search_context_documents:
    "在当前 Workspace 的项目文档中搜索相关内容，返回匹配文档和章节定位，不返回正文。",
  read_context_document:
    "按文档 ID 读取完整 Markdown、指定章节或系统文档，一次可以批量读取多个目标。",
  search_database_objects:
    "在当前任务已授权的数据库中搜索 Schema、表、视图、字段或索引。",
  execute_database_query:
    "使用 read_task_context 返回的数据库别名执行一条受限制的只读 SQL。",
  apply_workspace_changes:
    "根据 Workspace 相对变更路径定位受影响项目，并选择快速或完整更新。",
  start_workspace:
    "使用 Workspace 的统一启动配置，启动其中所有已登记的项目和服务。",
  get_workspace_operation:
    "查询 Workspace 启动或更新操作的状态、执行步骤和有界日志。",
};

function toolName(tool: Record<string, JsonValue>): string | null {
  return typeof tool.name === "string" ? tool.name : null;
}

function toolSelectionId(name: string): string {
  return `${MCP_TOOL_ID_PREFIX}${name}`;
}

function displayToolDescription(tool: Record<string, JsonValue>): string {
  const name = toolName(tool);
  if (name && MCP_TOOL_DESCRIPTIONS_ZH[name]) {
    return MCP_TOOL_DESCRIPTIONS_ZH[name];
  }
  return typeof tool.description === "string"
    ? tool.description
    : "当前 MCP 工具定义";
}

function displayTool(tool: Record<string, JsonValue>): Record<string, JsonValue> {
  return {
    ...tool,
    description: displayToolDescription(tool),
  };
}

function formatBytes(source: string): string {
  const bytes = new TextEncoder().encode(source).length;
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function stringifyDocument(document: SystemGuideDocument): string {
  return JSON.stringify(document, null, 2);
}

function parseDocument(source: string): {
  document: SystemGuideDocument | null;
  error: string | null;
} {
  try {
    const value = JSON.parse(source) as JsonValue;
    if (value === null || Array.isArray(value) || typeof value !== "object") {
      return { document: null, error: "文档根节点必须是 JSON 对象" };
    }
    return { document: value as SystemGuideDocument, error: null };
  } catch (error) {
    return {
      document: null,
      error: error instanceof Error ? error.message : "JSON 格式不正确",
    };
  }
}

function renderJsonPrimitive(value: JsonValue) {
  if (value === null) {
    return <span className="json-token json-token--null">null</span>;
  }
  if (typeof value === "boolean") {
    return <span className="json-token json-token--boolean">{String(value)}</span>;
  }
  if (typeof value === "number") {
    return <span className="json-token json-token--number">{value}</span>;
  }
  if (typeof value === "string") {
    const visible = value.length > 120 ? `${value.slice(0, 120)}...` : value;
    return <span className="json-token json-token--string">{`"${visible}"`}</span>;
  }
  return null;
}

function JsonTreeNode({
  keyName,
  value,
  depth = 0,
}: {
  keyName?: string;
  value: JsonValue;
  depth?: number;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const isContainer = value !== null && typeof value === "object";
  const isArray = Array.isArray(value);

  if (!isContainer) {
    return (
      <div className="json-tree-row" style={{ paddingLeft: depth * 20 + 4 }}>
        {keyName !== undefined ? (
          <>
            <span className="json-token json-token--key">{`"${keyName}"`}</span>
            <span className="json-token json-token--punctuation">:</span>
          </>
        ) : null}
        {renderJsonPrimitive(value)}
      </div>
    );
  }

  const entries = Array.isArray(value) ? value.map((item, index) => [String(index), item] as const) : Object.entries(value);
  const bracketOpen = isArray ? "[" : "{";
  const bracketClose = isArray ? "]" : "}";

  return (
    <div className="json-tree-node" style={{ paddingLeft: depth * 20 }}>
      <button
        type="button"
        className="json-tree-row json-tree-row--toggle"
        onClick={() => setCollapsed((current) => !current)}
        aria-expanded={!collapsed}
      >
        {keyName !== undefined ? (
          <>
            <span className="json-token json-token--key">{`"${keyName}"`}</span>
            <span className="json-token json-token--punctuation">:</span>
          </>
        ) : null}
        <span className="json-token json-token--bracket">{bracketOpen}</span>
        {collapsed ? (
          <>
            <span className="json-tree-summary">
              {entries.length} {isArray ? "items" : "keys"}
            </span>
            <span className="json-token json-token--bracket">{bracketClose}</span>
          </>
        ) : null}
      </button>
      {!collapsed ? (
        <>
          {entries.map(([entryKey, entryValue], index) => (
            <JsonTreeNode
              key={`${entryKey}-${index}`}
              keyName={isArray ? undefined : entryKey}
              value={entryValue}
              depth={depth + 1}
            />
          ))}
          <div className="json-tree-row json-tree-row--close" style={{ paddingLeft: 24 }}>
            <span className="json-token json-token--bracket">{bracketClose}</span>
          </div>
        </>
      ) : null}
    </div>
  );
}

export function SystemGuideManager() {
  const [guides, setGuides] = useState<SystemGuideDetail[]>([]);
  const [mcpTools, setMcpTools] = useState<McpToolsListResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("{}");
  const [mode, setMode] = useState<EditorMode>("source");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const parsed = useMemo(() => parseDocument(source), [source]);
  const selectedTool =
    mcpTools?.tools.find((tool) => {
      const name = toolName(tool);
      return name !== null && toolSelectionId(name) === selectedId;
    }) ?? null;
  const selectedToolName = selectedTool ? toolName(selectedTool) : null;
  const showingTool = selectedTool !== null;
  const selected = guides.find((item) => item.id === selectedId) ?? null;
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("zh-CN");
    const filteredGuides = normalized
      ? guides.filter((item) =>
          [item.title, item.summary, item.guide_key].some((value) =>
            value.toLocaleLowerCase("zh-CN").includes(normalized),
          ),
        )
      : guides;
    const filteredTools = (mcpTools?.tools ?? []).filter((tool) => {
      if (!normalized) return true;
      const values = [
        toolName(tool) ?? "",
        displayToolDescription(tool),
        typeof tool.description === "string" ? tool.description : "",
        "tools/list",
      ];
      return values.some((value) =>
        value.toLocaleLowerCase("zh-CN").includes(normalized),
      );
    });
    return {
      guides: filteredGuides,
      tools: filteredTools,
    };
  }, [guides, mcpTools, query]);

  useEffect(() => {
    let cancelled = false;
    void Promise.allSettled([listMcpTools(), listSystemGuides()]).then(
      ([toolsResult, guidesResult]) => {
        if (cancelled) return;
        const errors: string[] = [];
        let hasSelectedTool = false;
        if (toolsResult.status === "fulfilled") {
          setMcpTools(toolsResult.value);
          const firstTool = toolsResult.value.tools[0];
          const firstToolName = firstTool ? toolName(firstTool) : null;
          if (firstTool && firstToolName) {
            hasSelectedTool = true;
            setSelectedId(toolSelectionId(firstToolName));
            setSource(JSON.stringify(displayTool(firstTool), null, 2));
          }
        } else {
          errors.push(
            toolsResult.reason instanceof Error
              ? toolsResult.reason.message
              : "MCP 工具清单读取失败",
          );
        }
        if (guidesResult.status === "fulfilled") {
          setGuides(guidesResult.value);
          const first = guidesResult.value[0];
          if (!hasSelectedTool && first) {
            setSelectedId(first.id);
            setSource(stringifyDocument(first.document));
          }
        } else {
          errors.push(
            guidesResult.reason instanceof Error
              ? guidesResult.reason.message
              : "系统文档读取失败",
          );
        }
        setError(errors.length > 0 ? errors.join("；") : null);
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  function selectTool(tool: Record<string, JsonValue>) {
    const name = toolName(tool);
    if (!name) return;
    setSelectedId(toolSelectionId(name));
    setSource(JSON.stringify(displayTool(tool), null, 2));
    setNotice(null);
    setError(null);
  }

  function selectGuide(guide: SystemGuideDetail) {
    setSelectedId(guide.id);
    setSource(stringifyDocument(guide.document));
    setNotice(null);
    setError(null);
  }

  async function saveContent() {
    setNotice(null);
    setError(null);
    if (!selected || !parsed.document) {
      setError(parsed.error ?? "请选择要保存的系统文档");
      return;
    }
    setSaving(true);
    try {
      const saved = await updateSystemGuideContent(selected.id, parsed.document);
      setGuides((items) => items.map((item) => (item.id === saved.id ? saved : item)));
      setSource(stringifyDocument(saved.document));
      setNotice("系统文档内容已保存，下一次 prepare 将使用最新内容。");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "系统文档保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="system-guide-page" aria-label="系统文档">
      <div className="system-guide-workspace">
        <aside className="system-guide-list" aria-label="系统文档菜单">
          <label className="system-guide-search">
            <span className="sr-only">搜索工具或系统文档</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索工具、标题、摘要或 key"
              inputMode="search"
            />
          </label>
          <div className="system-guide-list-items">
            {loading ? <p className="system-guide-list-message">正在读取内容…</p> : null}
            {!loading && filtered.tools.length === 0 && filtered.guides.length === 0 ? (
              <p className="system-guide-list-message">没有匹配的内容</p>
            ) : null}
            {filtered.tools.map((tool) => {
              const name = toolName(tool);
              if (!name) return null;
              const description = displayToolDescription(tool);
              return (
                <button
                  type="button"
                  key={name}
                  data-active={toolSelectionId(name) === selectedId}
                  onClick={() => selectTool(tool)}
                >
                  <strong>{name}</strong>
                  <span>{description}</span>
                  <code>tools/list</code>
                </button>
              );
            })}
            {filtered.guides.map((guide) => (
              <button
                type="button"
                key={guide.id}
                data-active={guide.id === selectedId}
                onClick={() => selectGuide(guide)}
              >
                <strong>{guide.title}</strong>
                <span>{guide.summary}</span>
                <code>{guide.guide_key}</code>
              </button>
            ))}
          </div>
        </aside>

        <div className="system-guide-editor">
          <div className="system-guide-editor-toolbar">
            <div>
              <strong>{selectedToolName ?? selected?.title ?? "请选择内容"}</strong>
              {showingTool ? <code>tools/list</code> : null}
              {selected ? <code>{selected.guide_key}</code> : null}
              <span>{formatBytes(source)}</span>
            </div>
            <div className="system-guide-toolbar-actions">
              <span className={parsed.error ? "json-validity is-error" : "json-validity"}>
                {parsed.error
                  ? "Invalid"
                  : showingTool
                    ? "只读 · tools/list"
                    : "Valid JSON"}
              </span>
              <div className="system-guide-view-tabs" role="tablist" aria-label="JSON 查看方式">
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === "tree"}
                  data-active={mode === "tree"}
                  onClick={() => setMode("tree")}
                >
                  树形
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === "source"}
                  data-active={mode === "source"}
                  onClick={() => setMode("source")}
                >
                  源码
                </button>
              </div>
            </div>
          </div>

          <div className="system-guide-editor-body">
            {mode === "source" ? (
              <div className="system-guide-source-pane">
                <textarea
                  aria-label={showingTool ? "MCP tool JSON 源码" : "系统文档 JSON 源码"}
                  value={source}
                  onChange={(event) => {
                    if (!showingTool) setSource(event.target.value);
                  }}
                  readOnly={showingTool}
                  disabled={!showingTool && !selected}
                  spellCheck={false}
                />
                {parsed.error ? (
                  <div className="system-guide-inline-error" role="alert">
                    <span aria-hidden="true">!</span>
                    <p>{parsed.error}</p>
                  </div>
                ) : null}
              </div>
            ) : parsed.document ? (
              <div className="json-tree-view" aria-label="JSON 树形预览">
                <JsonTreeNode value={parsed.document} />
              </div>
            ) : (
              <div className="system-guide-json-error" role="alert">
                <strong>JSON 无法预览</strong>
                <p>{parsed.error}</p>
              </div>
            )}
          </div>

          {error ? <p className="error-banner" role="alert">{error}</p> : null}
          {notice ? <p className="success-banner" role="status">{notice}</p> : null}

          {showingTool ? (
            <footer className="system-guide-footer system-guide-footer--readonly">
              <p>页面使用中文介绍；AI 通过 MCP tools/list 获取的原始英文描述保持不变。</p>
            </footer>
          ) : (
            <footer className="system-guide-footer system-guide-footer--save-only">
              <button
                type="button"
                className="primary-button"
                onClick={() => void saveContent()}
                disabled={saving || !selected || Boolean(parsed.error)}
              >
                {saving ? "正在保存…" : "保存内容"}
              </button>
            </footer>
          )}
        </div>
      </div>
    </section>
  );
}
