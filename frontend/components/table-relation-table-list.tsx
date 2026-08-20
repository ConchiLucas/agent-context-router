"use client";

import { tableKey } from "@/lib/table-relations";
import type { TableRelationTableSummary } from "@/lib/types";

export function TableRelationTableList({
  tables,
  selectedKey,
  search,
  databaseKey,
  databaseKeys,
  onlyRelated,
  hiddenCount,
  onSearchChange,
  onDatabaseKeyChange,
  onOnlyRelatedChange,
  onSelect,
}: {
  tables: TableRelationTableSummary[];
  selectedKey: string | null;
  search: string;
  databaseKey: string;
  databaseKeys: string[];
  onlyRelated: boolean;
  hiddenCount: number;
  onSearchChange: (value: string) => void;
  onDatabaseKeyChange: (value: string) => void;
  onOnlyRelatedChange: (value: boolean) => void;
  onSelect: (table: TableRelationTableSummary) => void;
}) {
  return (
    <div className="table-relation-list">
      <div className="table-relation-list-controls">
        <label className="table-relation-search">
          <span>库名</span>
          <select
            value={databaseKey}
            onChange={(event) => onDatabaseKeyChange(event.target.value)}
          >
            <option value="">全部库</option>
            {databaseKeys.map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </select>
        </label>
        <label className="table-relation-search">
          <span>搜索表名</span>
          <input
            type="search"
            value={search}
            placeholder="表名"
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </label>
        <label className="table-relation-toggle">
          <input
            type="checkbox"
            checked={onlyRelated}
            onChange={(event) => onOnlyRelatedChange(event.target.checked)}
          />
          <span>只看有关联的表</span>
        </label>
        <p className="table-relation-list-summary">
          共 {tables.length} 张表
          {onlyRelated && hiddenCount > 0 ? `，已隐藏 ${hiddenCount} 张没有关联的表` : ""}
        </p>
      </div>
      {tables.length === 0 ? (
        <p className="table-relation-empty-note">没有符合条件的表。</p>
      ) : (
        <ul className="table-relation-list-items">
          {tables.map((table) => {
            const key = tableKey(table);
            return (
              <li key={key}>
                <button
                  type="button"
                  data-active={key === selectedKey}
                  aria-current={key === selectedKey ? "true" : undefined}
                  onClick={() => onSelect(table)}
                >
                  <span className="table-relation-list-name">{table.table_name}</span>
                  <span className="table-relation-list-meta">{table.database_key}</span>
                  <span className="table-relation-list-counts">
                    {table.relation_count === 0 ? (
                      <span>没有关联</span>
                    ) : (
                      <span>{table.relation_count}</span>
                    )}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
