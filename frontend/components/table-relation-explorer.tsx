"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { TableRelationDetail } from "@/components/table-relation-detail";
import { TableRelationEvidenceModal } from "@/components/table-relation-evidence-modal";
import { TableRelationMcpModal } from "@/components/table-relation-mcp-modal";
import { TableRelationTableList } from "@/components/table-relation-table-list";
import { TableRelationWriteModal } from "@/components/table-relation-write-modal";
import {
  getTableRelationDetail,
  getTableRelationEvidence,
  getTableRelationMcpPreview,
  getTableRelationStatus,
  getTableRelationUpdates,
  getTableRelationWrites,
  listTableRelationTables,
  listWorkspaces,
} from "@/lib/api";
import {
  filterTableSummaries,
  listDatabaseKeys,
  sortTableSummaries,
  tableKey,
  unrelatedTableCount,
} from "@/lib/table-relations";
import type {
  TableRelationDetail as TableRelationEvidence,
  TableRelationMcpPreview,
  TableRelationStatus,
  TableRelationTableDetail,
  TableRelationTableSummary,
  TableRelationTableUpdates,
  TableRelationTableWrites,
  TableRelationView,
  WorkspaceSummary,
} from "@/lib/types";

export function TableRelationExplorer() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [status, setStatus] = useState<TableRelationStatus | null>(null);
  const [tables, setTables] = useState<TableRelationTableSummary[]>([]);
  const [detail, setDetail] = useState<TableRelationTableDetail | null>(null);
  const [evidence, setEvidence] = useState<TableRelationEvidence | null>(null);
  const [writes, setWrites] = useState<TableRelationTableWrites | null>(null);
  const [updates, setUpdates] = useState<TableRelationTableUpdates | null>(null);
  const [mcpPreview, setMcpPreview] = useState<TableRelationMcpPreview | null>(null);
  const [openingEdgeId, setOpeningEdgeId] = useState<string | null>(null);
  const [writesBusy, setWritesBusy] = useState(false);
  const [updatesBusy, setUpdatesBusy] = useState(false);
  const [mcpBusy, setMcpBusy] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [writesError, setWritesError] = useState<string | null>(null);
  const [updatesError, setUpdatesError] = useState<string | null>(null);
  const [mcpError, setMcpError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [databaseKey, setDatabaseKey] = useState("");
  const [onlyRelated, setOnlyRelated] = useState(true);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listWorkspaces()
      .then((items) => {
        if (cancelled) return;
        setWorkspaces(items);
        setWorkspaceId((current) => current ?? items[0]?.id ?? null);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "工作空间读取失败");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadWorkspace = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    setDetail(null);
    setWrites(null);
    setUpdates(null);
    setMcpPreview(null);
    setSelectedKey(null);
    setDatabaseKey("");
    try {
      const [nextStatus, nextTables] = await Promise.all([
        getTableRelationStatus(id),
        listTableRelationTables(id, { onlyRelated: false }),
      ]);
      setStatus(nextStatus);
      setTables(nextTables.tables);
    } catch (cause: unknown) {
      setStatus(null);
      setTables([]);
      setError(cause instanceof Error ? cause.message : "表关联数据读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!workspaceId) return;
    void loadWorkspace(workspaceId);
  }, [workspaceId, loadWorkspace]);

  const sorted = useMemo(() => sortTableSummaries(tables), [tables]);
  const databaseKeys = useMemo(
    () => (status?.database_keys?.length ? status.database_keys : listDatabaseKeys(sorted)),
    [status, sorted],
  );

  useEffect(() => {
    if (databaseKey && !databaseKeys.includes(databaseKey)) {
      setDatabaseKey("");
    }
  }, [databaseKey, databaseKeys]);

  const scoped = useMemo(
    () => filterTableSummaries(sorted, { search: "", onlyRelated: false, databaseKey }),
    [sorted, databaseKey],
  );
  const visible = useMemo(
    () => filterTableSummaries(sorted, { search, onlyRelated, databaseKey }),
    [sorted, search, onlyRelated, databaseKey],
  );
  const unrelatedCount = useMemo(() => unrelatedTableCount(scoped), [scoped]);

  const openRelation = useCallback(
    async (relation: TableRelationView) => {
      // Read from the table the row belongs to, not from the relation's own ends:
      // the two cardinalities are stated from an end, and the panel has to agree
      // with the row that was clicked.
      if (!workspaceId || !detail) return;
      setOpeningEdgeId(relation.edge_id);
      setEvidenceError(null);
      try {
        setEvidence(
          await getTableRelationEvidence(workspaceId, {
            edgeId: relation.edge_id,
            databaseKey: detail.table.database_key,
            schemaName: detail.table.schema_name,
            tableName: detail.table.table_name,
          }),
        );
      } catch (cause: unknown) {
        setEvidence(null);
        setEvidenceError(cause instanceof Error ? cause.message : "关系依据读取失败");
      } finally {
        setOpeningEdgeId(null);
      }
    },
    [workspaceId, detail],
  );

  const openWrites = useCallback(async () => {
    if (!workspaceId || !detail) return;
    setWritesBusy(true);
    setWritesError(null);
    setUpdates(null);
    setMcpPreview(null);
    try {
      setWrites(
        await getTableRelationWrites(workspaceId, {
          databaseKey: detail.table.database_key,
          schemaName: detail.table.schema_name,
          tableName: detail.table.table_name,
        }),
      );
    } catch (cause: unknown) {
      setWrites(null);
      setWritesError(cause instanceof Error ? cause.message : "插入入口读取失败");
    } finally {
      setWritesBusy(false);
    }
  }, [workspaceId, detail]);

  const openUpdates = useCallback(async () => {
    if (!workspaceId || !detail) return;
    setUpdatesBusy(true);
    setUpdatesError(null);
    setWrites(null);
    setMcpPreview(null);
    try {
      setUpdates(
        await getTableRelationUpdates(workspaceId, {
          databaseKey: detail.table.database_key,
          schemaName: detail.table.schema_name,
          tableName: detail.table.table_name,
        }),
      );
    } catch (cause: unknown) {
      setUpdates(null);
      setUpdatesError(cause instanceof Error ? cause.message : "更新入口读取失败");
    } finally {
      setUpdatesBusy(false);
    }
  }, [workspaceId, detail]);

  const openMcp = useCallback(async () => {
    if (!workspaceId || !detail) return;
    setMcpBusy(true);
    setMcpError(null);
    setWrites(null);
    setUpdates(null);
    try {
      setMcpPreview(
        await getTableRelationMcpPreview(workspaceId, {
          databaseKey: detail.table.database_key,
          schemaName: detail.table.schema_name,
          tableName: detail.table.table_name,
        }),
      );
    } catch (cause: unknown) {
      setMcpPreview(null);
      setMcpError(cause instanceof Error ? cause.message : "MCP 返回读取失败");
    } finally {
      setMcpBusy(false);
    }
  }, [workspaceId, detail]);

  const selectTable = useCallback(
    async (table: TableRelationTableSummary) => {
      if (!workspaceId) return;
      setSelectedKey(tableKey(table));
      setDetailLoading(true);
      setDetailError(null);
      setEvidenceError(null);
      setWritesError(null);
      setUpdatesError(null);
      setMcpError(null);
      setWrites(null);
      setUpdates(null);
      setMcpPreview(null);
      try {
        setDetail(
          await getTableRelationDetail(workspaceId, {
            databaseKey: table.database_key,
            schemaName: table.schema_name,
            tableName: table.table_name,
          }),
        );
      } catch (cause: unknown) {
        setDetail(null);
        setDetailError(cause instanceof Error ? cause.message : "表关联详情读取失败");
      } finally {
        setDetailLoading(false);
      }
    },
    [workspaceId],
  );

  return (
    <section className="table-relation-explorer" aria-labelledby="table-relation-title">
      <header className="table-relation-header">
        <div>
          <h1 id="table-relation-title">表关联</h1>
        </div>
        <label className="table-relation-workspace">
          <span>工作空间</span>
          <select
            value={workspaceId ?? ""}
            onChange={(event) => setWorkspaceId(event.target.value)}
          >
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </select>
        </label>
      </header>

      {error ? <p className="table-relation-error">{error}</p> : null}

      {loading ? (
        <p className="table-relation-empty-note">正在读取表关联数据…</p>
      ) : !status?.generation ? (
        <div className="table-relation-empty-card">
          <h2>这个工作空间还没有表关联数据</h2>
          <p>
            关联数据的自动生成还没有实现，这一版的示例数据由种子脚本写入。在仓库目录下执行下面的命令
            就能看到页面效果。
          </p>
          <pre>
            <code>{status?.rebuild_command ?? ""}</code>
          </pre>
        </div>
      ) : (
        <div className="table-relation-layout">
          <aside className="table-relation-panel" aria-label="表清单">
            <TableRelationTableList
              tables={visible}
              selectedKey={selectedKey}
              search={search}
              databaseKey={databaseKey}
              databaseKeys={databaseKeys}
              onlyRelated={onlyRelated}
              hiddenCount={unrelatedCount}
              onSearchChange={setSearch}
              onDatabaseKeyChange={setDatabaseKey}
              onOnlyRelatedChange={setOnlyRelated}
              onSelect={(table) => void selectTable(table)}
            />
          </aside>
          <div className="table-relation-panel table-relation-panel--detail">
            {detailError ? <p className="table-relation-error">{detailError}</p> : null}
            {evidenceError ? <p className="table-relation-error">{evidenceError}</p> : null}
            {writesError ? <p className="table-relation-error">{writesError}</p> : null}
            {updatesError ? <p className="table-relation-error">{updatesError}</p> : null}
            {mcpError ? <p className="table-relation-error">{mcpError}</p> : null}
            {detailLoading ? (
              <p className="table-relation-empty-note">正在读取这张表的关联…</p>
            ) : detail ? (
              <TableRelationDetail
                detail={detail}
                openingEdgeId={openingEdgeId}
                writesBusy={writesBusy}
                updatesBusy={updatesBusy}
                mcpBusy={mcpBusy}
                onOpenRelation={(relation) => void openRelation(relation)}
                onOpenWrites={() => void openWrites()}
                onOpenUpdates={() => void openUpdates()}
                onOpenMcp={() => void openMcp()}
              />
            ) : !detailError ? (
              <p className="table-relation-empty-note">
                从左边选一张表，这里会列出它的全部关联。
              </p>
            ) : null}
          </div>
        </div>
      )}

      {evidence ? (
        <TableRelationEvidenceModal
          detail={evidence}
          onClose={() => setEvidence(null)}
        />
      ) : null}
      {writes ? (
        <TableRelationWriteModal
          table={writes.table}
          sites={writes.writes}
          mode="insert"
          onClose={() => setWrites(null)}
        />
      ) : null}
      {updates ? (
        <TableRelationWriteModal
          table={updates.table}
          sites={updates.updates}
          mode="update"
          onClose={() => setUpdates(null)}
        />
      ) : null}
      {mcpPreview && detail ? (
        <TableRelationMcpModal
          table={detail.table}
          preview={mcpPreview}
          onClose={() => setMcpPreview(null)}
        />
      ) : null}
    </section>
  );
}
