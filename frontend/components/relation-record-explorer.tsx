"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getWorkspaceEnvironments,
  listTableRelationTables,
  listWorkspaces,
  searchRelationRecords,
} from "@/lib/api";
import type {
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
  const [draftPage, setDraftPage] = useState(String(page));
  useEffect(() => setDraftPage(String(page)), [page]);
  const commitPage = () => {
    const next = Number(draftPage);
    if (Number.isInteger(next) && next >= 1 && next <= totalPages) {
      onPage(next);
      return;
    }
    setDraftPage(String(page));
  };
  if (card.cardinality === "one_to_one" || totalPages <= 1) return null;
  return (
    <nav className="relation-record-pager" aria-label={`${card.target.table_name} 分页`}>
      <button type="button" aria-label="首页" disabled={busy || page <= 1} onClick={() => onPage(1)}>┃◀</button>
      <button type="button" aria-label="上一页" disabled={busy || page <= 1} onClick={() => onPage(page - 1)}>◀</button>
      <label>
        <span className="sr-only">当前页</span>
        <input
          type="number"
          min={1}
          max={totalPages}
          value={draftPage}
          disabled={busy}
          onChange={(event) => setDraftPage(event.target.value)}
          onBlur={commitPage}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commitPage();
            }
          }}
        />
      </label>
      <span aria-label={`共 ${totalPages} 页`}>/ {totalPages}</span>
      <button type="button" aria-label="下一页" disabled={busy || page >= totalPages} onClick={() => onPage(page + 1)}>▶</button>
      <button type="button" aria-label="末页" disabled={busy || page >= totalPages} onClick={() => onPage(totalPages)}>▶┃</button>
    </nav>
  );
}

export function RelationRecordExplorer() {
  const composing = useRef(false);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [environments, setEnvironments] = useState<WorkspaceEnvironmentOption[]>([]);
  const [environment, setEnvironment] = useState("local");
  const [tables, setTables] = useState<TableRelationTableSummary[]>([]);
  const [databaseKey, setDatabaseKey] = useState("");
  const [selectedTable, setSelectedTable] = useState("");
  const [keyword, setKeyword] = useState("");
  const [result, setResult] = useState<RelationRecordSearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [pagingEdge, setPagingEdge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listWorkspaces()
      .then((items) => {
        if (cancelled) return;
        setWorkspaces(items);
        setWorkspaceId(items[0]?.id ?? "");
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "工作空间读取失败");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!workspaceId) return;
    let cancelled = false;
    setLoading(true);
    setResult(null);
    getWorkspaceEnvironments(workspaceId)
      .then((payload) => {
        if (cancelled) return;
        setEnvironments(payload.environments);
        setEnvironment(payload.default_environment || payload.environments[0]?.key || "local");
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "环境读取失败");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [workspaceId]);

  useEffect(() => {
    if (!workspaceId || !environment) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setResult(null);
    listTableRelationTables(workspaceId, { environment, onlyRelated: true })
      .then((payload) => {
        if (cancelled) return;
        setTables(payload.tables);
        setDatabaseKey(payload.tables[0]?.database_key ?? "");
        setSelectedTable(payload.tables[0] ? tableValue(payload.tables[0]) : "");
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setTables([]);
          setError(cause instanceof Error ? cause.message : "表关联清单读取失败");
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [workspaceId, environment]);

  const databaseKeys = useMemo(
    () => Array.from(new Set(tables.map((table) => table.database_key))).sort(),
    [tables],
  );
  const visibleTables = useMemo(() => {
    return tables.filter(
      (table) => !databaseKey || table.database_key === databaseKey,
    );
  }, [tables, databaseKey]);

  useEffect(() => {
    if (!visibleTables.some((table) => tableValue(table) === selectedTable)) {
      setSelectedTable(visibleTables[0] ? tableValue(visibleTables[0]) : "");
    }
  }, [selectedTable, visibleTables]);

  const selected = useMemo(
    () => tables.find((table) => tableValue(table) === selectedTable) ?? null,
    [selectedTable, tables],
  );

  const runSearch = useCallback(async () => {
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
  }, [environment, keyword, selected, workspaceId]);

  const changePage = useCallback(async (card: RelationRecordCard, page: number) => {
    if (!workspaceId || !selected || !result || page === card.page.page) return;
    setPagingEdge(card.edge_id);
    setError(null);
    try {
      const next = await searchRelationRecords(workspaceId, {
        environment,
        table: result.table,
        keyword: result.keyword,
        edgeId: card.edge_id,
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
  }, [environment, result, selected, workspaceId]);

  return (
    <section className="relation-record-explorer" aria-labelledby="relation-record-title">
      <header className="relation-record-header">
        <div>
          <h1 id="relation-record-title">关联数据</h1>
          <p>关键词只扫描所选表参与关系的字段，并展示一层直接关联记录。</p>
        </div>
        <div className="relation-record-context">
          <label><span>工作空间</span><select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}>{workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label><span>环境</span><select value={environment} disabled={environments.length <= 1} onChange={(event) => setEnvironment(event.target.value)}>{environments.map((item) => <option key={item.key} value={item.key}>{item.display_name}</option>)}</select></label>
        </div>
      </header>

      <form className="relation-record-toolbar" onSubmit={(event) => { event.preventDefault(); if (!composing.current) void runSearch(); }}>
        <label><span>库名</span><select aria-label="库名" value={databaseKey} onChange={(event) => setDatabaseKey(event.target.value)}>{databaseKeys.map((key) => <option key={key} value={key}>{key}</option>)}</select></label>
        <label className="relation-record-table-picker"><span>表名</span><select aria-label="表名" value={selectedTable} onChange={(event) => setSelectedTable(event.target.value)}>{visibleTables.map((table) => <option key={tableValue(table)} value={tableValue(table)}>{table.table_name}</option>)}</select></label>
        <label className="relation-record-keyword"><span>关键词</span><input value={keyword} placeholder="输入关联字段中的值" onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onChange={(event) => setKeyword(event.target.value)} /></label>
        <button className="primary-button" type="submit" disabled={searching || !selected || !keyword.trim()}>{searching ? "查询中…" : "查询"}</button>
      </form>

      {error ? <p className="relation-record-error" role="alert">{error}</p> : null}
      {loading ? <p className="relation-record-state">正在读取关联配置…</p> : null}
      {!loading && tables.length === 0 ? <div className="relation-record-empty"><h2>当前环境没有可查询的表关联</h2><p>请先为这个环境发布表关联数据并配置对应数据库。</p></div> : null}
      {result ? (
        <div className="relation-record-results">
          <p className="relation-record-summary">扫描字段：{result.scanned_columns.length ? result.scanned_columns.join("、") : "无"} · 命中 {result.cards.length} 张关联表</p>
          {result.cards.length === 0 ? <div className="relation-record-empty"><h2>没有匹配的关联记录</h2><p>关键词未命中这张表的任何关联字段。</p></div> : null}
          {result.cards.map((card) => (
            <article className="relation-record-card" key={card.edge_id}>
              <header><div><h2>{card.target.table_name}</h2><p>{card.target.database_key}.{card.target.schema_name} · {card.source_column} → {card.target_column}</p></div><div className="relation-record-card-meta"><span>{cardinalityLabel(card.cardinality)}</span><span>{card.page.total_rows} 条</span></div></header>
              {card.warning ? <p className="relation-record-warning">{card.warning}</p> : null}
              <div className={`relation-record-grid${card.cardinality === "one_to_one" ? " relation-record-grid--scroll" : ""}`} tabIndex={0} aria-label={`${card.target.table_name} 数据表格`}>
                <table>
                  <thead><tr>{card.columns.map((column) => <th key={column.name} title={column.comment || "暂无字段注释"} tabIndex={0}><strong>{column.name}</strong><span>{column.type || "未知类型"}{column.relation_key ? " · 关联键" : ""}</span></th>)}</tr></thead>
                  <tbody>{card.rows.map((row, rowIndex) => <tr key={`${card.edge_id}-${card.page.page}-${rowIndex}`}>{row.map((cell, columnIndex) => <td key={card.columns[columnIndex]?.name ?? columnIndex} title={displayValue(cell)}>{displayValue(cell)}</td>)}</tr>)}</tbody>
                </table>
              </div>
              <footer><span>{card.matched_key_count} 个关联键命中</span><CompactPager card={card} busy={pagingEdge === card.edge_id} onPage={(page) => void changePage(card, page)} /></footer>
            </article>
          ))}
        </div>
      ) : !loading && tables.length > 0 ? <div className="relation-record-empty"><h2>选择表并输入关键词</h2><p>系统只会扫描表关联中已经登记的字段。</p></div> : null}
    </section>
  );
}
