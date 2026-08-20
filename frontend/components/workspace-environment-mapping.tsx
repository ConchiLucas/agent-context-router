"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getWorkspaceDatabaseEnvironmentMappings,
  getWorkspaceEnvironmentConfig,
} from "@/lib/api";
import { formatEnvironmentJson } from "@/lib/environment-config";
import type {
  DatabaseEnvironmentTarget,
  WorkspaceDatabaseEnvironmentMapping,
  WorkspaceDatabaseEnvironmentMappings,
  WorkspaceEnvironmentConfig,
  WorkspaceSummary,
} from "@/lib/types";

type LegacyDatabaseEnvironment = "test" | "uat";
const ENVIRONMENTS: LegacyDatabaseEnvironment[] = ["test", "uat"];
type EnvironmentPanelTab = "database-mappings" | "environment-json";
type MappingStatusFilter = "all" | "complete" | "issue";

const ENVIRONMENT_LABELS: Record<LegacyDatabaseEnvironment, string> = {
  test: "TEST",
  uat: "UAT",
};

const ISSUE_LABELS: Record<string, string> = {
  alias_conflict: "MCP 别名重复",
  ambiguous_match: "存在多个同后缀候选",
  database_unavailable: "数据库不可用",
  engine_mismatch: "TEST/UAT 数据库类型不同",
  namespace_mismatch: "TEST/UAT 命名空间类型不同",
  missing_mcp_alias: "缺少 MCP 别名",
  missing_test: "缺少 TEST 数据库",
  missing_uat: "缺少 UAT 数据库",
};

interface MappingRow {
  key: string;
  projectId: string;
  projectName: string;
  mapping: WorkspaceDatabaseEnvironmentMapping;
  issues: string[];
}

interface WorkspaceEnvironmentMappingProps {
  workspace: WorkspaceSummary;
  onClose: () => void;
  onEnvironmentChanged?: (environment: LegacyDatabaseEnvironment | null) => void;
}

function issueLabel(issue: string): string {
  return ISSUE_LABELS[issue] ?? issue.replaceAll("_", " ");
}

function targetTitle(target: DatabaseEnvironmentTarget): string {
  return target.database_display_name || target.database_name;
}

function targetIssues(
  target: DatabaseEnvironmentTarget,
  environment: LegacyDatabaseEnvironment,
): string[] {
  const label = ENVIRONMENT_LABELS[environment];
  const issues: string[] = [];
  if (!target.available) issues.push(`${label} 数据库不可用`);
  if (!target.readonly) issues.push(`${label} 授权不是只读`);
  if (target.system_database) issues.push(`${label} 是系统数据库`);
  return issues;
}

function evaluateMapping(
  mapping: WorkspaceDatabaseEnvironmentMapping,
  aliasCount: number,
): string[] {
  const issues: string[] = [];
  const testTarget = mapping.targets.test;
  const uatTarget = mapping.targets.uat;

  if (!mapping.logical_name.trim()) issues.push("缺少逻辑数据库名称");
  if (!mapping.mcp_alias.trim()) issues.push(ISSUE_LABELS.missing_mcp_alias);
  if (mapping.mcp_alias.trim() && aliasCount > 1) {
    issues.push(ISSUE_LABELS.alias_conflict);
  }
  if (!testTarget) issues.push(ISSUE_LABELS.missing_test);
  if (!uatTarget) issues.push(ISSUE_LABELS.missing_uat);
  if (
    testTarget &&
    uatTarget &&
    testTarget.engine !== uatTarget.engine
  ) {
    issues.push(ISSUE_LABELS.engine_mismatch);
  }
  if (
    testTarget &&
    uatTarget &&
    testTarget.namespace_type !== uatTarget.namespace_type
  ) {
    issues.push(ISSUE_LABELS.namespace_mismatch);
  }

  if (testTarget) issues.push(...targetIssues(testTarget, "test"));
  if (uatTarget) issues.push(...targetIssues(uatTarget, "uat"));
  if (!["complete", "suggested"].includes(mapping.status)) {
    const serverIssues =
      mapping.issues.length > 0 ? mapping.issues : [mapping.status];
    issues.push(...serverIssues.map(issueLabel));
  }

  return Array.from(new Set(issues));
}

function resolveActiveEnvironment(
  configuration: WorkspaceDatabaseEnvironmentMappings | null,
  environmentConfig: WorkspaceEnvironmentConfig | null,
): LegacyDatabaseEnvironment | null {
  if (configuration?.configured) {
    return (
      configuration.active_environment ??
      environmentConfig?.active_environment ??
      null
    );
  }
  return environmentConfig?.configured
    ? environmentConfig.active_environment
    : null;
}

function environmentJsonValue(
  environmentConfig: WorkspaceEnvironmentConfig,
  environment: LegacyDatabaseEnvironment,
) {
  if (
    environmentConfig.active_environment === environment &&
    environmentConfig.active_config !== null
  ) {
    return environmentConfig.active_config;
  }
  return environmentConfig.environments[environment];
}

export function WorkspaceEnvironmentMapping({
  workspace,
  onClose,
  onEnvironmentChanged,
}: WorkspaceEnvironmentMappingProps) {
  const [configuration, setConfiguration] =
    useState<WorkspaceDatabaseEnvironmentMappings | null>(null);
  const [environmentConfig, setEnvironmentConfig] =
    useState<WorkspaceEnvironmentConfig | null>(null);
  const [panelTab, setPanelTab] =
    useState<EnvironmentPanelTab>("database-mappings");
  const [statusFilter, setStatusFilter] =
    useState<MappingStatusFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchEnvironmentState(): Promise<{
    configuration: WorkspaceDatabaseEnvironmentMappings;
    environmentConfig: WorkspaceEnvironmentConfig;
  }> {
    let [nextConfiguration, nextEnvironmentConfig] = await Promise.all([
      getWorkspaceDatabaseEnvironmentMappings(workspace.id),
      getWorkspaceEnvironmentConfig(workspace.id),
    ]);
    if (nextConfiguration.revision !== nextEnvironmentConfig.revision) {
      [nextConfiguration, nextEnvironmentConfig] = await Promise.all([
        getWorkspaceDatabaseEnvironmentMappings(workspace.id),
        getWorkspaceEnvironmentConfig(workspace.id),
      ]);
    }
    if (nextConfiguration.revision !== nextEnvironmentConfig.revision) {
      throw new Error("环境配置版本正在变化，请稍后重新加载。");
    }
    return {
      configuration: nextConfiguration,
      environmentConfig: nextEnvironmentConfig,
    };
  }

  async function loadEnvironmentState(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const next = await fetchEnvironmentState();
      setConfiguration(next.configuration);
      setEnvironmentConfig(next.environmentConfig);
      onEnvironmentChanged?.(
        resolveActiveEnvironment(next.configuration, next.environmentConfig),
      );
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "环境详情读取失败",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadEnvironmentState();
    // The modal is remounted for each workspace, so its identifier is stable
    // for the lifetime of this request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace.id]);

  const aliasCounts = useMemo(() => {
    const counts = new Map<string, number>();
    configuration?.projects.forEach((project) => {
      project.mappings.forEach((mapping) => {
        const alias = mapping.mcp_alias.trim().toLocaleLowerCase();
        if (alias) counts.set(alias, (counts.get(alias) ?? 0) + 1);
      });
    });
    return counts;
  }, [configuration]);

  const rows = useMemo<MappingRow[]>(
    () =>
      configuration?.projects
        .filter((project) => project.project_kind === "backend")
        .flatMap((project) =>
          project.mappings.map((mapping, index) => {
            const normalizedAlias = mapping.mcp_alias
              .trim()
              .toLocaleLowerCase();
            return {
              key:
                mapping.id ??
                `${project.project_id}:${mapping.logical_name || mapping.mcp_alias || index}`,
              projectId: project.project_id,
              projectName: project.project_name,
              mapping,
              issues: evaluateMapping(
                mapping,
                normalizedAlias
                  ? (aliasCounts.get(normalizedAlias) ?? 0)
                  : 0,
              ),
            };
          }),
        ) ?? [],
    [aliasCounts, configuration],
  );

  const visibleRows = useMemo(
    () =>
      rows.filter((row) => {
        if (statusFilter === "complete") return row.issues.length === 0;
        if (statusFilter === "issue") return row.issues.length > 0;
        return true;
      }),
    [rows, statusFilter],
  );

  const completeCount = rows.filter((row) => row.issues.length === 0).length;
  const issueCount = rows.length - completeCount;
  const backendProjectCount =
    configuration?.projects.filter(
      (project) => project.project_kind === "backend",
    ).length ?? 0;
  const activeEnvironment = resolveActiveEnvironment(
    configuration,
    environmentConfig,
  );
  const environmentConfigured = Boolean(
    configuration?.configured || environmentConfig?.configured,
  );
  const revision = configuration?.revision ?? environmentConfig?.revision;
  const environmentJson = useMemo(
    () => ({
      test: environmentConfig
        ? formatEnvironmentJson(
            environmentJsonValue(environmentConfig, "test"),
          )
        : "{}",
      uat: environmentConfig
        ? formatEnvironmentJson(
            environmentJsonValue(environmentConfig, "uat"),
          )
        : "{}",
    }),
    [environmentConfig],
  );

  return (
    <div className="environment-mapping-modal" role="presentation">
      <section
        className="environment-mapping-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`${workspace.name} 工作空间环境详情`}
      >
        <header className="environment-mapping-header">
          <div>
            <span className="file-chip">只读环境</span>
            <h2>工作空间环境详情</h2>
            <p>
              查看 TEST / UAT 数据库映射和通用环境 JSON；页面不提供配置修改或环境切换。
            </p>
          </div>
          <div className="environment-mapping-header-actions">
            <div className="active-environment-summary">
              <span>默认环境</span>
              <strong data-environment={activeEnvironment ?? "unconfigured"}>
                {activeEnvironment
                  ? ENVIRONMENT_LABELS[activeEnvironment]
                  : "未配置"}
              </strong>
            </div>
            <div className="active-environment-summary">
              <span>Revision</span>
              <strong data-environment={revision ? "configured" : "unconfigured"}>
                {revision ?? "—"}
              </strong>
            </div>
            <button
              type="button"
              className="secondary-button"
              disabled={loading}
              onClick={() => void loadEnvironmentState()}
            >
              {loading ? "正在加载…" : "重新加载"}
            </button>
            <button
              type="button"
              className="close-button"
              aria-label="关闭工作空间环境详情"
              onClick={onClose}
            >
              ×
            </button>
          </div>
        </header>

        <div className="environment-mapping-guidance">
          <strong>只读说明</strong>
          <span>
            默认环境仅用于未指定环境的任务；AI 可通过
            prepare_task_context(environment=&quot;test&quot;|&quot;uat&quot;)
            为单个任务选择环境，不会修改这里的全局状态。
          </span>
        </div>

        <nav
          className="environment-config-tabs"
          role="tablist"
          aria-label="环境详情类型"
        >
          <button
            type="button"
            role="tab"
            aria-selected={panelTab === "database-mappings"}
            data-active={panelTab === "database-mappings"}
            onClick={() => setPanelTab("database-mappings")}
          >
            数据库映射
            <small>{rows.length}</small>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={panelTab === "environment-json"}
            data-active={panelTab === "environment-json"}
            onClick={() => setPanelTab("environment-json")}
          >
            环境 JSON
          </button>
        </nav>

        <div className="environment-mapping-content">
          {error ? (
            <div
              className="error-banner environment-mapping-error"
              role="alert"
            >
              <span>{error}</span>
              <button
                type="button"
                className="secondary-button"
                disabled={loading}
                onClick={() => void loadEnvironmentState()}
              >
                {loading ? "正在加载…" : "重新加载"}
              </button>
            </div>
          ) : null}

          {loading && !configuration ? (
            <p className="empty-message">正在读取环境详情…</p>
          ) : null}

          {panelTab === "database-mappings" &&
          !loading &&
          configuration ? (
            <>
              <div className="environment-mapping-toolbar">
                <div className="environment-mapping-counts">
                  <span>
                    <strong>{rows.length}</strong> 项映射
                  </span>
                  <span data-status="complete">
                    <strong>{completeCount}</strong> 项完整
                  </span>
                  <span data-status={issueCount > 0 ? "issue" : "complete"}>
                    <strong>{issueCount}</strong> 项有问题
                  </span>
                  <span>
                    <strong>
                      {environmentConfigured ? "已配置" : "未配置"}
                    </strong>
                    环境配置状态
                  </span>
                </div>
                <div className="environment-mapping-actions">
                  <label className="environment-issues-filter">
                    状态
                    <select
                      aria-label="映射状态筛选"
                      value={statusFilter}
                      onChange={(event) =>
                        setStatusFilter(
                          event.target.value as MappingStatusFilter,
                        )
                      }
                    >
                      <option value="all">全部</option>
                      <option value="complete">仅完整</option>
                      <option value="issue">仅问题</option>
                    </select>
                  </label>
                </div>
              </div>

              {backendProjectCount === 0 ? (
                <div className="environment-mapping-empty">
                  <h3>当前工作空间没有后端项目</h3>
                  <p>环境数据库映射不会包含前端项目。</p>
                </div>
              ) : rows.length === 0 ? (
                <div className="environment-mapping-empty">
                  <h3>还没有数据库环境映射</h3>
                  <p>
                    当前页面只负责查看；需要建立映射时，请让 AI
                    通过受控运维入口维护。
                  </p>
                </div>
              ) : visibleRows.length === 0 ? (
                <div className="environment-mapping-empty">
                  <h3>没有符合筛选条件的映射</h3>
                  <p>调整状态筛选可以查看其他映射。</p>
                </div>
              ) : (
                <div
                  className="environment-mapping-table"
                  role="table"
                  aria-label="项目 TEST 和 UAT 数据库映射"
                >
                  <div
                    className="environment-mapping-table-header"
                    role="row"
                  >
                    <span role="columnheader">项目 / 逻辑别名</span>
                    <span role="columnheader">TEST 数据库</span>
                    <span role="columnheader">UAT 数据库</span>
                    <span role="columnheader">状态</span>
                  </div>
                  <div className="environment-mapping-table-body">
                    {visibleRows.map((row) => (
                      <div
                        className="environment-mapping-row"
                        data-status={
                          row.issues.length === 0 ? "complete" : "issue"
                        }
                        role="row"
                        key={row.key}
                      >
                        <div
                          className="environment-mapping-identity"
                          role="cell"
                        >
                          <strong>{row.projectName}</strong>
                          <span>
                            {row.mapping.logical_name || "未设置逻辑名称"}
                          </span>
                          <code>
                            {row.mapping.mcp_alias || "未设置 MCP 别名"}
                          </code>
                        </div>

                        {ENVIRONMENTS.map((environment) => {
                          const target = row.mapping.targets[environment];
                          const suggestion =
                            row.mapping.suggested_targets[environment];
                          return (
                            <div
                              className="environment-target-cell"
                              data-active={activeEnvironment === environment}
                              role="cell"
                              key={`${row.projectId}:${environment}`}
                            >
                              {target ? (
                                <>
                                  <strong>{targetTitle(target)}</strong>
                                  <code>{target.database_name}</code>
                                  <small>
                                    {target.data_source_name} ·{" "}
                                    {target.engine.toUpperCase()} ·{" "}
                                    {target.namespace_type}
                                  </small>
                                  <small>
                                    {target.readonly ? "只读授权" : "可写授权"}
                                    {" · "}
                                    {target.available ? "数据库可用" : "数据库不可用"}
                                  </small>
                                </>
                              ) : (
                                <>
                                  <strong className="environment-target-missing">
                                    未配置
                                  </strong>
                                  <small>
                                    {suggestion
                                      ? `候选：${targetTitle(suggestion)}`
                                      : "没有可用候选"}
                                  </small>
                                </>
                              )}
                            </div>
                          );
                        })}

                        <div
                          className="environment-mapping-status"
                          role="cell"
                        >
                          <span
                            data-status={
                              row.issues.length === 0 ? "complete" : "issue"
                            }
                          >
                            {row.issues.length === 0 ? "完整" : "有问题"}
                          </span>
                          {row.issues.slice(0, 4).map((issue) => (
                            <small key={issue}>{issue}</small>
                          ))}
                          {row.issues.length > 4 ? (
                            <small>另有 {row.issues.length - 4} 个问题</small>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : null}

          {panelTab === "environment-json" &&
          !loading &&
          environmentConfig ? (
            <section className="environment-json-section">
              <header className="environment-json-intro">
                <div>
                  <span className="file-chip">只读 JSON</span>
                  <h3>TEST / UAT 环境配置</h3>
                  <p>
                    两份 JSON 用于展示 MQ、Redis、ES、MinIO
                    等通用环境差异；字段结构不由前端限定。
                  </p>
                </div>
              </header>

              {!environmentConfig.configured ? (
                <div
                  className="environment-json-prerequisite"
                  role="status"
                >
                  当前还没有保存通用环境 JSON。
                </div>
              ) : null}

              <div className="environment-json-editors">
                {ENVIRONMENTS.map((environment) => {
                  const isActive = activeEnvironment === environment;
                  const json = environmentJson[environment];
                  return (
                    <article
                      className="environment-json-editor"
                      data-active={isActive}
                      key={environment}
                    >
                      <header>
                        <div>
                          <strong>{ENVIRONMENT_LABELS[environment]}</strong>
                          <span>
                            {isActive ? "默认环境配置" : "备用环境配置"}
                          </span>
                        </div>
                        {isActive ? (
                          <span
                            className="environment-json-active-chip"
                            data-environment={environment}
                          >
                            默认
                          </span>
                        ) : null}
                      </header>
                      <pre
                        className="mcp-json-output"
                        aria-label={`${ENVIRONMENT_LABELS[environment]} 环境 JSON`}
                      >
                        <code>{json}</code>
                      </pre>
                      <footer data-status="valid">
                        <span>只读 JSON</span>
                        <small>{json.length} 字符</small>
                      </footer>
                    </article>
                  );
                })}
              </div>

              <div className="environment-json-privacy-note">
                <span>
                  环境 JSON 可能包含服务地址和访问凭据，仅会随 read_task_context
                  返回给可信本机 MCP 调用方；页面不会修改这些内容。
                </span>
                <strong>Revision {revision ?? "—"}</strong>
              </div>
            </section>
          ) : null}
        </div>

        <footer className="environment-mapping-footer">
          <span>
            所有配置修改由 AI 或运维入口完成；重新加载只执行读取，不会改变环境状态。
          </span>
          <div>
            <button
              type="button"
              className="primary-button"
              onClick={onClose}
            >
              关闭
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
