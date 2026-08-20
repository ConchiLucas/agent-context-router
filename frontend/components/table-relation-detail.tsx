"use client";

import { TableRelationEdgeRow } from "@/components/table-relation-edge-row";
import { disagreementCount } from "@/lib/table-relations";
import type { TableRelationTableDetail, TableRelationView } from "@/lib/types";

export function TableRelationDetail({
  detail,
  openingEdgeId,
  writesBusy,
  updatesBusy,
  mcpBusy,
  onOpenRelation,
  onOpenWrites,
  onOpenUpdates,
  onOpenMcp,
}: {
  detail: TableRelationTableDetail;
  openingEdgeId: string | null;
  writesBusy: boolean;
  updatesBusy: boolean;
  mcpBusy: boolean;
  onOpenRelation: (relation: TableRelationView) => void;
  onOpenWrites: () => void;
  onOpenUpdates: () => void;
  onOpenMcp: () => void;
}) {
  const table = detail.table;
  const diverging = disagreementCount(detail.relations);

  return (
    <div className="table-relation-detail">
      <header className="table-relation-detail-header">
        <div>
          <h2>{table.table_name}</h2>
          <p>
            {table.database_key}.{table.schema_name}
          </p>
        </div>
        <div className="table-relation-detail-actions">
          <button
            type="button"
            className="secondary-button"
            aria-label={`查看 ${table.table_name} 的 MCP 返回`}
            disabled={mcpBusy}
            onClick={onOpenMcp}
          >
            {mcpBusy ? "读取中" : "MCP 返回"}
          </button>
          <button
            type="button"
            className="secondary-button"
            aria-label={`查看 ${table.table_name} 的插入入口`}
            disabled={writesBusy}
            onClick={onOpenWrites}
          >
            {writesBusy ? "读取中" : "插入入口"}
          </button>
          <button
            type="button"
            className="secondary-button"
            aria-label={`查看 ${table.table_name} 的更新入口`}
            disabled={updatesBusy}
            onClick={onOpenUpdates}
          >
            {updatesBusy ? "读取中" : "更新入口"}
          </button>
        </div>
      </header>

      {detail.relations.length === 0 ? (
        <p className="table-relation-empty-note">这张表没有可展示的关联。</p>
      ) : (
        <ul className="table-relation-rows">
          {detail.relations.map((relation) => (
            <TableRelationEdgeRow
              key={relation.edge_id}
              relation={relation}
              busy={openingEdgeId === relation.edge_id}
              onOpen={onOpenRelation}
            />
          ))}
        </ul>
      )}

      {/* Both notes are counts of things deliberately not on screen, so the page
          never looks complete while holding something back. */}
      {diverging > 0 || detail.hidden_count > 0 ? (
        <p className="table-relation-detail-footnote">
          {diverging > 0 ? `两个维度结论不一致 ${diverging} 条` : ""}
          {diverging > 0 && detail.hidden_count > 0 ? " · " : ""}
          {detail.hidden_count > 0 ? `未写入过的列 ${detail.hidden_count} 条未展示` : ""}
        </p>
      ) : null}
    </div>
  );
}
