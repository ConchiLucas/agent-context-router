"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getTableRelationContext,
  getTableRelationDefaultDatabases,
  getProjectTableRelationSqlWhitelist,
  getTableRelationStatus,
  listAllTableRelationTables,
  listTableRelationWarnings,
  listWorkspaces,
  rebuildTableRelations,
  rebuildProjectTableRelations,
  replaceProjectTableRelationSqlWhitelist,
} from "@/lib/api";
import type {
  ObservedTableJoin,
  TableRelationBuildStatus,
  TableRelationContext,
  TableRelationDefaultDatabaseProject,
  TableRelationIdentity,
  TableRelationProjectBuildStatus,
  TableRelationSqlWhitelistConfiguration,
  TableRelationTableOption,
  TableRelationWarningList,
  WorkspaceSummary,
} from "@/lib/types";

const ALL_PROJECTS = "__all_projects__";

function identityKey(table: TableRelationIdentity): string {
  return [table.project_id, table.database_key, table.schema_name, table.table_name].join("\u0000");
}

function otherTable(join: ObservedTableJoin, root: TableRelationIdentity): TableRelationIdentity {
  return identityKey(join.table_a) === identityKey(root) ? join.table_b : join.table_a;
}

function statusLabel(status: TableRelationBuildStatus["status"]): string {
  if (status === "ready") return "索引就绪";
  if (status === "partial") return "部分索引可用";
  if (status === "building") return "正在扫描";
  if (status === "failed") return "构建失败";
  return "尚未构建";
}

function projectStatusLabel(status?: TableRelationProjectBuildStatus["status"]): string {
  if (status === "ready") return "就绪";
  if (status === "failed") return "失败";
  if (status === "building") return "扫描中";
  return "未构建";
}

export function TableRelationExplorer() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [status, setStatus] = useState<TableRelationBuildStatus | null>(null);
  const [projects, setProjects] = useState<TableRelationDefaultDatabaseProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [tables, setTables] = useState<TableRelationTableOption[]>([]);
  const [query, setQuery] = useState("");
  const [context, setContext] = useState<TableRelationContext | null>(null);
  const [selectedJoinId, setSelectedJoinId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [rebuildScope, setRebuildScope] = useState<"all" | "project" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showWarnings, setShowWarnings] = useState(false);
  const [warningCode, setWarningCode] = useState("");
  const [warningProjectId, setWarningProjectId] = useState("");
  const [warningDisposition, setWarningDisposition] = useState<"attention" | "expected">(
    "attention",
  );
  const [warningQuery, setWarningQuery] = useState("");
  const [warningReport, setWarningReport] = useState<TableRelationWarningList | null>(null);
  const [warningsLoading, setWarningsLoading] = useState(false);
  const [warningsError, setWarningsError] = useState<string | null>(null);
  const [showWhitelist, setShowWhitelist] = useState(false);
  const [whitelist, setWhitelist] = useState<TableRelationSqlWhitelistConfiguration | null>(null);
  const [whitelistDraft, setWhitelistDraft] = useState("");
  const [whitelistLoading, setWhitelistLoading] = useState(false);
  const [whitelistSaving, setWhitelistSaving] = useState(false);
  const [whitelistError, setWhitelistError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listWorkspaces()
      .then((items) => {
        if (!active) return;
        setWorkspaces(items);
        setWorkspaceId((current) => current || items[0]?.id || "");
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "工作空间加载失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!workspaceId) return;
    let active = true;
    setError(null);
    setContext(null);
    setSelectedJoinId(null);
    setShowWarnings(false);
    setWarningCode("");
    setWarningProjectId("");
    setWarningDisposition("attention");
    setWarningQuery("");
    setWarningReport(null);
    setShowWhitelist(false);
    setWhitelist(null);
    setWhitelistDraft("");
    setWhitelistError(null);
    Promise.all([
      getTableRelationStatus(workspaceId),
      getTableRelationDefaultDatabases(workspaceId),
    ])
      .then(async ([nextStatus, configuration]) => {
        const nextTables = ["ready", "partial"].includes(nextStatus.status)
          ? await listAllTableRelationTables(workspaceId)
          : null;
        if (!active) return;
        const nextProjects = configuration.projects.filter(
          (item) => item.selected_project_database_id,
        );
        setStatus(nextStatus);
        setProjects(nextProjects);
        setProjectId((current) =>
          nextProjects.some((item) => item.project_id === current)
            ? current
            : nextProjects[0]?.project_id ?? "",
        );
        setTables(nextTables?.tables ?? []);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "表关联读取失败");
      });
    return () => {
      active = false;
    };
  }, [workspaceId]);

  useEffect(() => {
    if (
      !workspaceId
      || !status
      || !["ready", "partial"].includes(status.status)
    ) return;
    let active = true;
    const timeout = window.setTimeout(() => {
      listAllTableRelationTables(workspaceId, query)
        .then((result) => {
          if (active) setTables(result.tables);
        })
        .catch((reason: unknown) => {
          if (active) {
            setError(reason instanceof Error ? reason.message : "表清单搜索失败");
          }
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [query, status, workspaceId]);

  useEffect(() => {
    if (!showWarnings || !workspaceId) return;
    let active = true;
    const timeout = window.setTimeout(() => {
      setWarningsLoading(true);
      setWarningsError(null);
      listTableRelationWarnings(workspaceId, {
        code: warningCode || undefined,
        projectId: warningProjectId || undefined,
        disposition: warningDisposition,
        query: warningQuery,
      })
        .then((result) => {
          if (active) setWarningReport(result);
        })
        .catch((reason: unknown) => {
          if (active) {
            setWarningsError(reason instanceof Error ? reason.message : "跳过提示读取失败");
          }
        })
        .finally(() => {
          if (active) setWarningsLoading(false);
        });
    }, 200);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [showWarnings, warningCode, warningDisposition, warningProjectId, warningQuery, workspaceId]);

  const filteredTables = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return tables;
    return tables.filter((item) =>
      `${item.table_name} ${item.schema_name} ${item.database_key} ${item.project_name}`
        .toLocaleLowerCase()
        .includes(normalized),
    );
  }, [query, tables]);

  const projectStatusById = useMemo(
    () => new Map((status?.projects ?? []).map((item) => [item.project_id, item])),
    [status?.projects],
  );

  const failedProjects = useMemo(
    () => (status?.projects ?? []).filter((item) => item.status === "failed"),
    [status?.projects],
  );

  const selectedJoin = context?.joins.find((item) => item.relation_id === selectedJoinId)
    ?? context?.joins[0]
    ?? null;

  async function rebuild(scope: "all" | "project") {
    if (!workspaceId || rebuildScope || (scope === "project" && !projectId)) return;
    setRebuildScope(scope);
    setError(null);
    setStatus((current) => current
      ? {
          ...current,
          status: "building",
          projects: current.projects.map((item) =>
            scope === "all" || item.project_id === projectId
              ? { ...item, status: "building", error_message: null }
              : item,
          ),
        }
      : current);
    try {
      if (scope === "project") {
        await rebuildProjectTableRelations(workspaceId, projectId);
      } else {
        await rebuildTableRelations(workspaceId);
      }
      const [nextStatus, nextTables] = await Promise.all([
        getTableRelationStatus(workspaceId),
        listAllTableRelationTables(workspaceId),
      ]);
      setStatus(nextStatus);
      setTables(nextTables.tables);
      setContext(null);
      setSelectedJoinId(null);
      setShowWarnings(false);
      setWarningCode("");
      setWarningProjectId("");
      setWarningDisposition("attention");
      setWarningQuery("");
      setWarningReport(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "表关联构建失败");
      try {
        setStatus(await getTableRelationStatus(workspaceId));
      } catch {
        // Preserve the original actionable error.
      }
    } finally {
      setRebuildScope(null);
    }
  }

  async function selectTable(table: TableRelationTableOption) {
    setError(null);
    try {
      const next = await getTableRelationContext(
        workspaceId,
        table.table_name,
        table.database_key,
        table.schema_name,
      );
      setContext(next);
      setSelectedJoinId(next.joins[0]?.relation_id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "表关联详情读取失败");
    }
  }

  async function focusRelated(table: TableRelationIdentity) {
    await selectTable({ ...table, relation_count: 0 });
  }

  async function openWhitelist() {
    if (!workspaceId || !projectId || projectId === ALL_PROJECTS) return;
    setShowWhitelist(true);
    setWhitelistLoading(true);
    setWhitelistError(null);
    try {
      const result = await getProjectTableRelationSqlWhitelist(workspaceId, projectId);
      setWhitelist(result);
      setWhitelistDraft(result.paths.join("\n"));
    } catch (reason) {
      setWhitelistError(reason instanceof Error ? reason.message : "SQL 白名单读取失败");
    } finally {
      setWhitelistLoading(false);
    }
  }

  function includeSuggestedPaths() {
    if (!whitelist) return;
    const paths = new Map<string, string>();
    for (const item of [...whitelistDraft.split("\n"), ...whitelist.suggested_paths]) {
      const normalized = item.trim();
      if (normalized) paths.set(normalized.toLocaleLowerCase(), normalized);
    }
    setWhitelistDraft([...paths.values()].sort((left, right) => left.localeCompare(right)).join("\n"));
  }

  async function saveWhitelist() {
    if (!workspaceId || !projectId || projectId === ALL_PROJECTS || whitelistSaving) return;
    setWhitelistSaving(true);
    setWhitelistError(null);
    const paths = whitelistDraft
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
    try {
      await replaceProjectTableRelationSqlWhitelist(workspaceId, projectId, paths);
      setShowWhitelist(false);
      setWhitelist(null);
      setWhitelistDraft("");
      await rebuild("project");
    } catch (reason) {
      setWhitelistError(reason instanceof Error ? reason.message : "SQL 白名单保存失败");
    } finally {
      setWhitelistSaving(false);
    }
  }

  return (
    <section className="table-relation-page" aria-labelledby="table-relation-title">
      <header className="section-heading table-relation-heading">
        <div>
          <span className="eyebrow">SQL OBSERVATION</span>
          <h1 id="table-relation-title">表关联</h1>
          <p>只展示 SQL 文件中实际出现且通过数据库元数据校验的字段等值关联。</p>
        </div>
        <div className="table-relation-actions">
          <label>
            <span>工作空间</span>
            <select
              value={workspaceId}
              disabled={rebuildScope !== null}
              onChange={(event) => setWorkspaceId(event.target.value)}
            >
              {workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>更新项目</span>
            <select
              value={projectId}
              disabled={rebuildScope !== null || projects.length === 0}
              onChange={(event) => setProjectId(event.target.value)}
            >
              <option value={ALL_PROJECTS}>全部项目</option>
              {projects.map((project) => (
                <option key={project.project_id} value={project.project_id}>
                  {project.project_name}（{projectStatusLabel(
                    projectStatusById.get(project.project_id)?.status,
                  )}）
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="secondary-button"
            onClick={() => void openWhitelist()}
            disabled={
              !workspaceId
              || !projectId
              || projectId === ALL_PROJECTS
              || rebuildScope !== null
            }
          >
            SQL 白名单
          </button>
          <button
            type="button"
            className="primary-button"
            onClick={() => rebuild(projectId === ALL_PROJECTS ? "all" : "project")}
            disabled={
              !workspaceId
              || !projectId
              || rebuildScope !== null
              || !status
              || status.eligible_project_count === 0
              || status.configured_project_count !== status.eligible_project_count
            }
          >
            {rebuildScope === "all"
              ? "全部项目更新中…"
              : rebuildScope === "project"
                ? "当前项目更新中…"
                : projectId === ALL_PROJECTS
                  ? "更新全部项目"
                  : "更新当前项目"}
          </button>
        </div>
      </header>

      <p className="table-relation-notice">
        关系是无方向的观察事实，不代表外键、上下游、主从关系或数据血缘。
      </p>
      {error ? <div className="error-banner" role="alert">{error}</div> : null}

      <div className="table-relation-status" aria-live="polite">
        <strong>{loading ? "正在加载" : status ? statusLabel(status.status) : "等待选择"}</strong>
        <span>{status?.sql_file_count ?? 0} 个 SQL 文件</span>
        <span>{status?.statement_count ?? 0} 条解析候选</span>
        <span>{status?.relation_count ?? 0} 组关联</span>
        {status ? (
          <span>
            默认数据库 {status.configured_project_count}/{status.eligible_project_count} 已配置
          </span>
        ) : null}
        {status ? <span>{status.ready_project_count}/{status.project_count} 个数据库目标可用</span> : null}
        {status?.warning_count ? (
          <button
            type="button"
            className="table-relation-warning-trigger"
            data-attention={status.attention_warning_count > 0}
            aria-expanded={showWarnings}
            aria-controls="table-relation-warnings"
            onClick={() => {
              if (!showWarnings) {
                setWarningDisposition(
                  status.attention_warning_count > 0 ? "attention" : "expected",
                );
                setWarningCode("");
                setWarningProjectId("");
              }
              setShowWarnings((current) => !current);
            }}
          >
            {status.attention_warning_count > 0
              ? `${status.attention_warning_count} 条需要处理`
              : "查看扫描诊断"}
          </button>
        ) : null}
      </div>

      {failedProjects.length > 0 ? (
        <section className="table-relation-project-failures" aria-labelledby="failed-projects-title">
          <header>
            <div>
              <strong id="failed-projects-title">{failedProjects.length} 个项目扫描失败</strong>
              <span>选择项目后可使用上方更新按钮单独重试。</span>
            </div>
          </header>
          <ul>
            {failedProjects.map((project) => (
              <li key={project.project_id} data-selected={projectId === project.project_id}>
                <div>
                  <strong>{project.project_name}</strong>
                  <span>{project.error_message?.trim() || "扫描失败，暂无更多原因"}</span>
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setProjectId(project.project_id)}
                  disabled={rebuildScope !== null}
                >
                  {projectId === project.project_id ? "已选择" : "选择项目"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {showWarnings ? (
        <WarningDiagnostics
          report={warningReport}
          loading={warningsLoading}
          error={warningsError}
          selectedCode={warningCode}
          selectedProjectId={warningProjectId}
          selectedDisposition={warningDisposition}
          query={warningQuery}
          onSelectCode={setWarningCode}
          onSelectProjectId={setWarningProjectId}
          onSelectDisposition={(disposition) => {
            setWarningDisposition(disposition);
            setWarningCode("");
            setWarningProjectId("");
          }}
          onQuery={setWarningQuery}
          onClose={() => setShowWarnings(false)}
        />
      ) : null}

      {showWhitelist ? (
        <SqlWhitelistDialog
          configuration={whitelist}
          draft={whitelistDraft}
          loading={whitelistLoading}
          saving={whitelistSaving}
          error={whitelistError}
          onDraft={setWhitelistDraft}
          onIncludeSuggested={includeSuggestedPaths}
          onClose={() => {
            if (whitelistSaving) return;
            setShowWhitelist(false);
            setWhitelistError(null);
          }}
          onSave={() => void saveWhitelist()}
        />
      ) : null}

      {status?.status === "ready" || status?.status === "partial" ? (
        <div className="table-relation-layout">
          <aside className="table-relation-table-list" aria-label="可查询表">
            <label className="table-relation-search">
              <span>查找精确表</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="例如 cs_dsly_basic_cargo"
              />
            </label>
            <div>
              {filteredTables.map((table) => (
                <button
                  type="button"
                  key={identityKey(table)}
                  data-active={context ? identityKey(context.root_table) === identityKey(table) : false}
                  onClick={() => selectTable(table)}
                >
                  <strong>{table.table_name}</strong>
                  <span>{table.project_name} · {table.database_key} · {table.relation_count} 组</span>
                </button>
              ))}
              {!filteredTables.length ? <p className="empty-state">没有匹配的已观察关联表。</p> : null}
            </div>
          </aside>

          <div className="table-relation-main">
            {context ? (
              <RelationGraph
                context={context}
                selectedJoinId={selectedJoin?.relation_id ?? null}
                onSelectJoin={setSelectedJoinId}
                onSelectTable={focusRelated}
              />
            ) : (
              <div className="table-relation-welcome">
                <strong>选择一张表查看直接关联</strong>
                <p>第一版只返回一跳关系；每条边都可查看 SQL 路径和关联表达式。</p>
              </div>
            )}
          </div>
          {context ? <EvidencePanel join={selectedJoin} /> : null}
        </div>
      ) : (
        <div className="table-relation-welcome">
          <strong>{status?.status === "failed" ? "上次扫描没有产生可用索引" : "先构建一次表关联索引"}</strong>
          <p>
            {status?.configured_project_count !== status?.eligible_project_count
              ? "请由本机 AI 或运维为每个后端项目配置一个表关联默认数据库。"
              : status?.error_message
                ?? "刷新会扫描后端项目中的 SQL 文件，并通过默认数据库核实表和字段。"}
          </p>
        </div>
      )}
    </section>
  );
}

function SqlWhitelistDialog({
  configuration,
  draft,
  loading,
  saving,
  error,
  onDraft,
  onIncludeSuggested,
  onClose,
  onSave,
}: {
  configuration: TableRelationSqlWhitelistConfiguration | null;
  draft: string;
  loading: boolean;
  saving: boolean;
  error: string | null;
  onDraft: (value: string) => void;
  onIncludeSuggested: () => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const pathCount = draft.split("\n").filter((item) => item.trim()).length;
  return (
    <div className="project-settings-modal" role="presentation">
      <section
        className="management-modal table-relation-whitelist-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="table-relation-whitelist-title"
        onKeyDown={(event) => {
          if (event.key === "Escape" && !saving) onClose();
        }}
      >
        <header>
          <div>
            <span className="file-chip">项目级扫描排除</span>
            <h2 id="table-relation-whitelist-title">
              {configuration?.project_name ?? "当前项目"} SQL 白名单
            </h2>
          </div>
          <button
            type="button"
            className="close-button"
            aria-label="关闭 SQL 白名单"
            disabled={saving}
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <p className="table-relation-whitelist-notice">
          白名单按项目相对路径精确匹配。命中后整个 SQL 文件不参与扫描，其中原本可识别的关系也会一并忽略。
        </p>

        <section className="table-relation-whitelist-rules" aria-labelledby="automatic-rules-title">
          <header>
            <strong id="automatic-rules-title">系统白名单</strong>
            <span>自动生效，不需要填写文件路径</span>
          </header>
          <div>
            {configuration?.automatic_rules.map((rule) => (
              <article key={rule.code}>
                <strong>{rule.label}</strong>
                <p>{rule.description}</p>
              </article>
            ))}
          </div>
        </section>

        <label className="table-relation-whitelist-editor">
          <span>项目路径白名单 · {pathCount} 个文件</span>
          <textarea
            value={draft}
            disabled={loading || saving}
            onChange={(event) => onDraft(event.target.value)}
            placeholder="每行一个项目相对路径，例如：src/main/resources/sql-ext/example.sql"
          />
        </label>

        {configuration?.suggested_paths.length ? (
          <div className="table-relation-whitelist-suggestions">
            <div>
              <strong>{configuration.suggested_paths.length} 个当前异常 SQL 文件</strong>
              <span>可一次加入编辑区，保存前仍可删除任意路径。</span>
            </div>
            <button
              type="button"
              className="secondary-button"
              disabled={loading || saving}
              onClick={onIncludeSuggested}
            >
              加入当前异常 SQL
            </button>
          </div>
        ) : null}

        {loading ? <p className="empty-state">正在读取白名单…</p> : null}
        {error ? <div className="error-banner" role="alert">{error}</div> : null}

        <footer>
          <button type="button" className="secondary-button" disabled={saving} onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={loading || saving || !configuration}
            onClick={onSave}
          >
            {saving ? "保存并更新中…" : "保存并更新当前项目"}
          </button>
        </footer>
      </section>
    </div>
  );
}

function WarningDiagnostics({
  report,
  loading,
  error,
  selectedCode,
  selectedProjectId,
  selectedDisposition,
  query,
  onSelectCode,
  onSelectProjectId,
  onSelectDisposition,
  onQuery,
  onClose,
}: {
  report: TableRelationWarningList | null;
  loading: boolean;
  error: string | null;
  selectedCode: string;
  selectedProjectId: string;
  selectedDisposition: "attention" | "expected";
  query: string;
  onSelectCode: (code: string) => void;
  onSelectProjectId: (projectId: string) => void;
  onSelectDisposition: (disposition: "attention" | "expected") => void;
  onQuery: (query: string) => void;
  onClose: () => void;
}) {
  const classificationLabels = {
    source_error: "源码错误",
    preprocessor: "预处理边界",
    metadata: "元数据未确认",
    safe_skip: "安全跳过",
  } as const;
  return (
    <section id="table-relation-warnings" className="table-relation-diagnostics" aria-label="跳过提示详情">
      <header>
        <div>
          <strong>跳过提示诊断</strong>
          <span>这些记录没有生成关系边，可按原因确认是语法边界还是数据库元数据问题。</span>
        </div>
        <button type="button" className="secondary-button" onClick={onClose}>收起</button>
      </header>
      <div className="table-relation-warning-filters">
        <div>
          <div className="table-relation-warning-dispositions" aria-label="诊断类型筛选">
            <button
              type="button"
              data-active={selectedDisposition === "attention"}
              onClick={() => onSelectDisposition("attention")}
            >
              需要处理 <span>{report?.attention_total ?? 0}</span>
            </button>
            <button
              type="button"
              data-active={selectedDisposition === "expected"}
              onClick={() => onSelectDisposition("expected")}
            >
              正常忽略 <span>{report?.expected_total ?? 0}</span>
            </button>
          </div>
          <div className="table-relation-warning-projects" aria-label="诊断项目筛选">
            <button
              type="button"
              data-active={!selectedProjectId}
              onClick={() => onSelectProjectId("")}
            >
              全部项目
            </button>
            {report?.projects.map((project) => (
              <button
                type="button"
                key={`${project.project_id}:${project.database_key}`}
                data-active={selectedProjectId === project.project_id}
                onClick={() => onSelectProjectId(project.project_id)}
                title={project.database_key}
              >
                {project.project_name} <span>{project.count}</span>
              </button>
            ))}
          </div>
          <div className="table-relation-warning-categories" aria-label="提示原因筛选">
            <button type="button" data-active={!selectedCode} onClick={() => onSelectCode("")}>
              全部
            </button>
            {report?.categories.map((category) => (
              <button
                type="button"
                key={category.code}
                data-active={selectedCode === category.code}
                onClick={() => onSelectCode(category.code)}
              >
                {category.label} <span>{category.count}</span>
                <small>{classificationLabels[category.classification]}</small>
              </button>
            ))}
          </div>
        </div>
        <label>
          <span>搜索路径或表达式</span>
          <input
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder="例如 cargo_query 或 category_id"
          />
        </label>
      </div>
      {error ? <div className="error-banner" role="alert">{error}</div> : null}
      <div className="table-relation-warning-summary" aria-live="polite">
        {loading ? "正在读取诊断…" : `匹配 ${report?.total ?? 0} 次，显示前 ${report?.warnings.length ?? 0} 条归并记录`}
      </div>
      <div className="table-relation-warning-list">
        {report?.warnings.map((warning) => (
          <article
            key={[
              warning.project_id,
              warning.database_key,
              warning.source_path,
              warning.code,
              warning.expression ?? "",
              warning.message,
            ].join("\u0000")}
          >
            <header>
              <strong>{warning.category} · {classificationLabels[warning.classification]}</strong>
              <span>{warning.project_name} · {warning.database_key} · {warning.occurrence_count} 次</span>
            </header>
            <code>{warning.source_path}</code>
            <p>{warning.message}</p>
            {warning.expression ? <pre>{warning.expression}</pre> : null}
          </article>
        ))}
        {!loading && !error && report && !report.warnings.length ? (
          <p className="empty-state">没有符合当前筛选条件的跳过提示。</p>
        ) : null}
      </div>
    </section>
  );
}

function RelationGraph({
  context,
  selectedJoinId,
  onSelectJoin,
  onSelectTable,
}: {
  context: TableRelationContext;
  selectedJoinId: string | null;
  onSelectJoin: (id: string) => void;
  onSelectTable: (table: TableRelationIdentity) => void;
}) {
  const center = { x: 450, y: 250 };
  const nodes = context.joins.map((join, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(context.joins.length, 1) - Math.PI / 2;
    return {
      join,
      table: otherTable(join, context.root_table),
      x: center.x + Math.cos(angle) * 300,
      y: center.y + Math.sin(angle) * 175,
    };
  });
  return (
    <div className="table-relation-graph" aria-label={`${context.root_table.table_name} 的直接 SQL 关联图`}>
      <svg viewBox="0 0 900 500" role="img">
        <title>{context.root_table.table_name} 的无方向 SQL 等值关联</title>
        {nodes.map(({ join, x, y }) => (
          <g key={`edge-${join.relation_id}`}>
            <line className={join.relation_id === selectedJoinId ? "selected" : ""} x1={center.x} y1={center.y} x2={x} y2={y} />
            <foreignObject x={(center.x + x) / 2 - 56} y={(center.y + y) / 2 - 15} width="112" height="30">
              <button
                className="table-relation-edge-label"
                data-active={join.relation_id === selectedJoinId}
                type="button"
                onClick={() => onSelectJoin(join.relation_id)}
              >SQL 等值关联</button>
            </foreignObject>
          </g>
        ))}
        <GraphNode table={context.root_table} x={center.x} y={center.y} root />
        {nodes.map(({ table, join, x, y }) => (
          <GraphNode key={join.relation_id} table={table} x={x} y={y} onClick={() => onSelectTable(table)} />
        ))}
      </svg>
      <div className="table-relation-mobile-list">
        {nodes.map(({ join, table }) => (
          <button key={join.relation_id} type="button" onClick={() => onSelectJoin(join.relation_id)}>
            <strong>{context.root_table.table_name}</strong>
            <span>— SQL 等值关联 —</span>
            <strong>{table.table_name}</strong>
          </button>
        ))}
      </div>
    </div>
  );
}

function GraphNode({ table, x, y, root = false, onClick }: {
  table: TableRelationIdentity;
  x: number;
  y: number;
  root?: boolean;
  onClick?: () => void;
}) {
  const label = table.table_name.length > 28 ? `${table.table_name.slice(0, 27)}…` : table.table_name;
  return (
    <g className={root ? "table-relation-node root" : "table-relation-node"} transform={`translate(${x - 115} ${y - 39})`}>
      <rect width="230" height="78" rx="13" />
      <text x="16" y="31">{label}</text>
      <text className="meta" x="16" y="56">{table.project_name} · {table.database_key}</text>
      {!root ? (
        <foreignObject x="0" y="0" width="230" height="78">
          <button type="button" aria-label={`以 ${table.table_name} 为中心`} onClick={onClick} />
        </foreignObject>
      ) : null}
    </g>
  );
}

function EvidencePanel({ join }: { join: ObservedTableJoin | null }) {
  if (!join) return null;
  return (
    <aside className="table-relation-evidence" aria-label="关联证据">
      <header>
        <div>
          <span>关联证据</span>
          <strong>{join.table_a.table_name} ↔ {join.table_b.table_name}</strong>
        </div>
        <span>{join.source_file_count} 个文件 · {join.statement_count} 条语句</span>
      </header>
      <div className="table-relation-pairs">
        {join.column_pairs.map((pair) => (
          <code key={`${pair.column_a}-${pair.column_b}`}>{pair.column_a} = {pair.column_b}</code>
        ))}
      </div>
      {join.evidence.map((evidence, index) => (
        <article key={`${evidence.source_path}-${evidence.join_expression}-${index}`}>
          <code>{evidence.source_path}</code>
          <strong>{evidence.join_expression}</strong>
          {evidence.template_derived ? (
            <p className="table-relation-preprocess-note">
              模板预处理 · {evidence.preprocess_profile_id}
              {evidence.applied_rules.length > 0
                ? ` · ${evidence.applied_rules.join(" → ")}`
                : ""}
            </p>
          ) : null}
          {evidence.sql_statement ? <pre>{evidence.sql_statement}</pre> : null}
        </article>
      ))}
    </aside>
  );
}
