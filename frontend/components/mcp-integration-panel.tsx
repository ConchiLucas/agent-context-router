"use client";

import { useEffect, useState } from "react";

import { getMcpIntegration, runMcpIntegrationTest } from "@/lib/api";
import type {
  McpClientConfig,
  McpIntegrationInfo,
  McpIntegrationTestResult,
  WorkspaceSummary,
} from "@/lib/types";

type IntegrationTab = "connection" | "codex" | "antigravity" | "test";

interface McpIntegrationPanelProps {
  workspace: WorkspaceSummary;
  onClose: () => void;
}

const tabs: Array<{ id: IntegrationTab; label: string }> = [
  { id: "connection", label: "连接信息" },
  { id: "codex", label: "Codex" },
  { id: "antigravity", label: "Antigravity" },
  { id: "test", label: "连接测试" },
];

function ClientConfigGuide({
  client,
  copied,
  onCopy,
}: {
  client: McpClientConfig | undefined;
  copied: boolean;
  onCopy: (value: string, key: string) => void;
}) {
  if (!client) return <p className="empty-message">配置模板尚未加载。</p>;

  return (
    <section className="integration-guide">
      <div className="integration-guide-copy">
        <span className="file-chip">{client.title}</span>
        <h3>添加一个全局 MCP 服务</h3>
        <p>
          全局配置文件：<code>{client.config_path}</code>
        </p>
        {client.project_config_path ? (
          <p>
            也可以仅对当前工作空间配置：<code>{client.project_config_path}</code>
          </p>
        ) : null}
      </div>
      <div className="integration-code-block">
        <button
          type="button"
          className="secondary-button integration-copy-button"
          onClick={() => onCopy(client.config, `${client.client}-config`)}
        >
          {copied ? "已复制" : "复制配置"}
        </button>
        <pre>
          <code>{client.config}</code>
        </pre>
      </div>
      <div className="integration-note">
        <strong>接入后怎么用</strong>
        <p>
          新任务先调用 <code>prepare_task_context</code> 获取文档树、task_id 和工作空间可用数据库别名；
          文档目标不明确时先调用 <code>search_context_documents</code>，
          再按需读取选中的文档或章节；数据库仍按对象搜索、有界只读查询的顺序使用。
          没有匹配工作空间时，客户端继续使用普通源码检索。
        </p>
      </div>
    </section>
  );
}

export function McpIntegrationPanel({
  workspace,
  onClose,
}: McpIntegrationPanelProps) {
  const [tab, setTab] = useState<IntegrationTab>("connection");
  const [info, setInfo] = useState<McpIntegrationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] =
    useState<McpIntegrationTestResult | null>(null);

  useEffect(() => {
    let active = true;
    void getMcpIntegration()
      .then((result) => {
        if (!active) return;
        setInfo(result);
        setError(null);
      })
      .catch((requestError: Error) => {
        if (active) setError(requestError.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function copy(value: string, key: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey(null), 1800);
    } catch {
      setError("浏览器未允许写入剪贴板，请手动复制配置");
    }
  }

  async function runTest() {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await runMcpIntegrationTest(workspace.id));
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setTesting(false);
    }
  }

  const codex = info?.clients.find((client) => client.client === "codex");
  const antigravity = info?.clients.find(
    (client) => client.client === "antigravity",
  );
  const databaseToolsAvailable = Boolean(
    info?.tools.some((tool) => tool.name === "search_database_objects") &&
      info.tools.some((tool) => tool.name === "execute_database_query"),
  );

  return (
    <div className="mcp-integration-modal" role="presentation">
      <section
        className="mcp-integration-panel"
        role="dialog"
        aria-modal="true"
        aria-label="MCP 接入与测试"
      >
        <header className="mcp-integration-header">
          <div>
            <span className="file-chip">Streamable HTTP</span>
            <h2>MCP 接入与测试</h2>
            <p>复制客户端配置，并从当前服务验证文档与数据库上下文能力。</p>
          </div>
          <button
            type="button"
            className="close-button"
            aria-label="关闭 MCP 接入面板"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <nav className="mcp-integration-tabs" role="tablist" aria-label="MCP 接入步骤">
          {tabs.map((item) => (
            <button
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              data-active={tab === item.id}
              key={item.id}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="mcp-integration-content">
          {loading ? <p className="empty-message">正在读取接入信息…</p> : null}
          {error ? (
            <div className="error-banner" role="alert">
              {error}
            </div>
          ) : null}

          {!loading && info && tab === "connection" ? (
            <div className="integration-connection">
              <section className="integration-endpoint">
                <div>
                  <span>MCP 服务地址</span>
                  <strong>{info.service.url}</strong>
                  <small>
                    {info.service.name} · {info.service.transport}
                  </small>
                </div>
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => copy(info.service.url, "service-url")}
                >
                  {copiedKey === "service-url" ? "已复制" : "复制地址"}
                </button>
              </section>

              <section className="integration-readiness" aria-label="服务就绪状态">
                <article data-ready="true">
                  <span>传输协议</span>
                  <strong>{info.service.transport}</strong>
                </article>
                <article data-ready={info.readiness.database_configured}>
                  <span>任务数据库</span>
                  <strong>
                    {info.readiness.database_configured ? "已配置" : "未配置"}
                  </strong>
                </article>
                <article data-ready={info.readiness.workspace_count > 0}>
                  <span>可匹配工作空间</span>
                  <strong>{info.readiness.workspace_count} 个</strong>
                </article>
                <article data-ready={databaseToolsAvailable}>
                  <span>数据库工具</span>
                  <strong>{databaseToolsAvailable ? "已注册" : "未注册"}</strong>
                </article>
              </section>

              <section className="integration-tools">
                <div>
                  <span className="file-chip">可用工具</span>
                  <h3>客户端接入后会发现以下能力</h3>
                </div>
                {info.tools.map((tool, index) => (
                  <article key={tool.name}>
                    <span>{index + 1}</span>
                    <div>
                      <code>{tool.name}</code>
                      <p>{tool.description}</p>
                    </div>
                  </article>
                ))}
                <div className="integration-note">
                  <strong>数据库可用性</strong>
                  <p>
                    工具列表固定不随数据源变化；当前任务真正可用的数据库，以
                    <code> prepare_task_context </code>
                    返回的 databases 列表为准。
                  </p>
                </div>
              </section>
            </div>
          ) : null}

          {!loading && info && tab === "codex" ? (
            <ClientConfigGuide
              client={codex}
              copied={copiedKey === "codex-config"}
              onCopy={copy}
            />
          ) : null}

          {!loading && info && tab === "antigravity" ? (
            <ClientConfigGuide
              client={antigravity}
              copied={copiedKey === "antigravity-config"}
              onCopy={copy}
            />
          ) : null}

          {!loading && info && tab === "test" ? (
            <div className="integration-test">
              <section className="integration-test-controls">
                <div>
                  <span className="file-chip">端到端验证</span>
                  <h3>对当前工作空间执行真实 MCP 调用</h3>
                  <p>
                    测试会创建一条隐藏的 connection-test 任务并读取入口文档，不返回正文，也不会执行任何业务数据库查询。
                  </p>
                </div>
                <div className="integration-test-workspace">
                  <span>测试工作空间</span>
                  <strong>{workspace.name}</strong>
                  <code>{workspace.root_path}</code>
                </div>
                <button
                  type="button"
                  className="primary-button"
                  disabled={testing || !info.readiness.ready_for_full_test}
                  onClick={() => void runTest()}
                >
                  {testing ? "正在执行完整链路…" : "开始连接测试"}
                </button>
              </section>

              {!info.readiness.ready_for_full_test ? (
                <div className="integration-note integration-warning">
                  <strong>暂时不能执行完整测试</strong>
                  <p>
                    {!info.readiness.database_configured
                      ? "请先配置 PostgreSQL 任务数据库。"
                      : "请先添加至少一个工作空间。"}
                  </p>
                </div>
              ) : null}

              {testResult ? (
                <section className="integration-test-result" data-status={testResult.status}>
                  <header>
                    <div>
                      <span>
                        {testResult.status === "passed" ? "测试通过" : "测试未通过"}
                      </span>
                      <h3>{testResult.workspace_name ?? "MCP 接入测试"}</h3>
                    </div>
                    {testResult.task_id ? (
                      <code>
                        task #{testResult.task_id}
                        {testResult.read_call_id
                          ? ` · read #${testResult.read_call_id}`
                          : ""}
                      </code>
                    ) : null}
                  </header>
                  <ol>
                    {testResult.stages.map((stage) => (
                      <li data-status={stage.status} key={stage.key}>
                        <span aria-hidden="true" />
                        <div>
                          <strong>{stage.label}</strong>
                          <p>{stage.detail}</p>
                        </div>
                        <small>{stage.duration_ms} ms</small>
                      </li>
                    ))}
                  </ol>
                </section>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
