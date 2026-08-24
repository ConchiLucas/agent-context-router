"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getAiDataQueryHistory,
  getLatestAiDataQuery,
  getWorkspaceEnvironments,
  listTableRelationTables,
  listWorkspaces,
  searchRelationRecords,
} from "@/lib/api";
import { sortTableSummaries } from "@/lib/table-relations";
import type {
  AiDataQueryRecord,
  RelationRecordCard,
  RelationRecordSearchResult,
  TableRelationTableSummary,
  WorkspaceEnvironmentOption,
  WorkspaceSummary,
} from "@/lib/types";

function tableValue(table: TableRelationTableSummary): string {
  return `${table.database_key}\u0000${table.schema_name}\u0000${table.table_name}`;
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function sourceLabel(source: string): string {
  return { codex: "Codex", antigravity: "Antigravity", agent: "本机 Agent" }[source] ?? source;
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function cardinalityLabel(value: RelationRecordCard["cardinality"]): string {
  return {
    one_to_one: "1 : 1",
    one_to_many: "1 : N",
    many_to_one: "N : 1",
    unknown: "未确认",
  }[value];
}

function CompactPager({
  card,
  busy,
  onPage,
}: {
  card: RelationRecordCard;
  busy: boolean;
  onPage: (page: number) => void;
}) {
  const { page, total_pages: totalPages } = card.page;
  if ((card.kind === "related" && card.cardinality === "one_to_one") || totalPages <= 1) {
    return null;
  }
  return (
    <nav className="relation-record-pager" aria-label={`${card.target.table_name} 分页`}>
      <button type="button" aria-label="首页" disabled={busy || page <= 1} onClick={() => onPage(1)}>┃◀</button>
      <button type="button" aria-label="上一页" disabled={busy || page <= 1} onClick={() => onPage(page - 1)}>◀</button>
      <span aria-label={`第 ${page} 页，共 ${totalPages} 页`}>{page} / {totalPages}</span>
      <button type="button" aria-label="下一页" disabled={busy || page >= totalPages} onClick={() => onPage(page + 1)}>▶</button>
      <button type="button" aria-label="末页" disabled={busy || page >= totalPages} onClick={() => onPage(totalPages)}>▶┃</button>
    </nav>
  );
}

export function DataVisualizationWorkbench() {
  const composing = useRef(false);
  const historyButtonRef = useRef<HTMLButtonElement>(null);
  const historyCloseButtonRef = useRef<HTMLButtonElement>(null);
  const workspacesRef = useRef<WorkspaceSummary[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [environments, setEnvironments] = useState<WorkspaceEnvironmentOption[]>([]);
  const [environment, setEnvironment] = useState("local");
  const [tables, setTables] = useState<TableRelationTableSummary[]>([]);
  const [databaseKey, setDatabaseKey] = useState("");
  const [selectedTable, setSelectedTable] = useState("");
  const [keyword, setKeyword] = useState("");
  const [activeRecord, setActiveRecord] = useState<AiDataQueryRecord | null>(null);
  const [history, setHistory] = useState<AiDataQueryRecord[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [result, setResult] = useState<RelationRecordSearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [pagingEdge, setPagingEdge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const closeHistory = useCallback(() => {
    setHistoryOpen(false);
    window.requestAnimationFrame(() => historyButtonRef.current?.focus());
  }, []);

  const loadContext = useCallback(async (
    targetWorkspaceId: string,
    record: AiDataQueryRecord | null,
  ) => {
    if (!targetWorkspaceId) {
      setWorkspaceId("");
      setEnvironments([]);
      setTables([]);
      return;
    }
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const [environmentPayload, tablePayload] = await Promise.all([
        getWorkspaceEnvironments(targetWorkspaceId),
        listTableRelationTables(targetWorkspaceId, { onlyRelated: true }),
      ]);
      const orderedTables = sortTableSummaries(tablePayload.tables);
      const desiredEnvironment = record?.environment;
      const nextEnvironment = environmentPayload.environments.some(
        (item) => item.key === desiredEnvironment,
      )
        ? desiredEnvironment!
        : environmentPayload.default_environment || environmentPayload.environments[0]?.key || "local";
      const desiredTable = record
        ? orderedTables.find((item) => (
          item.database_key === record.database_key
          && item.schema_name === record.schema_name
          && item.table_name === record.table_name
        ))
        : null;
      const nextTable = desiredTable ?? orderedTables[0] ?? null;
      setWorkspaceId(targetWorkspaceId);
      setEnvironments(environmentPayload.environments);
      setEnvironment(nextEnvironment);
      setTables(orderedTables);
      setDatabaseKey(nextTable?.database_key ?? "");
      setSelectedTable(nextTable ? tableValue(nextTable) : "");
      setKeyword(record?.keyword ?? "");
      setActiveRecord(record);
      setResult(null);
      if (record && !desiredTable) {
        setNotice("这条历史记录对应的表已不在当前关联清单中，已切换到第一个可用表。请重新确认条件。");
      } else if (record && nextEnvironment !== desiredEnvironment) {
        setNotice("这条记录对应的环境已不存在，已回退到工作空间默认环境。请重新确认条件。");
      }
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "查询条件加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const applyRecord = useCallback(async (
    record: AiDataQueryRecord,
    knownWorkspaces = workspacesRef.current,
  ) => {
    if (!knownWorkspaces.some((item) => item.id === record.workspace_id)) {
      setError("这条记录对应的工作空间当前不可见或已被删除");
      return;
    }
    await loadContext(record.workspace_id, record);
  }, [loadContext]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listWorkspaces(), getLatestAiDataQuery(), getAiDataQueryHistory(20)])
      .then(async ([workspaceItems, latestPayload, historyPayload]) => {
        if (cancelled) return;
        workspacesRef.current = workspaceItems;
        setWorkspaces(workspaceItems);
        setHistory(historyPayload.items);
        if (latestPayload.record) {
          await applyRecord(latestPayload.record, workspaceItems);
        } else if (workspaceItems[0]) {
          await loadContext(workspaceItems[0].id, null);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "数据可视化初始化失败");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [applyRecord, loadContext]);

  useEffect(() => {
    if (!historyOpen) return;
    historyCloseButtonRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeHistory();
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [closeHistory, historyOpen]);

  const databaseKeys = useMemo(
    () => Array.from(new Set(tables.map((table) => table.database_key)).values()).sort(),
    [tables],
  );
  const visibleTables = useMemo(
    () => tables.filter((table) => !databaseKey || table.database_key === databaseKey),
    [databaseKey, tables],
  );
  const selected = useMemo(
    () => tables.find((table) => tableValue(table) === selectedTable) ?? null,
    [selectedTable, tables],
  );

  const changeDatabase = (nextDatabaseKey: string) => {
    setDatabaseKey(nextDatabaseKey);
    const nextTable = tables.find((table) => table.database_key === nextDatabaseKey) ?? null;
    setSelectedTable(nextTable ? tableValue(nextTable) : "");
    setResult(null);
  };

  const loadLatest = async () => {
    setLoading(true);
    setError(null);
    try {
      const [latestPayload, historyPayload] = await Promise.all([
        getLatestAiDataQuery(),
        getAiDataQueryHistory(20),
      ]);
      setHistory(historyPayload.items);
      if (latestPayload.record) await applyRecord(latestPayload.record);
      else setNotice("还没有 Codex 或 Antigravity 保存的查询条件。");
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "最新查询条件读取失败");
    } finally {
      setLoading(false);
    }
  };

  const runSearch = async () => {
    if (!workspaceId || !selected || !keyword.trim()) return;
    setSearching(true);
    setError(null);
    try {
      setResult(await searchRelationRecords(workspaceId, {
        environment,
        table: {
          database_key: selected.database_key,
          schema_name: selected.schema_name,
          table_name: selected.table_name,
        },
        keyword: keyword.trim(),
      }));
    } catch (cause: unknown) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "关联数据查询失败");
    } finally {
      setSearching(false);
    }
  };

  const changePage = async (card: RelationRecordCard, page: number) => {
    if (!result || !selected || page === card.page.page) return;
    setPagingEdge(card.edge_id);
    setError(null);
    try {
      const next = await searchRelationRecords(workspaceId, {
        environment,
        table: result.table,
        keyword: result.keyword,
        edgeId: card.edge_id,
        sourceKeys: result.source_keys,
        page,
      });
      const replacement = next.cards[0];
      if (replacement) {
        setResult((current) => current ? {
          ...current,
          cards: current.cards.map((item) => item.edge_id === card.edge_id ? replacement : item),
        } : current);
      }
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "分页读取失败");
    } finally {
      setPagingEdge(null);
    }
  };

  return (
    <section className="data-visualization-page" aria-labelledby="data-visualization-title">
      <header className="data-visualization-heading">
        <div>
          <p className="section-eyebrow">AI VISUALIZATION / DATA</p>
          <h1 id="data-visualization-title">数据可视化</h1>
          <p>加载本机 AI 工具保存的查询条件，确认后查询一层关联数据。</p>
        </div>
        <div className="data-visualization-heading-actions">
          <button type="button" className="secondary-button" onClick={() => void loadLatest()} disabled={loading}>加载最新</button>
          <button ref={historyButtonRef} type="button" className="secondary-button" onClick={() => setHistoryOpen(true)}>历史记录</button>
        </div>
      </header>

      {activeRecord ? (
        <article className="data-visualization-source" aria-label="AI 查询描述">
          <div><span>{sourceLabel(activeRecord.source)}</span><time dateTime={activeRecord.created_at}>{formatTime(activeRecord.created_at)}</time></div>
          <p>{activeRecord.description || "AI 工具未提供原始文字描述。"}</p>
        </article>
      ) : (
        <div className="data-visualization-empty-source">
          <strong>还没有 AI 查询记录</strong>
          <span>请让 Codex 或 Antigravity 调用查询条件写入接口，然后点击“加载最新”。</span>
        </div>
      )}

      <form className="relation-record-toolbar data-visualization-toolbar" onSubmit={(event) => { event.preventDefault(); if (!composing.current) void runSearch(); }}>
        <label><span>工作空间</span><select value={workspaceId} onChange={(event) => void loadContext(event.target.value, null)}>{workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label><span>环境</span><select value={environment} disabled={environments.length <= 1} onChange={(event) => { setEnvironment(event.target.value); setResult(null); }}>{environments.map((item) => <option key={item.key} value={item.key}>{item.display_name}</option>)}</select></label>
        <label><span>库名</span><select aria-label="库名" value={databaseKey} onChange={(event) => changeDatabase(event.target.value)}>{databaseKeys.map((key) => <option key={key} value={key}>{key}</option>)}</select></label>
        <label className="relation-record-table-picker"><span>表名</span><select aria-label="表名" value={selectedTable} onChange={(event) => { setSelectedTable(event.target.value); setResult(null); }}>{visibleTables.map((table) => <option key={tableValue(table)} value={tableValue(table)}>{table.table_name}</option>)}</select></label>
        <label className="relation-record-keyword"><span>关键词</span><input value={keyword} placeholder="等待 AI 填充或手动输入关键词" autoComplete="off" onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onChange={(event) => { setKeyword(event.target.value); setResult(null); }} /></label>
        <button className="primary-button" type="submit" disabled={loading || searching || !selected || !keyword.trim()}>{searching ? "查询中…" : "查询"}</button>
      </form>

      {error ? <p className="relation-record-error" role="alert">{error}</p> : null}
      {notice ? <p className="data-visualization-notice" role="status">{notice}</p> : null}
      {loading ? <p className="relation-record-state" aria-live="polite">正在读取查询条件…</p> : null}
      {!loading && tables.length === 0 ? <div className="relation-record-empty"><h2>这个工作空间没有可查询的表关联</h2><p>请先发布表关联快照。</p></div> : null}
      {result ? (
        <div className="relation-record-results">
          <p className="relation-record-summary">扫描字段：{result.scanned_columns.length ? result.scanned_columns.join("、") : "无"} · 命中 {result.cards.filter((card) => card.kind === "related").length} 张关联表</p>
          {result.cards.length === 0 ? <div className="relation-record-empty"><h2>没有匹配的关联记录</h2><p>关键词未命中这张表的任何关联字段。</p></div> : null}
          {result.cards.map((card) => (
            <article className="relation-record-card" key={card.edge_id}>
              <header><div><h2>{card.target.table_name}</h2><p>{card.kind === "source" ? `${card.target.database_key}.${card.target.schema_name} · 命中字段：${card.matched_columns.join("、") || "无"}` : `${card.target.database_key}.${card.target.schema_name} · ${card.source_column} → ${card.target_column}`}</p></div><div className="relation-record-card-meta"><span>{card.kind === "source" ? "当前表" : cardinalityLabel(card.cardinality)}</span><span>{card.page.total_rows} 条</span></div></header>
              {card.warning ? <p className="relation-record-warning">{card.warning}</p> : null}
              <div className="relation-record-grid" tabIndex={0} aria-label={`${card.target.table_name} 数据表格`}>
                <table><thead><tr>{card.columns.map((column) => <th key={column.name} title={column.comment || "暂无字段注释"} tabIndex={0}><strong>{column.name}</strong></th>)}</tr></thead><tbody>{card.rows.map((row, rowIndex) => <tr key={`${card.edge_id}-${card.page.page}-${rowIndex}`}>{row.map((cell, index) => <td key={card.columns[index]?.name ?? index} title={displayValue(cell)}>{displayValue(cell)}</td>)}</tr>)}</tbody></table>
              </div>
              <footer><span>{card.kind === "source" ? `当前表命中 ${card.page.total_rows} 条` : `${card.matched_key_count} 个关联键命中`}</span><CompactPager card={card} busy={pagingEdge === card.edge_id} onPage={(page) => void changePage(card, page)} /></footer>
            </article>
          ))}
        </div>
      ) : !loading && tables.length > 0 ? <div className="relation-record-empty"><h2>确认查询条件后点击查询</h2><p>页面不会自动执行 AI 保存的条件。</p></div> : null}

      {historyOpen ? (
        <div className="data-visualization-history-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeHistory(); }}>
          <aside className="data-visualization-history" role="dialog" aria-modal="true" aria-labelledby="data-visualization-history-title">
            <header><div><p className="section-eyebrow">RECENT QUERIES</p><h2 id="data-visualization-history-title">历史记录</h2></div><button ref={historyCloseButtonRef} type="button" className="close-button" aria-label="关闭历史记录" onClick={closeHistory}>×</button></header>
            {history.length ? <div className="data-visualization-history-list">{history.map((record) => <button key={record.id} type="button" data-active={activeRecord?.id === record.id} onClick={() => { closeHistory(); void applyRecord(record); }}><span><strong>{record.description || record.keyword}</strong><time dateTime={record.created_at}>{formatTime(record.created_at)}</time></span><small>{sourceLabel(record.source)} · {record.workspace_name} · {record.environment}</small><code>{record.database_key}.{record.schema_name}.{record.table_name} · {record.keyword}</code></button>)}</div> : <div className="relation-record-empty"><h3>暂无历史记录</h3><p>AI 工具保存的条件会显示在这里。</p></div>}
          </aside>
        </div>
      ) : null}
    </section>
  );
}
