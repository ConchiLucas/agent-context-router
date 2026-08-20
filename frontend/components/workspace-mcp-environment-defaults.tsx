"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { WorkspaceDataSourceOverview } from "@/components/workspace-data-source-overview";
import {
  getWorkspace,
  getWorkspaceEnvironments,
  getWorkspaceNacosProfiles,
} from "@/lib/api";
import type {
  NacosProfileSummary,
  WorkspaceEnvironmentList,
  WorkspaceNacosProfiles,
  WorkspaceSummary,
} from "@/lib/types";

interface WorkspaceMcpEnvironmentDefaultsProps {
  workspaceId: string;
}

export function WorkspaceMcpEnvironmentDefaults({
  workspaceId,
}: WorkspaceMcpEnvironmentDefaultsProps) {
  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null);
  const [configuration, setConfiguration] =
    useState<WorkspaceEnvironmentList | null>(null);
  const [nacosProfiles, setNacosProfiles] =
    useState<WorkspaceNacosProfiles | null>(null);
  const [environment, setEnvironment] = useState("local");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [nextWorkspace, environments, nacos] = await Promise.all([
        getWorkspace(workspaceId),
        getWorkspaceEnvironments(workspaceId),
        getWorkspaceNacosProfiles(workspaceId),
      ]);
      setWorkspace(nextWorkspace);
      setConfiguration(environments);
      setNacosProfiles(nacos);
      const keys = new Set(environments.environments.map((item) => item.key));
      setEnvironment((current) =>
        keys.has(current) ? current : environments.default_environment,
      );
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "工作空间环境读取失败");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = useMemo(
    () => configuration?.environments.find((item) => item.key === environment),
    [configuration, environment],
  );
  const nacos = useMemo<NacosProfileSummary | null>(
    () => nacosProfiles?.profiles.find((item) => item.profile_key === environment) ?? null,
    [environment, nacosProfiles],
  );

  return (
    <main className="mcp-environment-page">
      <div className="mcp-environment-page-shell">
        <header className="mcp-environment-page-header workspace-environment-detail-header">
          <div>
            <span className="section-eyebrow">Workspace environment</span>
            <h1>工作空间环境</h1>
            <p>
              环境属于当前工作空间；新任务未传 <code>environment</code> 时使用
              <code> local</code>，任务后续的数据库、中间件和表关联调用继承同一环境。
            </p>
          </div>
          <div className="workspace-environment-header-actions">
            <label className="workspace-environment-select">
              <span>查看环境</span>
              <select
                value={environment}
                disabled={loading || (configuration?.environments.length ?? 0) <= 1}
                onChange={(event) => setEnvironment(event.target.value)}
              >
                {(configuration?.environments ?? []).map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.display_name}（{item.key}）
                  </option>
                ))}
              </select>
            </label>
            <Link className="secondary-button mcp-environment-back-link" href="/">
              返回工作空间
            </Link>
          </div>
        </header>

        {workspace ? (
          <section className="mcp-environment-workspace-card" aria-label="当前工作空间">
            <div>
              <span>当前工作空间</span>
              <strong>{workspace.name}</strong>
            </div>
            <code>{workspace.root_path}</code>
          </section>
        ) : null}

        {loadError ? (
          <div className="error-banner mcp-environment-load-error" role="alert">
            <span>{loadError}</span>
            <button type="button" className="secondary-button" onClick={() => void load()}>
              重新加载
            </button>
          </div>
        ) : null}

        {loading ? <p className="empty-message">正在读取工作空间环境…</p> : null}

        {!loading && !loadError && selected ? (
          <>
            <section className="workspace-environment-flow-grid" aria-label="当前环境流转">
              <article className="workspace-environment-flow-card">
                <span className="workspace-environment-card-label">当前环境</span>
                <strong>{selected.display_name}</strong>
                <code>{selected.key}</code>
                <p>
                  {selected.is_default
                    ? "这是工作空间初始环境；prepare 未显式传环境时从这里开始。"
                    : "prepare 显式选择该环境后，后续环境感知工具默认继承它。"}
                </p>
              </article>

              <article className="workspace-environment-flow-card">
                <span className="workspace-environment-card-label">Nacos 映射</span>
                {nacos ? (
                  <>
                    <strong>{nacos.base_url}</strong>
                    <code>{nacos.namespace_id}</code>
                    <p>
                      1 个环境对应 1 个 Nacos 配置；当前声明 {nacos.components.length} 个组件。
                    </p>
                  </>
                ) : (
                  <>
                    <strong>未配置</strong>
                    <p>当前环境没有 Nacos 配置，读取中间件上下文时会明确返回未配置。</p>
                  </>
                )}
              </article>

              <article className="workspace-environment-flow-card workspace-environment-flow-card-wide">
                <span className="workspace-environment-card-label">MCP 继承规则</span>
                <strong>显式环境优先，省略时继承任务环境</strong>
                <p>
                  <code>prepare_task_context</code> 创建任务环境；
                  <code>read_middleware_context</code>、<code>read_table_relations</code> 和
                  <code>search_relation_tables</code> 可显式覆盖。数据库搜索、只读查询和
                  <code>read_task_context</code> 始终使用任务快照，避免中途静默换库。
                </p>
              </article>
            </section>

            <section className="workspace-environment-data-sources" aria-labelledby="environment-data-source-title">
              <header>
                <div>
                  <span className="section-eyebrow">Environment data sources</span>
                  <h2 id="environment-data-source-title">数据源汇总</h2>
                </div>
                <p>
                  数据库本身不区分环境；这里仅展示 {selected.display_name} 关联的项目数据库，
                  同一个数据库可以被多个环境复用。
                </p>
              </header>
              <WorkspaceDataSourceOverview
                key={environment}
                workspaceId={workspaceId}
                environment={environment}
              />
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}
