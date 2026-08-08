"use client";

import { useEffect, useMemo, useState } from "react";

import { listSystemGuides, updateSystemGuideContent } from "@/lib/api";
import type {
  JsonValue,
  SystemGuideDetail,
  SystemGuideDocument,
} from "@/lib/types";

type EditorMode = "tree" | "source";

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

export function SystemGuideManager() {
  const [guides, setGuides] = useState<SystemGuideDetail[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("{}");
  const [mode, setMode] = useState<EditorMode>("source");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const parsed = useMemo(() => parseDocument(source), [source]);
  const selected = guides.find((item) => item.id === selectedId) ?? null;
  const filteredGuides = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("zh-CN");
    if (!normalized) return guides;
    return guides.filter((item) =>
      [item.title, item.summary, item.guide_key].some((value) =>
        value.toLocaleLowerCase("zh-CN").includes(normalized),
      ),
    );
  }, [guides, query]);

  useEffect(() => {
    let cancelled = false;
    void listSystemGuides()
      .then((items) => {
        if (cancelled) return;
        setGuides(items);
        const first = items[0];
        if (first) {
          setSelectedId(first.id);
          setSource(stringifyDocument(first.document));
        }
      })
      .catch((loadError: unknown) => {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "系统文档读取失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
    <section className="system-guide-page" aria-labelledby="system-guide-title">
      <header className="system-guide-header">
        <div>
          <span className="section-eyebrow">Context Router</span>
          <h1 id="system-guide-title">系统文档</h1>
          <p>选择已有文档，编辑 JSON 内容并保存。</p>
        </div>
        <div className="system-guide-header-actions">
          <span className={parsed.error ? "json-validity is-error" : "json-validity"}>
            {parsed.error ? "JSON 有误" : "JSON 有效"}
          </span>
        </div>
      </header>

      <div className="system-guide-workspace">
        <aside className="system-guide-list" aria-label="系统文档菜单">
          <label className="system-guide-search">
            <span className="sr-only">搜索系统文档</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索标题、摘要或 key"
              inputMode="search"
            />
          </label>
          <div className="system-guide-list-items">
            {loading ? <p className="system-guide-list-message">正在读取系统文档…</p> : null}
            {!loading && filteredGuides.length === 0 ? (
              <p className="system-guide-list-message">没有匹配的系统文档</p>
            ) : null}
            {filteredGuides.map((guide) => (
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
              <strong>{selected?.title ?? "请选择系统文档"}</strong>
              {selected ? <code>{selected.guide_key}</code> : null}
              <span>{new TextEncoder().encode(source).length} bytes</span>
            </div>
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

          <div className="system-guide-editor-body">
            {mode === "source" ? (
              <textarea
                aria-label="系统文档 JSON 源码"
                value={source}
                onChange={(event) => setSource(event.target.value)}
                disabled={!selected}
                spellCheck={false}
              />
            ) : parsed.document ? (
              <pre aria-label="系统文档 JSON 树形预览">
                {stringifyDocument(parsed.document)}
              </pre>
            ) : (
              <div className="system-guide-json-error" role="alert">
                <strong>JSON 无法预览</strong>
                <p>{parsed.error}</p>
              </div>
            )}
          </div>

          {error ? <p className="error-banner" role="alert">{error}</p> : null}
          {notice ? <p className="success-banner" role="status">{notice}</p> : null}

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
        </div>
      </div>
    </section>
  );
}
